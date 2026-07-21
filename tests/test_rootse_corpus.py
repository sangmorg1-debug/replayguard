import json

import pytest

from replayguard.diagnostic_corpora import load_rootse


def test_rootse_reader_separates_gold_from_input(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    (data / "case.json").write_text(json.dumps({"instance_id": "x", "original_traj": [
        {"index": "0", "thought": "plan"}, {"index": "1", "observation": "failure"}],
        "failure_id": "1", "failure_reason": "bad plan", "agent": "agent"}), encoding="utf-8")
    row = next(load_rootse(tmp_path))
    assert row["id"] == "case"
    assert row["gold"] == {"1"}
    assert "gold" not in row["input"] and row["input"]["steps"][1]["raw"] == "failure"


def test_rootse_reader_rejects_dangling_failure(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    (data / "case.json").write_text(json.dumps({"instance_id": "x", "original_traj": [{"index": "0"}],
                                                "failure_id": "9"}), encoding="utf-8")
    with pytest.raises(ValueError, match="not a trajectory step"):
        list(load_rootse(tmp_path))
