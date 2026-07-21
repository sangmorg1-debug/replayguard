from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .redaction import Redactor
from .schema import Event, EventKind, Run

ADAPTER_VERSION = "otel-1.0.0"
PINNED_CONVENTIONS = {"otlp": "1.10.0", "otel_semconv": "1.43.0", "openinference": "2026-07-snapshot"}
RESERVED = "_replayguard_otel"
CONTENT_ATTRIBUTE_KEYS = ("input.value", "input", "gen_ai.input.messages", "ai.prompt.messages", "ai.prompt",
                          "output.value", "output", "gen_ai.output.messages", "ai.response.text")


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=repr, separators=(",", ":")).encode()).hexdigest()


def _any_value(value: Any) -> Any:
    if not isinstance(value, dict): return value
    for key in ("stringValue", "boolValue", "intValue", "doubleValue", "bytesValue"):
        if key in value: return int(value[key]) if key == "intValue" else value[key]
    if "arrayValue" in value: return [_any_value(item) for item in value["arrayValue"].get("values", [])]
    if "kvlistValue" in value: return {item["key"]: _any_value(item.get("value")) for item in value["kvlistValue"].get("values", [])}
    return value


def _attributes(value: Any) -> dict[str, Any]:
    if isinstance(value, dict): return copy.deepcopy(value)
    return {item["key"]: _any_value(item.get("value")) for item in value or [] if isinstance(item, dict) and "key" in item}


def _to_any(value: Any) -> dict[str, Any]:
    if isinstance(value, bool): return {"boolValue": value}
    if isinstance(value, int): return {"intValue": str(value)}
    if isinstance(value, float): return {"doubleValue": value}
    if isinstance(value, list): return {"arrayValue": {"values": [_to_any(item) for item in value]}}
    if isinstance(value, dict): return {"kvlistValue": {"values": [{"key": key, "value": _to_any(item)} for key, item in value.items()]}}
    return {"stringValue": "" if value is None else str(value)}


def _to_attribute_list(value: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": key, "value": _to_any(item)} for key, item in value.items() if key != RESERVED]


def _parse_json(value: Any) -> Any:
    if not isinstance(value, str): return value
    try: return json.loads(value)
    except (json.JSONDecodeError, TypeError): return value


def _nanos_to_iso(value: int | str | None) -> str:
    if not value: return datetime.fromtimestamp(0, timezone.utc).isoformat()
    return datetime.fromtimestamp(int(value) / 1_000_000_000, timezone.utc).isoformat()


def _hr_to_iso(value: Any) -> str:
    if isinstance(value, list) and len(value) == 2: return _nanos_to_iso(int(value[0]) * 1_000_000_000 + int(value[1]))
    return _nanos_to_iso(value)


def _iso_to_nanos(value: str | None) -> str:
    if not value: return "0"
    return str(int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1_000_000_000))


def _raw_nanos(raw: dict[str, Any], base: str) -> str | None:
    direct = raw.get(base + "UnixNano")
    if direct is not None: return str(direct)
    pair = raw.get("startTime" if base == "startTime" else "endTime")
    if isinstance(pair, list) and len(pair) == 2: return str(int(pair[0]) * 1_000_000_000 + int(pair[1]))
    return None


def _trail_nanos(timestamp: str) -> int:
    return int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1_000_000) * 1000


def _duration_nanos(value: str | None) -> int:
    match = re.fullmatch(r"P(?:([0-9.]+)D)?T?(?:([0-9.]+)H)?(?:([0-9.]+)M)?(?:([0-9.]+)S)?", value or "")
    if not match: return 0
    days, hours, minutes, seconds = (Decimal(item or 0) for item in match.groups())
    return int((days * 86400 + hours * 3600 + minutes * 60 + seconds) * 1_000_000_000)


