from replayguard.hypothesis_verification import verify_hypotheses


def test_explicit_error_generates_entail_hypothesis_at_symptom_and_source():
    candidates, hypotheses, verified = verify_hypotheses([
        ("s1", "The assistant selected account 42."),
        ("s2", "ERROR account 42 was not found.")])
    assert {item.location for item in candidates} == {"s1", "s2"}
    assert any(item.verdict == "entail" for item in verified)
    assert all(item.evidence[0].rule_id == "HYP001" for item in candidates)


def test_evidence_like_step_can_contradict_weak_source_hypothesis():
    _, hypotheses, verified = verify_hypotheses([
        ("s1", "The official result states project date 2020."),
        ("s2", "The final answer is project date 2030.")])
    assert hypotheses and any(item.verdict in {"neutral", "contradict"} for item in verified)


def test_empty_trace_abstains():
    assert verify_hypotheses([]) == ([], [], [])
