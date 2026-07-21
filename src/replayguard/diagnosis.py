from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .claim_graph import diagnose_claim_graph
from .schema import Event, EventKind, Run

CATEGORIES = (
    "Language-only", "Tool-related", "Poor Information Retrieval", "Incorrect Memory Usage",
    "Tool Output Misinterpretation", "Incorrect Problem Identification", "Tool Selection Errors",
    "Formatting Errors", "Instruction Non-compliance", "Tool Definition Issues", "Environment Setup Errors",
    "Rate Limiting", "Authentication Errors", "Service Errors", "Resource Not Found", "Resource Exhaustion",
    "Timeout Issues", "Context Handling Failures", "Resource Abuse", "Goal Deviation", "Task Orchestration",
)
FINAL_TOOL = re.compile(r"(?i)(final[_ ]?answer|submit|finish)")
EVIDENCE_CLAIM = re.compile(r"(?i)\b(according to|I (?:have )?(?:verified|confirmed|found)|the (?:record|search|source|report) (?:shows|states|says)|research (?:shows|indicates))\b")
TOOL_PLAN = re.compile(r"(?i)\b([a-z][a-z0-9_]*(?:search|browser|retriev)[a-z0-9_]*|(?:search|browser|retriev)[a-z0-9_]*)\b")
REQUIRED_MARKER = re.compile(r"(?i)(?:must|required|ensure|write|end(?:s|ing)? with|append)[^\n]{0,80}?(<[/]?[a-z][a-z0-9_-]*>|\[[A-Z_ -]{3,}\])")


@dataclass(slots=True)
class Suspect:
    span_id: str
    category: str
    score: float
    reason: str
    evidence: str
    deterministic: bool = True


@dataclass(slots=True)
class Diagnosis:
    run_id: str
    suspects: list[Suspect]
    inspected_spans: int
    engine_version: str = "1.0.0"
    claim_graph_suspects: list[Suspect] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"run_id": self.run_id, "engine_version": self.engine_version, "inspected_spans": self.inspected_spans,
                  "suspects": [asdict(item) for item in self.suspects]}
        if self.claim_graph_suspects is not None:
            result["experimental_claim_graph"] = [asdict(item) for item in self.claim_graph_suspects]
        return result


def _text(value: Any) -> str:
    if value is None: return ""
    if isinstance(value, str): return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _response_text(event: Event) -> str: return _text(event.response)


def _active_prompt(event: Event) -> str:
    """Return only the current instruction, excluding serialized chat history."""
    request = event.request
    if not isinstance(request, dict):
        return _text(request)
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        return _text(request)
    content = messages[-1].get("content") if isinstance(messages[-1], dict) else messages[-1]
    if isinstance(content, list):
        return "\n".join(_text(item.get("text", item)) if isinstance(item, dict) else _text(item) for item in content)
    return _text(content)


def _classify_error(text: str) -> tuple[str, str] | None:
    low = text.lower()
    rules = (
        (r"\b429\b|rate.?limit|too many requests", "Rate Limiting"),
        (r"\b(?:401|403)\b|unauthorized|forbidden|invalid (?:api )?key|authentication", "Authentication Errors"),
        (r"\b404\b|not found|does not exist", "Resource Not Found"),
        (r"\b5\d\d\b|service unavailable|bad gateway|internal server error", "Service Errors"),
        (r"timed? out|timeout|deadline exceeded", "Timeout Issues"),
        (r"out of memory|memoryerror|resource exhausted|no space left", "Resource Exhaustion"),
        (r"permission denied|missing dependency|module not found|environment", "Environment Setup Errors"),
        (r"context (?:window|length).*(?:exceed|overflow)|maximum context", "Context Handling Failures"),
    )
    for pattern, category in rules:
        match = re.search(pattern, low)
        if match: return category, match.group(0)
    return None


def _event_steps(run: Run) -> list[tuple[str, str]]:
    """Serialize each event into the (location, text) pairs the claim/evidence graph reads."""
    ordered = sorted(run.events, key=lambda item: (item.started_at, item.id))
    return [(event.id, " ".join((f"kind={event.kind.value} name={event.name} status={event.status}",
             "request=" + _text(event.request), "response=" + _response_text(event), "error=" + _text(event.error))))
            for event in ordered]


def _claim_graph_suspects(run: Run, max_candidates: int) -> list[Suspect]:
    """Experimental, non-gating signal (see docs/DIAGNOSE_CLAIM_GRAPH.md): weakly supported claims."""
    candidates, _ = diagnose_claim_graph(_event_steps(run), max_candidates=max_candidates)
    suspects = []
    for item in candidates:
        rule = item.evidence[0] if item.evidence else None
        reason = rule.message if rule else "Local claim/evidence graph signal."
        evidence = f"[{rule.rule_id}] {rule.excerpt}" if rule else ""
        suspects.append(Suspect(item.location, item.category or "Unclassified", item.confidence, reason, evidence, deterministic=False))
    return suspects


