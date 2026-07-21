import json
from pathlib import Path

import pytest

from replayguard.cli import main
from replayguard.diagnosis import diagnose, load_ground_truth, score_diagnosis
from replayguard.otel import import_traces
from replayguard.schema import Event, EventKind, Run
from replayguard.storage import LocalStore


def event(span_id, kind=EventKind.MODEL, **values):
    return Event(kind, values.pop("name", "operation"), id=span_id,
                 started_at=values.pop("started_at", f"2026-01-01T00:00:{span_id[-2:]}+00:00"), **values)


@pytest.mark.parametrize(("message", "category"), [
    ("HTTP 429: too many requests", "Rate Limiting"),
    ("401 unauthorized", "Authentication Errors"),
    ("resource 404 not found", "Resource Not Found"),
    ("deadline exceeded", "Timeout Issues"),
    ("503 service unavailable", "Service Errors"),
    ("out of memory", "Resource Exhaustion"),
])
def test_diagnose_localizes_observable_error_signatures(message, category):
    run = Run("failure", events=[event("span01", kind=EventKind.TOOL, status="error", error={"message": message})])
    result = diagnose(run)
    assert [(item.span_id, item.category) for item in result.suspects] == [("span01", category)]


def test_diagnose_active_prompt_rules_and_unsupported_evidence_claim():
    run = Run("failure", events=[event("span01", request={"messages": [
        {"role": "user", "content": "old request must end with <old_marker>"},
        {"role": "user", "content": "After the plan, write <end_plan>"},
    ]}, response={"content": "I have verified the source and here is the plan"})])
    pairs = {(item.span_id, item.category) for item in diagnose(run).suspects}
    assert pairs == {("span01", "Instruction Non-compliance"), ("span01", "Tool-related")}
    assert all("old_marker" not in item.evidence for item in diagnose(run).suspects)


def test_diagnose_plan_without_retrieval_and_repeated_calls():
    events = [event("span01", response="Use search_agent, then submit the answer")]
    events += [event(f"tool0{i}", kind=EventKind.TOOL, name="lookup", started_at=f"2026-01-01T00:00:0{i + 1}+00:00") for i in range(5)]
    events.append(event("final1", kind=EventKind.TOOL, name="final_answer", started_at="2026-01-01T00:00:09+00:00"))
    result = diagnose(Run("failure", events=events))
    assert ("tool04", "Resource Abuse") in {(item.span_id, item.category) for item in result.suspects}


def test_score_reports_official_joint_recall_and_precision_to_prevent_candidate_spam():
    run = Run("trace", id="trace", events=[
        event("good", status="error", error={"message": "429 rate limit"}),
        event("extra", status="error", error={"message": "timeout"}),
    ])
    result = score_diagnosis(diagnose(run), {"errors": [{"location": "good", "category": "Rate Limiting"}]})
    assert result["location_category_joint_accuracy"] == 1
    assert result["pair_precision"] == .5 and result["pair_f1"] == pytest.approx(2 / 3)


def test_default_candidate_limit_is_precision_calibrated_and_override_remains_available():
    events = [event(f"span{i:02}", status="error", error={"message": "503 service unavailable"}) for i in range(6)]
    run = Run("many", events=events)
    assert len(diagnose(run).suspects) == 3
    assert len(diagnose(run, max_candidates=5).suspects) == 5


def test_cli_diagnose_with_ground_truth(tmp_path, capsys):
    store = LocalStore(tmp_path / "store"); store.init()
    run = Run("trace", id="trace", events=[event("span01", status="error", error={"message": "429"})])
    store.save_run(run)
    truth = tmp_path / "truth.json"
    truth.write_text(json.dumps({"errors": [{"location": "span01", "category": "Rate Limiting"}]}), encoding="utf-8")
    assert main(["--store", str(tmp_path / "store"), "diagnose", "trace", "--ground-truth", str(truth)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["benchmark"]["location_category_joint_accuracy"] == 1


def test_trail_category_normalization_and_single_known_trailing_comma_repair(tmp_path):
    annotation = tmp_path / "annotation.json"
    annotation.write_text('{"errors":[{"location":"span01","category":"Context Handling Failure"},],}', encoding="utf-8")
    truth = load_ground_truth(annotation)
    run = Run("trace", id="trace", events=[event("span01", status="error", error={"message": "maximum context length exceeded"})])
    assert score_diagnosis(diagnose(run), truth)["matched_pairs"] == 1


def test_diagnose_default_output_has_no_experimental_claim_graph_key():
    run = Run("failure", events=[event("span01", status="error", error={"message": "429 rate limit"})])
    assert "experimental_claim_graph" not in diagnose(run).to_dict()


def test_diagnose_experimental_claim_graph_flag_adds_labeled_advisory_candidates():
    run = Run("failure", events=[event("span01", response="The final answer is 42, therefore we conclude the task is done.")])
    result = diagnose(run, experimental_claim_graph=True)
    payload = result.to_dict()
    assert "experimental_claim_graph" in payload
    candidates = payload["experimental_claim_graph"]
    assert candidates, "expected at least one claim-graph candidate for an unsupported final commitment"
    assert all("CLAIM001" in item["evidence"] for item in candidates)
    assert all(item["deterministic"] is False for item in candidates)


def test_cli_diagnose_experimental_claim_graph_flag_is_advisory_and_does_not_change_exit_code(tmp_path, capsys):
    store = LocalStore(tmp_path / "store"); store.init()
    run = Run("trace", id="trace", events=[event("span01", response="The final answer is 42, therefore we conclude the task is done.")])
    store.save_run(run)
    assert main(["--store", str(tmp_path / "store"), "diagnose", "trace", "--experimental-claim-graph"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert "experimental_claim_graph" in output
    assert main(["--store", str(tmp_path / "store"), "diagnose", "trace"]) == 0
    default_output = json.loads(capsys.readouterr().out)
    assert "experimental_claim_graph" not in default_output


def test_pinned_public_trail_sample_matches_all_three_human_labels_when_available():
    root = Path(__file__).resolve().parents[1]
    trace = root / ".verify/upstream/trail/0035f455b3ff2295167a844f04d85d34.json"
    if not trace.exists():
        pytest.skip("fetch the pinned public TRAIL sample before running the integration check")
    result = diagnose(import_traces(json.loads(trace.read_text(encoding="utf-8")))[0])
    assert {(item.span_id, item.category) for item in result.suspects} == {
        ("98fa1dda65ab168b", "Instruction Non-compliance"),
        ("bc20feefb97e11e5", "Tool-related"),
        ("bc20feefb97e11e5", "Goal Deviation"),
    }
