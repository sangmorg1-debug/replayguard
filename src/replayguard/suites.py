from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .compare import compare_runs
from .evaluation import EvaluationResult, EvaluatorRegistry
from .redaction import Redactor
from .schema import Run

SUITE_VERSION = "1.0.0"


@dataclass
class RegressionCase:
    name: str
    source_run: dict[str, Any]
    id: str = field(default_factory=lambda: uuid4().hex)
    kind: str = "positive"
    parameters: dict[str, list[Any]] = field(default_factory=dict)
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_run(cls, run: Run, *, name: str | None = None, negative: bool = False,
                 redactor: Redactor | None = None) -> "RegressionCase":
        safe = (redactor or Redactor()).redact(run.to_dict())
        return cls(name or run.name, safe, kind="negative" if negative else "positive")


@dataclass
class RegressionSuite:
    name: str
    version: str = SUITE_VERSION
    cases: list[RegressionCase] = field(default_factory=list)
    baseline: dict[str, Any] = field(default_factory=dict)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "RegressionSuite":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["cases"] = [RegressionCase(**item) for item in data.get("cases", [])]
        return cls(**data)

    def add_run(self, run: Run, **kwargs) -> RegressionCase:
        case = RegressionCase.from_run(run, **kwargs)
        self.cases.append(case)
        return case


@dataclass
class CaseResult:
    case_id: str
    name: str
    passed: bool
    deterministic_passed: bool
    evaluations: list[EvaluationResult]
    comparison: dict[str, Any]


@dataclass
class SuiteResult:
    suite: str
    total: int
    passed: int
    deterministic_failures: int
    results: list[CaseResult]

    def to_dict(self) -> dict[str, Any]:
        return {"suite": self.suite, "total": self.total, "passed": self.passed,
                "deterministic_failures": self.deterministic_failures,
                "results": [{**asdict(item), "evaluations": [e.to_dict() for e in item.evaluations]} for item in self.results]}


class SuiteRunner:
    def __init__(self, evaluators: EvaluatorRegistry | None = None) -> None:
        self.evaluators = evaluators or EvaluatorRegistry()

    def run(self, suite: RegressionSuite, candidates: dict[str, Run] | None = None) -> SuiteResult:
        candidates = candidates or {}
        results: list[CaseResult] = []
        for case in suite.cases:
            baseline = Run.from_dict(case.source_run)
            has_candidate = case.id in candidates
            candidate = candidates.get(case.id, baseline)
            if case.evaluations and not has_candidate:
                # Without a real candidate, "evaluating" would just compare the baseline to
                # itself and trivially pass - silently hiding whatever actually changed.
                evaluations = [EvaluationResult(spec["method"], None, None,
                               "No candidate run was supplied for this case; behavior comparison "
                               "is undetermined, not passing.", True, EvaluatorRegistry.VERSION)
                               for spec in case.evaluations]
            else:
                evaluations = [self.evaluators.evaluate(candidate, spec) for spec in case.evaluations]
            evaluations.extend(self._baseline_evaluations(candidate, suite.baseline))
            deterministic = [item for item in evaluations if item.deterministic]
            deterministic_passed = all(item.passed is True for item in deterministic)
            decided = [item for item in evaluations if item.passed is not None]
            passed = deterministic_passed and all(item.passed is True for item in decided)
            comparison = compare_runs(baseline, candidate).to_dict()
            results.append(CaseResult(case.id, case.name, passed, deterministic_passed, evaluations, comparison))
        return SuiteResult(suite.name, len(results), sum(item.passed for item in results),
                           sum(not item.deterministic_passed for item in results), results)

    def _baseline_evaluations(self, run: Run, baseline: dict[str, Any]) -> list[EvaluationResult]:
        results = []
        total_cost = sum(event.cost_usd or 0 for event in run.events)
        total_latency = sum(event.latency_ms or 0 for event in run.events)
        checks = (("max_cost_usd", total_cost), ("max_latency_ms", total_latency), ("max_steps", len(run.events)))
        for key, actual in checks:
            if key in baseline:
                limit = float(baseline[key])
                results.append(EvaluationResult(key, actual <= limit, float(actual <= limit),
                                                f"actual={actual}, limit={limit}", True, "1.0.0"))
        prohibited = set(baseline.get("prohibited_tools", []))
        if prohibited:
            seen = {event.name for event in run.events if event.kind.value == "tool"}
            bad = sorted(seen & prohibited)
            results.append(EvaluationResult("security_invariant", not bad, float(not bad),
                                            f"prohibited tools called: {bad}", True, "1.0.0"))
        return results