def diagnose(run: Run, *, max_candidates: int = 3, experimental_claim_graph: bool = False) -> Diagnosis:
    suspects: dict[tuple[str, str], Suspect] = {}
    ordered = sorted(run.events, key=lambda item: (item.started_at, item.id))

    def add(event: Event, category: str, score: float, reason: str, evidence: str) -> None:
        key = (event.id, category); candidate = Suspect(event.id, category, score, reason, evidence[:500])
        if key not in suspects or suspects[key].score < score: suspects[key] = candidate

    # Direct, observable failures.
    for event in ordered:
        combined = " ".join((_text(event.error), _response_text(event), _text(event.attributes.get("error.message"))))
        has_error_signal = bool(event.error or event.status == "error" or event.attributes.get("error.message"))
        classified = _classify_error(combined) if has_error_signal else None
        if classified:
            category, evidence = classified
            add(event, category, .99 if event.status == "error" or event.error else .9,
                "The span contains a deterministic error signature for this TRAIL category.", evidence)
        elif event.status == "error" or event.error:
            add(event, "Service Errors", .72, "The span is explicitly marked as failed but exposes no more specific signature.", combined)

        request, response = _active_prompt(event), _response_text(event)
        for marker in dict.fromkeys(REQUIRED_MARKER.findall(request)):
            if marker and marker not in response:
                add(event, "Instruction Non-compliance", .92,
                    "The span request requires a literal delimiter that is absent from its response.", f"missing required marker {marker}")
        if event.kind == EventKind.MODEL and re.search(r"(?i)(valid json|json format|strictly in json)", request):
            try: json.loads(response)
            except (json.JSONDecodeError, TypeError):
                add(event, "Formatting Errors", .88, "The model was required to return JSON but its response is not valid JSON.", response)

    # Unsupported claims of tool-derived evidence.
    evidence_tools: list[Event] = []
    for event in ordered:
        response = _response_text(event)
        if event.kind in {EventKind.TOOL, EventKind.RETRIEVAL} and not FINAL_TOOL.search(event.name): evidence_tools.append(event)
        if event.kind == EventKind.MODEL and EVIDENCE_CLAIM.search(response) and not evidence_tools:
            add(event, "Tool-related", .86,
                "The model claims tool- or source-derived evidence before any non-final tool/retrieval span appears.", EVIDENCE_CLAIM.search(response).group(0))

    # A model declares a retrieval plan, but execution jumps to a final-answer call.
    for index, event in enumerate(ordered):
        if event.kind != EventKind.MODEL: continue
        response = _response_text(event); planned = TOOL_PLAN.findall(response)
        if not planned: continue
        later = ordered[index + 1:]
        first_final = next((offset for offset, item in enumerate(later) if FINAL_TOOL.search(item.name)), None)
        if first_final is None: continue
        before_final = later[:first_final]
        if not any(item.kind in {EventKind.TOOL, EventKind.RETRIEVAL} and not FINAL_TOOL.search(item.name) for item in before_final):
            target = next((item for item in before_final if item.kind == EventKind.MODEL), event)
            add(target, "Goal Deviation", .84, "Execution proceeds to a final-answer tool without performing the retrieval operation declared in the plan.", ", ".join(planned))

    # Excessive repeated calls: TRAIL instructs localization at the final instance.
    calls: dict[str, list[Event]] = {}
    for event in ordered:
        if event.kind in {EventKind.TOOL, EventKind.RETRIEVAL}: calls.setdefault(event.name, []).append(event)
    for name, items in calls.items():
        if len(items) >= 5:
            add(items[-1], "Resource Abuse", min(.95, .6 + len(items) * .04),
                "The same external operation is repeated at least five times; localized at its final call.", f"{name}: {len(items)} calls")

    ranked = sorted(suspects.values(), key=lambda item: (-item.score, item.span_id, item.category))[:max_candidates]
    claim_graph_suspects = _claim_graph_suspects(run, max_candidates) if experimental_claim_graph else None
    return Diagnosis(run.id, ranked, len(run.events), claim_graph_suspects=claim_graph_suspects)


def load_ground_truth(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # One public TRAIL annotation at the pinned revision contains a trailing comma.
        return json.loads(re.sub(r",\s*([}\]])", r"\1", text))


def normalize_category(category: Any) -> str:
    value = str(category or "").lower().strip(); compact = value.replace(" ", "")
    aliases = {"taskorchestrationerror": "Task Orchestration", "taskorchestrationerrors": "Task Orchestration",
               "instructionnoncomplience": "Instruction Non-compliance"}
    if compact in aliases: return aliases[compact]
    for standard in CATEGORIES:
        candidate = standard.lower(); candidate_compact = candidate.replace(" ", "")
        if value == candidate or compact == candidate_compact or compact in candidate_compact:
            return standard
    return str(category or "")


def score_diagnosis(diagnosis: Diagnosis, ground_truth: dict[str, Any]) -> dict[str, Any]:
    expected = {(str(item.get("location")), normalize_category(item.get("category"))) for item in ground_truth.get("errors", [])}
    predicted = {(item.span_id, item.category) for item in diagnosis.suspects}
    matched = expected & predicted; precision = len(matched) / len(predicted) if predicted else float(not expected)
    recall = len(matched) / len(expected) if expected else float(not predicted)
    return {"trace_id": diagnosis.run_id, "expected_pairs": len(expected), "predicted_pairs": len(predicted), "matched_pairs": len(matched),
            "location_category_joint_accuracy": recall, "pair_precision": precision,
            "pair_recall": recall, "pair_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
            "matched": [{"location": location, "category": category} for location, category in sorted(matched)]}
