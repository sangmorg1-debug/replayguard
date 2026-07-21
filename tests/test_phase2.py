from __future__ import annotations

from copy import deepcopy

from replayguard.evaluation import EvaluatorRegistry
from replayguard.flakiness import analyze_flakiness
from replayguard.schema import Event, EventKind, Run
from replayguard.suites import RegressionSuite, SuiteRunner


def run_with_response(value, *, cost=0.01, latency=10, tool="search"):
    run = Run("case", status="ok")
    run.events.append(Event(EventKind.TOOL, tool, status="ok", response=value,
                            response_hash=str(value), cost_usd=cost, latency_ms=latency))
    return run


def test_all_evaluation_methods_are_provenanced():
    run = run_with_response({"answer": "Seattle weather is mild"})
    registry = EvaluatorRegistry()
    specs = [
        {"method": "exact", "expected": {"answer": "Seattle weather is mild"}},
        {"method": "schema", "expected": {"type": "object", "required": ["answer"]}},
        {"method": "reference", "expected": "Seattle weather is mild", "threshold": 0.7},
        {"method": "embedding_similarity", "expected": "mild Seattle weather", "threshold": 0.7},
        {"method": "human_review", "decision": True, "reviewer": "qa@example.invalid"},
        {"method": "pairwise", "score": 1, "judge": "reviewer-1"},
        {"method": "model_grader", "votes": [True, True, False], "grader_model": "fixture-model", "prompt_version": "v1"},
    ]
    results = [registry.evaluate(run, spec) for spec in specs]
    assert all(result.passed for result in results)
    assert all(result.evaluator_version for result in results)
    assert all(result.deterministic for result in results[:4])
    assert all(not result.deterministic for result in results[4:])
    assert results[-1].metadata["grader_model"] == "fixture-model"


def test_deterministic_failure_cannot_be_hidden_by_model_grader():
    run = run_with_response("wrong")
    suite = RegressionSuite("gate")
    case = suite.add_run(run)
    case.evaluations = [
        {"method": "exact", "expected": "right"},
        {"method": "model_grader", "votes": [True, True], "grader_model": "fixture", "prompt_version": "1"},
    ]
    result = SuiteRunner().run(suite, {case.id: run})
    assert result.passed == 0
    assert result.deterministic_failures == 1


def test_missing_candidate_does_not_silently_pass_configured_evaluations():
    """A case with configured evaluations but no supplied candidate must not silently compare
    the baseline against itself and report a pass - that hides real regressions whenever a
    caller (e.g. the default GitHub Action) forgets to wire up a candidate map."""
    run = run_with_response("original answer")
    suite = RegressionSuite("gate")
    case = suite.add_run(run)
    case.evaluations = [{"method": "exact", "expected": "original answer"}]
    result = SuiteRunner().run(suite)  # no candidates supplied
    assert result.passed == 0
    exact = next(item for item in result.results[0].evaluations if item.method == "exact")
    assert exact.passed is None
    assert "no candidate" in exact.message.lower()


def test_supplying_the_unchanged_run_as_its_own_candidate_still_passes():
    """The fail-closed behavior above must not block the legitimate case where a caller
    explicitly re-confirms an unmodified candidate matches its baseline."""
    run = run_with_response("original answer")
    suite = RegressionSuite("gate")
    case = suite.add_run(run)
    case.evaluations = [{"method": "exact", "expected": "original answer"}]
    result = SuiteRunner().run(suite, {case.id: run})
    assert result.passed == 1


def test_missing_candidate_leaves_baseline_only_budget_checks_unaffected():
    """Suites with only suite-level budget/security limits and no case.evaluations legitimately
    have nothing to compare a candidate against, so they must keep working without one."""
    run = run_with_response("ok", cost=0.01, latency=10)
    suite = RegressionSuite("budgets", baseline={"max_cost_usd": 1})
    suite.add_run(run)
    result = SuiteRunner().run(suite)
    assert result.passed == 1


def test_baseline_cost_latency_steps_and_security_constraints():
    run = run_with_response("ok", cost=2, latency=500, tool="delete_all")
    suite = RegressionSuite("budgets", baseline={
        "max_cost_usd": 1, "max_latency_ms": 100, "max_steps": 3, "prohibited_tools": ["delete_all"]})
    suite.add_run(run)
    result = SuiteRunner().run(suite)
    failures = [e.method for e in result.results[0].evaluations if not e.passed]
    assert failures == ["max_cost_usd", "max_latency_ms", "security_invariant"]


def test_suite_round_trip_redacts_sensitive_values(tmp_path):
    run = run_with_response({"authorization": "Bearer abcdefghijklmnop"})
    suite = RegressionSuite("persisted")
    suite.add_run(run)
    path = tmp_path / "suite.json"
    suite.save(path)
    assert "abcdefghijklmnop" not in path.read_text()
    loaded = RegressionSuite.load(path)
    assert loaded.name == "persisted" and len(loaded.cases) == 1


def test_flakiness_reports_variance_and_wilson_interval():
    runs = [run_with_response("a", cost=0.01, latency=10), run_with_response("b", cost=0.03, latency=30)]
    runs.append(run_with_response("a", cost=0.02, latency=20))
    runs[-1].status = "error"
    report = analyze_flakiness(runs)
    assert report.pass_rate == 2 / 3
    assert report.response_variants == 2
    assert report.cost_stdev > 0 and report.latency_stdev_ms > 0
    assert 0 <= report.confidence_interval_95[0] < report.confidence_interval_95[1] <= 1


def test_100_case_seeded_structural_regression_detection_rate():
    suite = RegressionSuite("benchmark")
    candidates = {}
    seeded = 0
    for index in range(100):
        baseline = run_with_response(f"response-{index}", tool=f"tool-{index % 7}")
        case = suite.add_run(baseline, name=f"case-{index}")
        if index < 95:
            candidate = deepcopy(baseline)
            candidate.events.append(Event(EventKind.TOOL, "unexpected.side_effect", status="ok"))
            candidates[case.id] = candidate
            seeded += 1
    result = SuiteRunner().run(suite, candidates)
    detected = sum(not item.comparison["equal"] for item in result.results[:95])
    false_alarms = sum(not item.comparison["equal"] for item in result.results[95:])
    assert detected / seeded >= 0.90
    assert false_alarms / 5 < 0.05