def _trail_spans(items: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]]:
    result = []
    def visit(item: dict[str, Any]) -> None:
        start = _trail_nanos(item["timestamp"]); raw = {"traceId": item["trace_id"], "spanId": item["span_id"],
            "name": item.get("span_name", "unnamed"), "kind": item.get("span_kind", "SPAN_KIND_UNSPECIFIED"),
            "startTimeUnixNano": str(start), "endTimeUnixNano": str(start + _duration_nanos(item.get("duration"))),
            "status": {"code": item.get("status_code", "Unset"), "message": item.get("status_message", "")},
            "attributes": copy.deepcopy(item.get("span_attributes", {})), "events": copy.deepcopy(item.get("events", [])),
            "links": copy.deepcopy(item.get("links", [])), "traceState": item.get("trace_state", "")}
        if item.get("parent_span_id"): raw["parentSpanId"] = item["parent_span_id"]
        if item.get("annotations") is not None: raw["attributes"]["trail.annotations"] = copy.deepcopy(item["annotations"])
        resource = {"attributes": _to_attribute_list(item.get("resource_attributes", {}))}
        scope = {"name": item.get("scope_name", ""), "version": item.get("scope_version", "")}
        result.append((raw, "trail-json", resource, scope))
        for child in item.get("child_spans", []): visit(child)
    for item in items: visit(item)
    return result


def _kind(name: str, attrs: dict[str, Any]) -> EventKind:
    hint = str(attrs.get("openinference.span.kind", "")).upper()
    operation = str(attrs.get("gen_ai.operation.name", attrs.get("ai.operationId", name))).lower()
    if hint in {"LLM", "EMBEDDING"} or any(item in operation for item in ("chat", "completion", "generatetext", "generateobject", "streamtext", "embed")): return EventKind.MODEL
    if hint == "RETRIEVER" or "retriev" in operation: return EventKind.RETRIEVAL
    if hint == "TOOL" or any(item in operation for item in ("tool", "execute")): return EventKind.TOOL
    if hint in {"AGENT", "CHAIN"} or "agent" in operation: return EventKind.AGENT_STEP
    return EventKind.ARTIFACT


def _status(value: Any) -> str:
    code = value.get("code") if isinstance(value, dict) else value
    return "error" if code in (2, "2", "STATUS_CODE_ERROR", "ERROR") else "ok"


def _span_to_event(span: dict[str, Any], *, source_format: str, resource: dict[str, Any], scope: dict[str, Any],
                    capture_content: bool = True) -> tuple[str, Event]:
    context = span.get("spanContext", {})
    trace_id = str(span.get("traceId") or context.get("traceId") or "unknown-trace")
    span_id = str(span.get("spanId") or context.get("spanId") or "unknown-span")
    parent = span.get("parentSpanId") or span.get("parentSpanContext", {}).get("spanId")
    redactor = Redactor()
    # Known secret patterns are stripped regardless of capture_content, matching Recorder.
    attrs = redactor.redact(_attributes(span.get("attributes", [])))
    start = _hr_to_iso(span.get("startTime") or span.get("startTimeUnixNano"))
    end = _hr_to_iso(span.get("endTime") or span.get("endTimeUnixNano")) if span.get("endTime") or span.get("endTimeUnixNano") else None
    request = _parse_json(attrs.get("input.value", attrs.get("input", attrs.get("gen_ai.input.messages", attrs.get("ai.prompt.messages", attrs.get("ai.prompt"))))))
    response = _parse_json(attrs.get("output.value", attrs.get("output", attrs.get("gen_ai.output.messages", attrs.get("ai.response.text")))))
    request_hash = _hash(request) if request is not None else None
    response_hash = _hash(response) if response is not None else None
    usage = {}
    aliases = {"input_tokens": ("gen_ai.usage.input_tokens", "llm.token_count.prompt", "ai.usage.promptTokens"),
               "output_tokens": ("gen_ai.usage.output_tokens", "llm.token_count.completion", "ai.usage.completionTokens")}
    for target, keys in aliases.items():
        for key in keys:
            if key in attrs: usage[target] = int(attrs[key]); break
    if capture_content:
        metadata = {"adapter_version": ADAPTER_VERSION, "source_format": source_format,
                    "raw_span": redactor.redact(copy.deepcopy(span)), "resource": redactor.redact(copy.deepcopy(resource)),
                    "scope": redactor.redact(copy.deepcopy(scope)), "original_started_at": start,
                    "original_ended_at": end, "original_name": span.get("name", "unnamed")}
    else:
        # No raw_span/resource/scope: those duplicate the same prompt/response content this
        # branch is stripping, and re-export fidelity is an accepted tradeoff for not capturing
        # content, matching Recorder's capture_content=False behavior elsewhere in the SDK.
        metadata = {"adapter_version": ADAPTER_VERSION, "source_format": source_format, "content_captured": False,
                    "original_started_at": start, "original_ended_at": end, "original_name": span.get("name", "unnamed")}
        attrs = {key: value for key, value in attrs.items() if key not in CONTENT_ATTRIBUTE_KEYS}
    attrs[RESERVED] = metadata
    event = Event(_kind(str(span.get("name", "unnamed")), attrs), str(span.get("name", "unnamed")), id=span_id,
                  parent_id=str(parent) if parent else None, started_at=start, ended_at=end, status=_status(span.get("status", {})),
                  attributes=attrs, request=request if capture_content else None,
                  response=response if capture_content else None,
                  request_hash=request_hash, response_hash=response_hash, usage=usage,
                  error={"message": span.get("status", {}).get("message", "OpenTelemetry span error")} if _status(span.get("status", {})) == "error" else None)
    if end: event.latency_ms = max(0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000)
    return trace_id, event


