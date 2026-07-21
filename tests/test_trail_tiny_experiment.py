import importlib.util
from pathlib import Path

from replayguard.schema import Event, EventKind


def module():
    path = Path(__file__).parents[1] / "tools/experiment_trail_tiny.py"
    spec = importlib.util.spec_from_file_location("trail_tiny", path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def test_fold_assignment_is_stable_and_trace_grouped():
    item = module()
    assert item.assign_fold("trace-a", 5) == item.assign_fold("trace-a", 5)
    assert 0 <= item.assign_fold("trace-b", 5) < 5


def test_feature_builder_excludes_attributes_and_raw_annotation_leakage():
    item = module()
    event = Event(EventKind.MODEL, "judge", id="span", request="safe request", response="safe response",
                  attributes={"trail.annotations": [{"category": "SECRET_LABEL"}],
                              "_replayguard_otel": {"raw_span": {"annotations": "SECRET_LABEL"}}})
    text = item.event_features(event, 0, 1)
    assert "safe request" in text and "safe response" in text
    assert "SECRET_LABEL" not in text and "trail.annotations" not in text


def test_metric_matches_official_macro_joint_definition():
    item = module(); rows = [
        {"expected": {("a", "Formatting Errors"), ("b", "Goal Deviation")},
         "predicted": {("a", "Formatting Errors"), ("x", "Goal Deviation")}},
        {"expected": {("c", "Tool-related")}, "predicted": {("c", "Tool-related")}},
    ]
    result = item.metrics(rows)
    assert result["official_macro_joint_accuracy"] == .75
    assert result["pair_precision"] == result["micro_pair_recall"] == 2 / 3
