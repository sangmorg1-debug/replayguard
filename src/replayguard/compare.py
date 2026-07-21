from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .schema import Run


@dataclass
class Comparison:
    equal: bool
    changes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"equal": self.equal, "changes": self.changes}


def compare_runs(left: Run, right: Run) -> Comparison:
    changes: list[dict[str, Any]] = []
    left_shape = Counter((event.kind.value, event.name, event.status) for event in left.events)
    right_shape = Counter((event.kind.value, event.name, event.status) for event in right.events)
    if left_shape != right_shape:
        serialize_shape = lambda shape: [
            {"kind": key[0], "name": key[1], "status": key[2], "count": count}
            for key, count in sorted(shape.items())
        ]
        changes.append({"category": "structure", "before": serialize_shape(left_shape), "after": serialize_shape(right_shape)})
    for metric in ("latency_ms", "cost_usd"):
        before = sum(getattr(event, metric) or 0 for event in left.events)
        after = sum(getattr(event, metric) or 0 for event in right.events)
        if before != after:
            changes.append({"category": "efficiency", "metric": metric, "before": before, "after": after})
    left_errors = [event.error for event in left.events if event.error]
    right_errors = [event.error for event in right.events if event.error]
    if left_errors != right_errors:
        changes.append({"category": "errors", "before": left_errors, "after": right_errors})
    left_responses = [event.response_hash for event in left.events]
    right_responses = [event.response_hash for event in right.events]
    if left_responses != right_responses:
        changes.append({"category": "content_identity", "before": left_responses, "after": right_responses})
    for kind, category in (("tool", "tool_behavior"), ("retrieval", "retrieval_behavior"),
                           ("authorization", "security"), ("artifact", "artifacts")):
        before = [(e.name, e.request_hash, e.response_hash, e.attributes) for e in left.events if e.kind.value == kind]
        after = [(e.name, e.request_hash, e.response_hash, e.attributes) for e in right.events if e.kind.value == kind]
        if before != after:
            changes.append({"category": category, "before": before, "after": after})
    before_steps, after_steps = len(left.events), len(right.events)
    if before_steps != after_steps:
        changes.append({"category": "efficiency", "metric": "step_count", "before": before_steps, "after": after_steps})
    return Comparison(not changes, changes)
