"""Deterministic, AgentRx-style trajectory invariants with auditable evidence."""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

from .diagnostic_candidates import DiagnosticCandidate, DiagnosticEvidence, merge_candidates
from .schema import Event, EventKind, Run

ERROR = re.compile(r"(?i)\b(error|failed|failure|exception|timed? out|not found|unauthorized|forbidden|invalid)\b")
CONSEQUENTIAL = re.compile(r"(?i)\b(cancel|modify|return|exchange|delete|purchase|send|transfer|book|create|update)[_\s-]")
CONFIRM = re.compile(r"(?i)\b(yes|confirm|confirmed|proceed|go ahead|do it|please do)\b")
AUTH_TOOL = re.compile(r"(?i)(find_user|authenticate|verify_identity|login)")
PRIVATE_TOOL = re.compile(r"(?i)(get_user|get_order|profile|account|cancel|modify|return|exchange)")


def _text(value: Any) -> str:
    if value is None: return ""
    if isinstance(value, str): return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _location(step: dict, index: int) -> str:
    return str(step.get("index") or step.get("id") or step.get("span_id") or index + 1)


def _calls(step: dict) -> list[tuple[str, Any, bool]]:
    result = []
    for call in step.get("tool_calls") or []:
        function = call.get("function", {}) if isinstance(call, dict) else {}
        name = function.get("name") if isinstance(function, dict) else None
        arguments = function.get("arguments") if isinstance(function, dict) else None
        valid = bool(name)
        if isinstance(arguments, str):
            try: json.loads(arguments)
            except json.JSONDecodeError: valid = False
        result.append((str(name or ""), arguments, valid))
    return result


def inspect_steps(steps: Iterable[dict], *, limit: int = 3) -> list[DiagnosticCandidate]:
    rows = [step for step in steps if isinstance(step, dict)]; found = []
    authenticated = False; pending: dict[str, str] = {}; last_user = ""; call_history: list[tuple[str, str, str]] = []

    def add(location: str, category: str, confidence: float, rule: str, message: str,
            excerpt: str = "", related: tuple[str, ...] = ()) -> None:
        found.append(DiagnosticCandidate(location, category, confidence, "deterministic_invariant",
                     (DiagnosticEvidence(rule, message, excerpt[:500], related),)))

    for index, step in enumerate(rows):
        location = _location(step, index); role = str(step.get("role", "")).lower()
        content = _text(step.get("content")); calls = _calls(step)
        if role == "user":
            last_user = content
        if role == "assistant" and calls and content.strip():
            add(location, "Invalid Invocation", .96, "INV001",
                "Assistant emitted user-facing content and a tool invocation in the same step.", content)
        for name, arguments, valid in calls:
            if not valid:
                add(location, "Invalid Invocation", .99, "INV002",
                    "Tool invocation has a missing name or malformed JSON arguments.", _text(arguments))
            if AUTH_TOOL.search(name): authenticated = True
            if PRIVATE_TOOL.search(name) and not authenticated:
                add(location, "Instruction/Plan Adherence Failure", .97, "INV003",
                    "Private-data or state-changing tool was called before an authentication tool.", name)
            if CONSEQUENTIAL.search(name + "_") and not CONFIRM.search(last_user):
                add(location, "Instruction/Plan Adherence Failure", .95, "INV004",
                    "A consequential tool was called without explicit confirmation in the latest user step.", name)
            call_id = ""
            for raw in step.get("tool_calls") or []:
                function = raw.get("function", {}) if isinstance(raw, dict) else {}
                if isinstance(function, dict) and str(function.get("name") or "") == name:
                    call_id = str(raw.get("id") or ""); break
            if call_id: pending[call_id] = location
            signature = (name, _text(arguments), location); call_history.append(signature)
            if len(call_history) >= 3 and len({item[:2] for item in call_history[-3:]}) == 1:
                add(location, "System Failure", .91, "INV005",
                    "The same tool call and arguments were repeated three consecutive times.", name,
                    tuple(item[2] for item in call_history[-3:-1]))
        if role == "tool":
            call_id = str(step.get("tool_call_id") or "")
            if call_id and call_id not in pending:
                add(location, "Invalid Invocation", .94, "INV006",
                    "Tool result has no preceding invocation with the same call ID.", call_id)
            pending.pop(call_id, None)
            if ERROR.search(content):
                add(location, "System Failure", .93, "INV007", "Tool result contains an explicit failure signature.", content)
    for call_id, location in pending.items():
        add(location, "System Failure", .88, "INV008", "Tool invocation has no matching result.", call_id)
    return merge_candidates(found, limit=limit)


def inspect_run(run: Run, *, limit: int = 3) -> list[DiagnosticCandidate]:
    steps = []
    for index, event in enumerate(sorted(run.events, key=lambda item: (item.started_at, item.id))):
        role = "tool" if event.kind in {EventKind.TOOL, EventKind.RETRIEVAL} else "assistant"
        step = {"index": event.id, "role": role, "content": event.response}
        if role == "assistant" and event.kind == EventKind.TOOL_PROPOSAL:
            step["tool_calls"] = [{"id": event.id, "function": {"name": event.name, "arguments": event.request}}]
        if role == "tool":
            step["tool_call_id"] = event.parent_id or ""
        steps.append(step)
        if event.status == "error" or event.error:
            steps.append({"index": event.id, "role": "tool", "content": event.error or "error"})
    return inspect_steps(steps, limit=limit)


def inspect_semantic_spans(spans: Iterable[dict], *, limit: int = 3) -> list[DiagnosticCandidate]:
    """Apply only span-safe explicit failure/loop invariants to TELBench semantic spans."""
    rows = list(spans); found = []; previous = None; repeats = 0
    for index, span in enumerate(rows):
        location = str(span.get("id") or span.get("span_id") or index + 1)
        text = _text(span.get("raw") or span.get("span_text")); normalized = " ".join(text.lower().split())
        if ERROR.search(text):
            found.append(DiagnosticCandidate(location, None, .78, "deterministic_invariant",
                (DiagnosticEvidence("INV009", "Semantic span contains an explicit failure signature.", text[:500]),)))
        repeats = repeats + 1 if normalized and normalized == previous else 1
        if repeats >= 3:
            found.append(DiagnosticCandidate(location, None, .82, "deterministic_invariant",
                (DiagnosticEvidence("INV010", "Three consecutive semantic spans repeat the same content.", text[:500]),)))
        previous = normalized
    return merge_candidates(found, limit=limit)
