from replayguard.diagnostic_candidates import DiagnosticCandidate, DiagnosticEvidence
from replayguard.meta_ranking import FEATURE_NAMES, candidate_feature_rows, rank_feature_rows


def test_feature_rows_are_signal_based_and_do_not_accept_labels():
    evidence = (DiagnosticEvidence("X", "reason", related_locations=("a",)),)
    rows = candidate_feature_rows([("a", "search"), ("b", "The final answer is wrong")],
        baseline=[DiagnosticCandidate("a", None, .5, "base")], invariants=[],
        claims=[DiagnosticCandidate("b", None, .8, "claim", evidence)])
    assert [row["location"] for row in rows] == ["a", "b"]
    assert all(len(row["features"]) == len(FEATURE_NAMES) for row in rows)
    assert all("label" not in row for row in rows)


def test_ranker_applies_strict_budget_and_stable_tie_break():
    rows = [{"location": "b", "features": ()}, {"location": "a", "features": ()}]
    assert rank_feature_rows(rows, [.5, .5], limit=1) == ["a"]
