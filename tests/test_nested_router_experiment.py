from tools.experiment_nested_router import fold, paired_bootstrap
from collections import Counter
from replayguard.claim_graph import similarity


def test_nested_fold_is_stable_and_bounded():
    assert fold("trace-1", 0, "outer") == fold("trace-1", 0, "outer")
    assert 0 <= fold("trace-1", 4, "inner-2") < 5


def test_repeat_or_level_changes_partition_inputs():
    values = {fold("trace-1", repeat, level) for repeat in range(5) for level in ("outer", "inner-0")}
    assert len(values) > 1


def test_paired_bootstrap_detects_strictly_better_predictions():
    cases = [{"dataset": "trail", "id": str(i), "expected": {"gold"}} for i in range(10)]
    fallback = {("trail", str(i)): {"wrong"} for i in range(10)}
    challenger = {("trail", str(i)): {"gold"} for i in range(10)}
    result = paired_bootstrap(cases, fallback, challenger, samples=100, seed=1)
    assert result["ci95_low"] == 1.0
    assert result["probability_delta_gt_zero"] == 1.0


def test_claim_similarity_has_stable_sorted_summation():
    left = frozenset({"gamma", "alpha", "beta"}); right = frozenset({"beta", "gamma", "alpha"})
    assert similarity(left, right, Counter({"alpha": 1, "beta": 2, "gamma": 3})) == similarity(right, left, Counter({"alpha": 1, "beta": 2, "gamma": 3}))
