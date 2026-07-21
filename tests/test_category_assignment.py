from replayguard.category_assignment import assign_categories, category_training_rows
from replayguard.diagnosis import normalize_category


class StubModel:
    def predict(self, texts):
        return ["failure" if "error" in text else "planning" for text in texts]


def test_training_rows_use_only_gold_locations():
    cases = [{"steps": [("1", "ok"), ("2", "explicit error")], "gold_pairs": {("2", "failure")}}]
    assert category_training_rows(cases) == (["explicit error"], ["failure"])


def test_assign_categories_skips_unknown_locations():
    assert assign_categories(StubModel(), [("1", "explicit error")], ["missing", "1"]) == {("1", "failure")}


def test_normalizes_public_trail_category_typos():
    assert normalize_category("Task Orchestration Errors") == "Task Orchestration"
    assert normalize_category("Instruction non complience") == "Instruction Non-compliance"
