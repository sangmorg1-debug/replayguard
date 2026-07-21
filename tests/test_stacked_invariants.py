from replayguard.diagnostic_candidates import DiagnosticCandidate, DiagnosticEvidence, conservative_stack, merge_candidates
from replayguard.invariants import inspect_steps


def test_candidate_contract_validates_confidence_and_merges_evidence():
    first = DiagnosticCandidate("3", "Invalid Invocation", .8, "a", (DiagnosticEvidence("A", "one"),))
    second = DiagnosticCandidate("3", "Invalid Invocation", .9, "b", (DiagnosticEvidence("B", "two"),))
    merged = merge_candidates([first], [second], limit=3)[0]
    assert merged.confidence == .9 and merged.signal_type == "a+b" and len(merged.evidence) == 2


def test_malformed_tool_call_is_auditable():
    result = inspect_steps([{"index": 3, "role": "assistant", "tool_calls": [
        {"id": "c1", "function": {"name": "lookup", "arguments": "{broken"}}]}])
    assert result[0].location == "3" and result[0].category == "Invalid Invocation"
    assert result[0].evidence[0].rule_id == "INV002"


def test_conservative_stack_does_not_displace_primary_candidates():
    primary = [DiagnosticCandidate("a", "A", .2, "primary")]
    secondary = [DiagnosticCandidate("b", "B", .99, "secondary")]
    assert [item.location for item in conservative_stack(primary, secondary, limit=2)] == ["a", "b"]


def test_consequential_call_requires_latest_user_confirmation():
    steps = [{"index": 1, "role": "user", "content": "I might return it"},
             {"index": 2, "role": "assistant", "tool_calls": [{"id": "c", "function": {
                 "name": "return_delivered_order_items", "arguments": "{}"}}]},
             {"index": 3, "role": "tool", "tool_call_id": "c", "content": "ok"}]
    rules = {e.rule_id for item in inspect_steps(steps) for e in item.evidence}
    assert "INV004" in rules


def test_repeated_identical_tool_calls_localize_final_repeat():
    call = lambda index: {"index": index, "role": "assistant", "tool_calls": [{"function": {
        "name": "search", "arguments": '{"q":"x"}'}}]}
    result = inspect_steps([call(1), call(2), call(3)], limit=10)
    assert any(item.location == "3" and item.evidence[0].rule_id == "INV005" for item in result)
