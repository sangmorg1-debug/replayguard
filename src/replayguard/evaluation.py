from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .schema import Run

EvaluatorFn = Callable[[Run, dict[str, Any]], tuple[bool | None, float | None, str]]


@dataclass
class EvaluationResult:
    method: str
    passed: bool | None
    score: float | None
    message: str
    deterministic: bool
    evaluator_version: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def final_response(run: Run) -> Any:
    values = [event.response for event in run.events if event.response is not None]
    return values[-1] if values else None


class EvaluatorRegistry:
    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._custom: dict[str, tuple[EvaluatorFn, bool, str]] = {}

    def register(self, name: str, callback: EvaluatorFn, *, deterministic: bool, version: str) -> None:
        self._custom[name] = (callback, deterministic, version)

    def evaluate(self, run: Run, spec: dict[str, Any]) -> EvaluationResult:
        method = spec["method"]
        expected = spec.get("expected")
        if method == "exact":
            actual = final_response(run)
            passed = actual == expected
            return self._result(method, passed, float(passed), f"expected {expected!r}; got {actual!r}", True)
        if method == "schema":
            errors = sorted(Draft202012Validator(expected).iter_errors(final_response(run)), key=lambda e: list(e.path))
            return self._result(method, not errors, float(not errors), errors[0].message if errors else "valid", True)
        if method in {"reference", "embedding_similarity"}:
            score = _cosine_text(str(final_response(run) or ""), str(expected or ""))
            threshold = float(spec.get("threshold", 0.8))
            return self._result(method, score >= threshold, score, f"similarity={score:.4f}, threshold={threshold:.4f}", True,
                                {"implementation": "token-frequency cosine; no external model"})
        if method == "human_review":
            decision = spec.get("decision")
            return self._result(method, decision if isinstance(decision, bool) else None, None,
                                spec.get("note", "awaiting human review"), False,
                                {"reviewer": spec.get("reviewer")})
        if method == "pairwise":
            score = float(spec.get("score", 0))
            return self._result(method, score > 0, score, "positive favors candidate; negative favors baseline", False,
                                {"judge": spec.get("judge", "unspecified")})
        if method == "model_grader":
            votes = [bool(item) for item in spec.get("votes", [])]
            score = sum(votes) / len(votes) if votes else None
            passed = score >= float(spec.get("threshold", 0.5)) if score is not None else None
            return self._result(method, passed, score, "probabilistic model grader", False, {
                "grader_model": spec.get("grader_model"), "prompt_version": spec.get("prompt_version"),
                "votes": votes, "limitations": spec.get("limitations", "model judgments may be unstable")})
        if method in self._custom:
            callback, deterministic, version = self._custom[method]
            passed, score, message = callback(run, spec)
            return EvaluationResult(method, passed, score, message, deterministic, version, spec.get("metadata", {}))
        raise ValueError(f"unknown evaluation method: {method}")

    def _result(self, method: str, passed: bool | None, score: float | None, message: str,
                deterministic: bool, metadata: dict[str, Any] | None = None) -> EvaluationResult:
        return EvaluationResult(method, passed, score, message, deterministic, self.VERSION, metadata or {})


def _cosine_text(left: str, right: str) -> float:
    tokenize = lambda value: Counter(re.findall(r"[a-z0-9]+", value.lower()))
    a, b = tokenize(left), tokenize(right)
    if not a or not b:
        return float(a == b)
    dot = sum(count * b[token] for token, count in a.items())
    return dot / math.sqrt(sum(v * v for v in a.values()) * sum(v * v for v in b.values()))