def import_traces(document: Any, *, capture_content: bool = True) -> list[Run]:
    """Import standard OTLP/JSON or OpenTelemetry JS flat-span JSON.

    capture_content defaults to True here because most callers (benchmark tooling, research
    experiments, round-trip fidelity tests) need real span content to do their job and already
    operate on authorized/public corpora. The CLI's `otel import` command, which persists
    arbitrary user-supplied traces into local storage, explicitly opts into False by default
    to match the rest of the SDK's content-off-by-default privacy posture (see cli.py).
    """
    spans: list[tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]] = []
    if isinstance(document, list):
        spans = [(item, "otel-js-flat", {}, {}) for item in document]
    elif isinstance(document, dict) and ("resourceSpans" in document or "resource_spans" in document):
        for resource_group in document.get("resourceSpans", document.get("resource_spans", [])):
            resource = copy.deepcopy(resource_group.get("resource", {}))
            for scope_group in resource_group.get("scopeSpans", resource_group.get("scope_spans", [])):
                scope = copy.deepcopy(scope_group.get("scope", {}))
                spans.extend((span, "otlp-json", resource, scope) for span in scope_group.get("spans", []))
    elif isinstance(document, dict) and "spans" in document:
        if document.get("trace_id") and any("span_name" in item for item in document["spans"]): spans = _trail_spans(document["spans"])
        else: spans = [(item, "flat-container", copy.deepcopy(document.get("resource", {})), copy.deepcopy(document.get("scope", {}))) for item in document["spans"]]
    else: raise ValueError("expected OTLP resourceSpans, a spans container, or a flat span array")
    grouped: dict[str, list[Event]] = defaultdict(list)
    for span, source_format, resource, scope in spans:
        trace_id, event = _span_to_event(span, source_format=source_format, resource=resource, scope=scope,
                                          capture_content=capture_content)
        grouped[trace_id].append(event)
    runs = []
    for trace_id, events in grouped.items():
        events.sort(key=lambda item: (item.started_at, item.id))
        roots = [item for item in events if not item.parent_id]
        run = Run(roots[0].name if roots else f"otel:{trace_id}", id=trace_id, created_at=min(item.started_at for item in events),
                  ended_at=max((item.ended_at for item in events if item.ended_at), default=None),
                  status="error" if any(item.status == "error" for item in events) else "ok",
                  attributes={"otel_adapter_version": ADAPTER_VERSION, "otel_conventions": PINNED_CONVENTIONS}, events=events)
        runs.append(run)
    return sorted(runs, key=lambda item: item.id)


