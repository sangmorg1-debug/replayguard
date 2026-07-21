from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .schema import EventKind, Run


@dataclass
class AssertionResult:
    passed: bool
    assertion: str
    message: str
    probabilistic: bool = False


@dataclass
class Assertion:
    kind: str
    expected: Any = None
    target: str | None = None
    callback: Callable[[Run], bool] | None = None

    def evaluate(self, run: Run) -> AssertionResult:
        responses = [event.response for event in run.events if event.response is not None]
        text = json.dumps(responses, sort_keys=True, default=repr)
        tools = [event for event in run.events if event.kind == EventKind.TOOL]
        checks = {
            "exact": lambda: responses[-1] == self.expected if responses else False,
            "contains": lambda: str(self.expected) in text,
            "excludes": lambda: str(self.expected) not in text,
            "tool_called": lambda: any(event.name == self.target for event in tools),
            "tool_not_called": lambda: all(event.name != self.target for event in tools),
            "tool_count": lambda: len([event for event in tools if not self.target or event.name == self.target]) == self.expected,
            "max_latency_ms": lambda: sum(event.latency_ms or 0 for event in run.events) <= float(self.expected),
            "max_cost_usd": lambda: sum(event.cost_usd or 0 for event in run.events) <= float(self.expected),
            "no_unhandled_error": lambda: run.status != "error" and not any(event.error for event in run.events),
            "custom": lambda: bool(self.callback and self.callback(run)),
        }
        if self.kind == "model_graded":
            if not self.callback:
                return AssertionResult(False, self.kind, "model grader callback required", True)
            return AssertionResult(bool(self.callback(run)), self.kind, "probabilistic model-graded result", True)
        if self.kind not in checks:
            return AssertionResult(False, self.kind, f"unsupported assertion: {self.kind}")
        passed = bool(checks[self.kind]())
        return AssertionResult(passed, self.kind, "passed" if passed else "failed")

