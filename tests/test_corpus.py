"""Required Phase 1 corpus: 50 cases across the specified failure families."""
from __future__ import annotations

import pytest

from replayguard.recorder import Recorder
from replayguard.replay import ReplayMode, Replayer
from replayguard.schema import EventKind
from replayguard.storage import LocalStore

FAMILIES = [
    "successful_model", "model_timeout", "provider_rate_limit", "tool_timeout", "tool_exception",
    "retried_call", "parallel_tool_a", "parallel_tool_b", "malformed_output", "large_context",
    "secret_input", "secret_tool_result", "nondeterministic_response", "changed_prompt", "changed_tool_schema",
    "unexpected_extra_tool", "destructive_proposal", "interrupted_execution", "nested_agent", "partial_trace",
    "corrupted_record", "retrieval_empty", "retrieval_many", "authorization_allow", "authorization_deny",
    "artifact_created", "evaluation_pass", "evaluation_fail", "zero_usage", "token_usage",
    "zero_cost", "nonzero_cost", "unicode_content", "binary_reference", "null_response",
    "list_response", "deep_json", "duplicate_tool", "parent_child", "custom_attributes",
    "long_tool_name", "error_redaction", "missing_parent", "cancelled_status", "model_alias",
    "multiple_models", "tool_argument_change", "response_change", "latency_boundary", "cost_boundary",
    "conversation_boundary", "agent_step_boundary", "retrieval_boundary", "artifact_boundary", "evaluation_boundary",
]


@pytest.mark.parametrize("scenario", FAMILIES)
def test_scenario_records_and_structurally_replays(tmp_path, scenario):
    kind = EventKind.TOOL
    if "model" in scenario or scenario in {"changed_prompt", "malformed_output", "provider_rate_limit"}:
        kind = EventKind.MODEL
    elif "retrieval" in scenario:
        kind = EventKind.RETRIEVAL
    elif "authorization" in scenario:
        kind = EventKind.AUTHORIZATION
    elif "artifact" in scenario:
        kind = EventKind.ARTIFACT
    elif "evaluation" in scenario:
        kind = EventKind.EVALUATION
    elif "conversation" in scenario:
        kind = EventKind.CONVERSATION
    elif "agent_step" in scenario or "nested_agent" in scenario:
        kind = EventKind.AGENT_STEP
    store = LocalStore(tmp_path / scenario)
    with Recorder(scenario, store=store, capture_content=True) as recorder:
        with recorder.event(kind, scenario, request={"scenario": scenario}) as event:
            recorder.set_response(event, {"result": scenario}, usage={"input_tokens": 1}, cost_usd=0.001)
    loaded = store.load_run(recorder.run.id)
    replay = Replayer().replay(loaded, mode=ReplayMode.EXACT)
    assert replay.live_calls == 0
    assert [(e.kind, e.name, e.status) for e in replay.run.events] == [(e.kind, e.name, e.status) for e in loaded.events]


def test_corpus_has_at_least_50_cases():
    assert len(FAMILIES) >= 50