def _event_to_span(event: Event, trace_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    metadata = event.attributes.get(RESERVED, {})
    raw = metadata.get("raw_span", {})
    allowed = {"traceState", "kind", "events", "links", "droppedAttributesCount", "droppedEventsCount",
               "droppedLinksCount", "flags"}
    span = {key: copy.deepcopy(value) for key, value in raw.items() if key in allowed}
    start_nanos = _raw_nanos(raw, "startTime") if event.started_at == metadata.get("original_started_at") else None
    end_nanos = _raw_nanos(raw, "endTime") if event.ended_at == metadata.get("original_ended_at") else None
    span.update({"traceId": trace_id, "spanId": event.id, "name": event.name,
                 "startTimeUnixNano": start_nanos or _iso_to_nanos(event.started_at), "endTimeUnixNano": end_nanos or _iso_to_nanos(event.ended_at),
                 "status": {"code": "STATUS_CODE_ERROR" if event.status == "error" else "STATUS_CODE_OK"}})
    if event.parent_id: span["parentSpanId"] = event.parent_id
    elif "parentSpanId" in span: span.pop("parentSpanId")
    span["attributes"] = _to_attribute_list({key: value for key, value in event.attributes.items() if key != RESERVED})
    return span, copy.deepcopy(metadata.get("resource", {})), copy.deepcopy(metadata.get("scope", {}))


def export_otlp(runs: list[Run] | Run) -> dict[str, Any]:
    if isinstance(runs, Run): runs = [runs]
    groups: dict[str, dict[str, Any]] = {}
    for run in runs:
        for event in run.events:
            span, resource, scope = _event_to_span(event, run.id)
            key = json.dumps([resource, scope], sort_keys=True, separators=(",", ":"))
            if key not in groups: groups[key] = {"resource": resource, "scopeSpans": [{"scope": scope, "spans": []}]}
            groups[key]["scopeSpans"][0]["spans"].append(span)
    return {"resourceSpans": list(groups.values())}


def normalized(document: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for run in import_traces(document):
        for event in run.events:
            metadata = event.attributes.get(RESERVED, {}); raw = metadata.get("raw_span", {})
            result.append({"trace_id": run.id, "span_id": event.id, "parent_span_id": event.parent_id, "name": event.name,
                           "start": event.started_at, "end": event.ended_at, "status": event.status,
                           "attributes": {key: value for key, value in event.attributes.items() if key != RESERVED},
                           "events": copy.deepcopy(raw.get("events", [])), "links": copy.deepcopy(raw.get("links", [])),
                           "kind": raw.get("kind"), "trace_state": raw.get("traceState"),
                           "resource": copy.deepcopy(metadata.get("resource", {})), "scope": copy.deepcopy(metadata.get("scope", {}))})
    return sorted(result, key=lambda item: (item["trace_id"], item["span_id"]))


def coverage(runs: list[Run]) -> dict[str, Any]:
    found = Counter(); mapped = Counter()
    for run in runs:
        for event in run.events:
            for key in event.attributes:
                if key == RESERVED: continue
                family = "gen_ai" if key.startswith("gen_ai.") else "openinference" if key.startswith(("openinference.", "llm.", "input.", "output.")) else "mcp" if "mcp" in key.lower() else "other"
                found[family] += 1
                if family != "other" or key.startswith("ai."): mapped[family] += 1
    return {"adapter_version": ADAPTER_VERSION, "conventions": PINNED_CONVENTIONS, "attribute_occurrences": dict(found),
            "recognized_occurrences": dict(mapped), "runs": len(runs), "spans": sum(len(item.events) for item in runs)}
