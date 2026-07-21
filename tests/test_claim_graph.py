from replayguard.claim_graph import build_claim_graph, diagnose_claim_graph


def test_supported_claim_builds_evidence_edge_and_is_not_flagged():
    steps = [("s1", "The official record states the launch date is 2025-01-04."),
             ("s2", "Therefore the answer is the launch date 2025-01-04.")]
    candidates, graph = diagnose_claim_graph(steps, support_threshold=.1)
    assert graph.claims and graph.support
    assert not candidates


def test_unsupported_final_claim_is_localized_with_evidence():
    candidates, _ = diagnose_claim_graph([("s1", "Search for launch information."),
                                           ("s2", "The final answer is that launch happened in 2039.")])
    assert candidates[0].location == "s2" and candidates[0].evidence[0].rule_id == "CLAIM001"


def test_unsupported_claim_propagates_to_later_reuse():
    candidates, graph = diagnose_claim_graph([
        ("s1", "We found that Project Zephyr launched in 2039."),
        ("s2", "Therefore Project Zephyr in 2039 satisfies the requested constraint."),
        ("s3", "The final answer is Project Zephyr, launched in 2039.")], max_candidates=3)
    assert graph.reuse
    assert {item.location for item in candidates} >= {"s1", "s3"}
