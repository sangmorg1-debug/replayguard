import json

import pytest

from replayguard.diagnostic_corpora import load_agentrx, load_telbench, localization_metrics


def test_telbench_reader_separates_model_input_from_gold(tmp_path):
    path = tmp_path / "tel.jsonl"
    path.write_text(json.dumps({"id": "1", "question": "q", "spans": [{"id": "s1", "raw": "text"}],
                                "gold": {"error_span_ids": ["s1"]}, "annotations": {"secret": True}}) + "\n")
    row = next(load_telbench(path))
    assert row["input"] == {"question": "q", "spans": [{"id": "s1", "raw": "text"}]}
    assert row["gold"] == {"s1"}
    assert "gold" not in row["input"] and "annotations" not in row["input"]


def test_agentrx_reader_preserves_upstream_step_numbers(tmp_path):
    root = tmp_path; (root / "data/tau_retail").mkdir(parents=True); (root / "data/ground_truth").mkdir()
    (root / "data/magentic_dataset").mkdir()
    (root / "data/tau_retail/tau_dataset_failed.json").write_text(json.dumps([{"task_id": 7, "traj": [{"index": 3}]}]))
    truth = [{"trajectory_id": 7, "failures": [{"failure_id": 1, "step_number": 3,
              "failure_category": "Invalid Invocation"}], "root_cause": {"failure_id": 1}}]
    (root / "data/ground_truth/tau_ground_truth.json").write_text(json.dumps(truth))
    (root / "data/ground_truth/magentic_one_ground_truth.json").write_text("[]")
    row = next(load_agentrx(root))
    assert row["gold"][0]["step"] == 3 and row["root_failure_id"] == 1


def test_common_localization_metrics_do_not_reward_false_positives():
    result = localization_metrics([({"a", "b"}, {"a", "x"}), ({"c"}, {"c"})])
    assert result["macro_recall"] == .75
    assert result["precision"] == result["micro_recall"] == pytest.approx(2 / 3)
