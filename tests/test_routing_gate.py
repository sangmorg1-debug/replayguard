from replayguard.routing_gate import select_routing_policy


def metric(f1, precision):
    return {"f1": f1, "precision": precision}


def test_gate_accepts_material_gain_without_precision_loss():
    decision = select_routing_policy(metric(.30, .40), metric(.32, .41))
    assert decision.policy == "meta_ranker"


def test_gate_rejects_small_gain():
    decision = select_routing_policy(metric(.30, .40), metric(.305, .42))
    assert decision.policy == "claim_graph"
    assert "below required" in decision.reason


def test_gate_rejects_precision_regression_despite_f1_gain():
    decision = select_routing_policy(metric(.30, .40), metric(.35, .39))
    assert decision.policy == "claim_graph"
    assert "precision regressed" in decision.reason
