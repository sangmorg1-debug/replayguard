"""Required Phase 1 corpus: 50+ cases across the specified failure families.

Each family builds a run that actually exhibits the behavior its name claims (a real
raised-and-caught exception for *_timeout/*_exception, real redaction for secret_*, a real
detected corruption for corrupted_record, a real compare_runs diff for changed_*/response_change,
etc.) rather than a single generic event whose only distinguishing feature is its name string.
"""
from __future__ import annotations

import json

import pytest

from replayguard.compare import compare_runs
from replayguard.recorder import Recorder
from replayguard.replay import ReplayMode, Replayer
from replayguard.schema import Event, EventKind, Run
from replayguard.storage import LocalStore

UNSET = object()


def _record(store, name, kind, *, request=None, response=UNSET, raises=None,
            attributes=None, usage=None, cost_usd=None, parent_id=None, capture_content=True):
    with Recorder(name, store=store, capture_content=capture_content) as recorder:
        try:
            with recorder.event(kind, name, request=request, attributes=attributes or {},
                                 parent_id=parent_id) as event:
                if raises is not None:
                    raise raises
                if response is not UNSET:
                    recorder.set_response(event, response, usage=usage or {}, cost_usd=cost_usd)
        except Exception:
            pass
    return store.load_run(recorder.run.id)


def _round_trips(loaded):
    replay = Replayer().replay(loaded, mode=ReplayMode.EXACT)
    assert replay.live_calls == 0
    assert [(e.kind, e.name, e.status) for e in replay.run.events] == \
           [(e.kind, e.name, e.status) for e in loaded.events]
    return replay


def _check_successful_model(store):
    loaded = _record(store, "successful_model", EventKind.MODEL, request={"prompt": "hi"}, response={"text": "hello"})
    _round_trips(loaded)
    assert loaded.events[0].status == "ok" and loaded.events[0].response == {"text": "hello"}


def _check_model_timeout(store):
    loaded = _record(store, "model_timeout", EventKind.MODEL, request={"prompt": "hi"}, raises=TimeoutError("model call timed out"))
    _round_trips(loaded)
    assert loaded.events[0].status == "error" and loaded.events[0].error["type"] == "TimeoutError"


def _check_provider_rate_limit(store):
    loaded = _record(store, "provider_rate_limit", EventKind.MODEL, request={"prompt": "hi"},
                      raises=RuntimeError("429 rate limited by provider"))
    _round_trips(loaded)
    assert loaded.events[0].status == "error" and "rate limited" in loaded.events[0].error["message"]


def _check_tool_timeout(store):
    loaded = _record(store, "tool_timeout", EventKind.TOOL, request={"url": "https://example.com"}, raises=TimeoutError())
    _round_trips(loaded)
    assert loaded.events[0].status == "error" and loaded.events[0].error["type"] == "TimeoutError"


def _check_tool_exception(store):
    loaded = _record(store, "tool_exception", EventKind.TOOL, request={"path": "/x"}, raises=RuntimeError("boom"))
    _round_trips(loaded)
    assert loaded.events[0].status == "error" and loaded.events[0].error["type"] == "RuntimeError"


def _check_retried_call(store):
    with Recorder("retried_call", store=store, capture_content=True) as recorder:
        try:
            with recorder.event(EventKind.TOOL, "retried_call", request={"attempt": 1}, attributes={"attempt": 1}):
                raise ConnectionError("transient")
        except ConnectionError:
            pass
        with recorder.event(EventKind.TOOL, "retried_call", request={"attempt": 2}, attributes={"attempt": 2}) as event:
            recorder.set_response(event, {"ok": True})
    loaded = store.load_run(recorder.run.id)
    _round_trips(loaded)
    assert [e.status for e in loaded.events] == ["error", "ok"]
    assert [e.attributes["attempt"] for e in loaded.events] == [1, 2]


def _parallel_tools(store, lane_scenario):
    with Recorder(lane_scenario, store=store, capture_content=True) as recorder:
        with recorder.event(EventKind.AGENT_STEP, "fan-out") as step:
            pass
        with recorder.event(EventKind.TOOL, "search", request={"lane": "a"}, parent_id=step.id) as event_a:
            recorder.set_response(event_a, {"lane": "a", "done": True})
        with recorder.event(EventKind.TOOL, "search", request={"lane": "b"}, parent_id=step.id) as event_b:
            recorder.set_response(event_b, {"lane": "b", "done": True})
    loaded = store.load_run(recorder.run.id)
    _round_trips(loaded)
    tools = [e for e in loaded.events if e.kind == EventKind.TOOL]
    assert len(tools) == 2 and tools[0].parent_id == tools[1].parent_id == step.id
    assert tools[0].id != tools[1].id


def _check_parallel_tool_a(store): _parallel_tools(store, "parallel_tool_a")
def _check_parallel_tool_b(store): _parallel_tools(store, "parallel_tool_b")


def _check_malformed_output(store):
    loaded = _record(store, "malformed_output", EventKind.MODEL, request={"prompt": "return json"},
                      response={"raw": "{not: valid, json"})
    _round_trips(loaded)
    with pytest.raises(json.JSONDecodeError):
        json.loads(loaded.events[0].response["raw"])


def _check_large_context(store):
    big = "x" * 200_000
    loaded = _record(store, "large_context", EventKind.TOOL, request={"context": big}, response={"ok": True})
    replay = _round_trips(loaded)
    assert len(loaded.events[0].request["context"]) == 200_000
    assert len(replay.run.events[0].request["context"]) == 200_000


def _check_secret_input(store):
    loaded = _record(store, "secret_input", EventKind.TOOL, request={"authorization": "sk-abcdefghijklmnopqrstuvwxyz"},
                      response={"ok": True})
    _round_trips(loaded)
    assert "sk-" not in repr(loaded.events[0].request)


def _check_secret_tool_result(store):
    loaded = _record(store, "secret_tool_result", EventKind.TOOL, request={"op": "fetch"},
                      response={"token": "sk-abcdefghijklmnopqrstuvwxyz"})
    _round_trips(loaded)
    assert "sk-" not in repr(loaded.events[0].response)


def _check_nondeterministic_response(store):
    run_a = _record(LocalStore(store.root / "a"), "nondeterministic_response", EventKind.MODEL,
                     request={"prompt": "roll"}, response={"text": "4"})
    run_b = _record(LocalStore(store.root / "b"), "nondeterministic_response", EventKind.MODEL,
                     request={"prompt": "roll"}, response={"text": "7"})
    comparison = compare_runs(run_a, run_b)
    assert not comparison.equal
    assert any(change["category"] == "content_identity" for change in comparison.changes)


def _check_changed_prompt(store):
    run_a = _record(LocalStore(store.root / "a"), "changed_prompt", EventKind.MODEL, request={"prompt": "v1"}, response={"text": "ok"})
    run_b = _record(LocalStore(store.root / "b"), "changed_prompt", EventKind.MODEL, request={"prompt": "v2"}, response={"text": "ok"})
    comparison = compare_runs(run_a, run_b)
    assert not comparison.equal


def _check_changed_tool_schema(store):
    run_a = _record(LocalStore(store.root / "a"), "changed_tool_schema", EventKind.TOOL, request={"city": "Paris"}, response={"ok": True})
    run_b = _record(LocalStore(store.root / "b"), "changed_tool_schema", EventKind.TOOL, request={"location": "Paris"}, response={"ok": True})
    comparison = compare_runs(run_a, run_b)
    assert not comparison.equal and any(change["category"] == "tool_behavior" for change in comparison.changes)


def _check_unexpected_extra_tool(store):
    baseline = LocalStore(store.root / "a")
    with Recorder("unexpected_extra_tool", store=baseline, capture_content=True) as recorder:
        with recorder.event(EventKind.TOOL, "search", request={"q": "x"}) as event:
            recorder.set_response(event, {"ok": True})
    run_a = baseline.load_run(recorder.run.id)
    candidate = LocalStore(store.root / "b")
    with Recorder("unexpected_extra_tool", store=candidate, capture_content=True) as recorder:
        with recorder.event(EventKind.TOOL, "search", request={"q": "x"}) as event:
            recorder.set_response(event, {"ok": True})
        with recorder.event(EventKind.TOOL, "delete", request={"id": 1}) as event:
            recorder.set_response(event, {"ok": True})
    run_b = candidate.load_run(recorder.run.id)
    comparison = compare_runs(run_a, run_b)
    assert not comparison.equal and any(change["category"] == "structure" for change in comparison.changes)


def _check_destructive_proposal(store):
    loaded = _record(store, "destructive_proposal", EventKind.TOOL_PROPOSAL, request={"action": "delete_database"},
                      attributes={"destructiveHint": True})
    _round_trips(loaded)
    assert loaded.events[0].kind == EventKind.TOOL_PROPOSAL and loaded.events[0].attributes["destructiveHint"] is True


def _check_interrupted_execution(store):
    run = Run("interrupted_execution", status="running")
    run.events.append(Event(EventKind.TOOL, "long_operation", status="running", ended_at=None))
    store.save_run(run)
    loaded = store.load_run(run.id)
    assert loaded.events[0].ended_at is None and loaded.events[0].status == "running"


def _check_nested_agent(store):
    with Recorder("nested_agent", store=store, capture_content=True) as recorder:
        with recorder.event(EventKind.AGENT_STEP, "outer") as outer:
            with recorder.event(EventKind.AGENT_STEP, "inner", parent_id=outer.id) as inner:
                with recorder.event(EventKind.TOOL, "leaf", parent_id=inner.id) as leaf:
                    recorder.set_response(leaf, {"ok": True})
    loaded = store.load_run(recorder.run.id)
    _round_trips(loaded)
    by_name = {e.name: e for e in loaded.events}
    assert by_name["inner"].parent_id == by_name["outer"].id
    assert by_name["leaf"].parent_id == by_name["inner"].id


def _check_partial_trace(store):
    run = Run("partial_trace", status="running")
    run.events.append(Event(EventKind.AGENT_STEP, "plan", status="ok"))
    store.save_run(run)
    loaded = store.load_run(run.id)
    assert loaded.status == "running" and loaded.ended_at is None and len(loaded.events) == 1


def _check_corrupted_record(store):
    run = Run("corrupted_record", status="ok")
    run.events.append(Event(EventKind.TOOL, "op", status="ok", response="content"))
    digest = store.save_run(run)
    blob_path = store.blobs / digest[:2] / f"{digest}.json"
    blob_path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        store.load_run(run.id)


def _check_retrieval_empty(store):
    loaded = _record(store, "retrieval_empty", EventKind.RETRIEVAL, request={"query": "x"}, response={"documents": []})
    _round_trips(loaded)
    assert loaded.events[0].response["documents"] == []


def _check_retrieval_many(store):
    documents = [{"id": index} for index in range(250)]
    loaded = _record(store, "retrieval_many", EventKind.RETRIEVAL, request={"query": "x"}, response={"documents": documents})
    _round_trips(loaded)
    assert len(loaded.events[0].response["documents"]) == 250


def _check_authorization_allow(store):
    loaded = _record(store, "authorization_allow", EventKind.AUTHORIZATION, request={"tool": "read"},
                      response={"decision": "allow"}, attributes={"decision": "allow"})
    _round_trips(loaded)
    assert loaded.events[0].status == "ok" and loaded.events[0].attributes["decision"] == "allow"


def _check_authorization_deny(store):
    loaded = _record(store, "authorization_deny", EventKind.AUTHORIZATION, request={"tool": "shell"},
                      raises=PermissionError("denied by policy"), attributes={"decision": "deny"})
    _round_trips(loaded)
    assert loaded.events[0].status == "error" and loaded.events[0].attributes["decision"] == "deny"


def _check_artifact_created(store):
    loaded = _record(store, "artifact_created", EventKind.ARTIFACT, request={"kind": "csv"}, response={"path": "output.csv"})
    _round_trips(loaded)
    assert loaded.events[0].response["path"] == "output.csv"


def _check_evaluation_pass(store):
    loaded = _record(store, "evaluation_pass", EventKind.EVALUATION, request={"case": "1"}, response={"passed": True},
                      attributes={"passed": True})
    _round_trips(loaded)
    assert loaded.events[0].status == "ok" and loaded.events[0].attributes["passed"] is True


def _check_evaluation_fail(store):
    loaded = _record(store, "evaluation_fail", EventKind.EVALUATION, request={"case": "1"},
                      raises=AssertionError("expected output did not match"), attributes={"passed": False})
    _round_trips(loaded)
    assert loaded.events[0].status == "error" and loaded.events[0].attributes["passed"] is False


def _check_zero_usage(store):
    loaded = _record(store, "zero_usage", EventKind.TOOL, request={}, response={"ok": True}, usage={})
    _round_trips(loaded)
    assert loaded.events[0].usage == {}


def _check_token_usage(store):
    loaded = _record(store, "token_usage", EventKind.MODEL, request={"prompt": "x"}, response={"text": "y"},
                      usage={"input_tokens": 120, "output_tokens": 45})
    _round_trips(loaded)
    assert loaded.events[0].usage == {"input_tokens": 120, "output_tokens": 45}


def _check_zero_cost(store):
    loaded = _record(store, "zero_cost", EventKind.TOOL, request={}, response={"ok": True}, cost_usd=0.0)
    _round_trips(loaded)
    assert loaded.events[0].cost_usd == 0.0


def _check_nonzero_cost(store):
    loaded = _record(store, "nonzero_cost", EventKind.MODEL, request={"prompt": "x"}, response={"text": "y"}, cost_usd=0.0234)
    _round_trips(loaded)
    assert loaded.events[0].cost_usd == 0.0234


def _check_unicode_content(store):
    text = "日本語 \U0001F600 café"
    loaded = _record(store, "unicode_content", EventKind.TOOL, request={"text": text}, response={"echo": text})
    replay = _round_trips(loaded)
    assert loaded.events[0].response["echo"] == text
    assert replay.run.events[0].response["echo"] == text


def _check_binary_reference(store):
    loaded = _record(store, "binary_reference", EventKind.ARTIFACT, request={"kind": "image"},
                      response={"blob_ref": "sha256:" + "ab" * 32, "encoding": "base64"})
    _round_trips(loaded)
    assert loaded.events[0].response["blob_ref"].startswith("sha256:")


def _check_null_response(store):
    loaded = _record(store, "null_response", EventKind.TOOL, request={"op": "noop"}, response=None)
    _round_trips(loaded)
    assert loaded.events[0].response is None and loaded.events[0].response_hash is not None


def _check_list_response(store):
    loaded = _record(store, "list_response", EventKind.TOOL, request={}, response=[1, 2, 3, {"nested": True}])
    _round_trips(loaded)
    assert loaded.events[0].response == [1, 2, 3, {"nested": True}]


def _check_deep_json(store):
    nested = {"a": {"b": {"c": {"d": {"e": {"f": "leaf"}}}}}}
    loaded = _record(store, "deep_json", EventKind.TOOL, request=nested, response={"ok": True})
    _round_trips(loaded)
    assert loaded.events[0].request["a"]["b"]["c"]["d"]["e"]["f"] == "leaf"


def _check_duplicate_tool(store):
    with Recorder("duplicate_tool", store=store, capture_content=True) as recorder:
        for _ in range(2):
            with recorder.event(EventKind.TOOL, "search", request={"q": "x"}) as event:
                recorder.set_response(event, {"ok": True})
    loaded = store.load_run(recorder.run.id)
    _round_trips(loaded)
    assert len(loaded.events) == 2 and loaded.events[0].id != loaded.events[1].id


def _check_parent_child(store):
    with Recorder("parent_child", store=store, capture_content=True) as recorder:
        with recorder.event(EventKind.AGENT_STEP, "parent") as parent:
            with recorder.event(EventKind.TOOL, "child", parent_id=parent.id) as child:
                recorder.set_response(child, {"ok": True})
    loaded = store.load_run(recorder.run.id)
    _round_trips(loaded)
    assert loaded.events[1].parent_id == loaded.events[0].id


def _check_custom_attributes(store):
    loaded = _record(store, "custom_attributes", EventKind.TOOL, request={}, response={"ok": True},
                      attributes={"custom_key": "custom_value", "nested": {"a": 1}})
    _round_trips(loaded)
    assert loaded.events[0].attributes == {"custom_key": "custom_value", "nested": {"a": 1}}


def _check_long_tool_name(store):
    name = "tool_" + "x" * 300
    loaded = _record(store, name, EventKind.TOOL, request={}, response={"ok": True})
    _round_trips(loaded)
    assert len(loaded.events[0].name) == len(name)


def _check_error_redaction(store):
    loaded = _record(store, "error_redaction", EventKind.TOOL, request={},
                      raises=RuntimeError("auth failed for token sk-abcdefghijklmnopqrstuvwxyz"))
    _round_trips(loaded)
    assert "sk-" not in loaded.events[0].error["message"]


def _check_missing_parent(store):
    loaded = _record(store, "missing_parent", EventKind.TOOL, request={}, response={"ok": True},
                      parent_id="does-not-exist-in-this-run")
    _round_trips(loaded)
    assert loaded.events[0].parent_id == "does-not-exist-in-this-run"


def _check_cancelled_status(store):
    """Event.status is a plain string field the schema doesn't constrain to an enum, but
    Recorder.event()'s context manager always resolves it to "ok" or "error" - an
    externally-cancelled call (never reaches either outcome) can only be represented by
    constructing the Event directly, bypassing the high-level recording API."""
    run = Run("cancelled_status", status="ok")
    run.events.append(Event(EventKind.TOOL, "cancelled_status", status="cancelled"))
    store.save_run(run)
    loaded = store.load_run(run.id)
    assert loaded.events[0].status == "cancelled"


def _check_model_alias(store):
    loaded = _record(store, "model_alias", EventKind.MODEL, request={"prompt": "x"}, response={"text": "y"},
                      attributes={"model": "gpt-4-turbo-2024-04-09", "alias": "gpt-4-turbo"})
    _round_trips(loaded)
    assert loaded.events[0].attributes["alias"] == "gpt-4-turbo"


def _check_multiple_models(store):
    with Recorder("multiple_models", store=store, capture_content=True) as recorder:
        with recorder.event(EventKind.MODEL, "call", request={}, attributes={"model": "gpt-4o"}) as event:
            recorder.set_response(event, {"text": "a"})
        with recorder.event(EventKind.MODEL, "call", request={}, attributes={"model": "claude-opus"}) as event:
            recorder.set_response(event, {"text": "b"})
    loaded = store.load_run(recorder.run.id)
    _round_trips(loaded)
    assert {e.attributes["model"] for e in loaded.events} == {"gpt-4o", "claude-opus"}


def _check_tool_argument_change(store):
    run_a = _record(LocalStore(store.root / "a"), "tool_argument_change", EventKind.TOOL, request={"city": "Paris"}, response={"ok": True})
    run_b = _record(LocalStore(store.root / "b"), "tool_argument_change", EventKind.TOOL, request={"city": "London"}, response={"ok": True})
    comparison = compare_runs(run_a, run_b)
    assert not comparison.equal and any(change["category"] == "tool_behavior" for change in comparison.changes)


def _check_response_change(store):
    run_a = _record(LocalStore(store.root / "a"), "response_change", EventKind.TOOL, request={"q": "x"}, response={"result": 1})
    run_b = _record(LocalStore(store.root / "b"), "response_change", EventKind.TOOL, request={"q": "x"}, response={"result": 2})
    comparison = compare_runs(run_a, run_b)
    assert not comparison.equal and any(change["category"] == "content_identity" for change in comparison.changes)


def _check_latency_boundary(store):
    """Recorder.event()'s context manager always recomputes latency_ms from elapsed
    perf_counter time on exit, so an exact 0.0 boundary can't be produced through the
    normal recording path - construct the Event directly instead."""
    run = Run("latency_boundary", status="ok")
    run.events.append(Event(EventKind.TOOL, "latency_boundary", status="ok", response={"ok": True}, latency_ms=0.0))
    store.save_run(run)
    loaded = store.load_run(run.id)
    assert loaded.events[0].latency_ms == 0.0


def _check_cost_boundary(store):
    loaded = _record(store, "cost_boundary", EventKind.TOOL, request={}, response={"ok": True}, cost_usd=999_999.99)
    _round_trips(loaded)
    assert loaded.events[0].cost_usd == 999_999.99


def _check_conversation_boundary(store):
    loaded = _record(store, "conversation_boundary", EventKind.CONVERSATION, request={"turn": "final"}, response={"text": "done"})
    _round_trips(loaded)
    assert loaded.events[0].kind == EventKind.CONVERSATION


def _check_agent_step_boundary(store):
    loaded = _record(store, "agent_step_boundary", EventKind.AGENT_STEP, request={"step": "leaf"}, response={"done": True})
    _round_trips(loaded)
    assert loaded.events[0].kind == EventKind.AGENT_STEP


def _check_retrieval_boundary(store):
    loaded = _record(store, "retrieval_boundary", EventKind.RETRIEVAL, request={"top_k": 1}, response={"documents": [{"id": 0}]})
    _round_trips(loaded)
    assert len(loaded.events[0].response["documents"]) == 1


def _check_artifact_boundary(store):
    loaded = _record(store, "artifact_boundary", EventKind.ARTIFACT, request={}, response={"content": "x" * 65_536})
    _round_trips(loaded)
    assert len(loaded.events[0].response["content"]) == 65_536


def _check_evaluation_boundary(store):
    loaded = _record(store, "evaluation_boundary", EventKind.EVALUATION, request={"case": "1"},
                      response={"score": 0.5}, attributes={"score": 0.5, "threshold": 0.5})
    _round_trips(loaded)
    assert loaded.events[0].attributes["score"] == loaded.events[0].attributes["threshold"]


FAMILIES = {
    "successful_model": _check_successful_model,
    "model_timeout": _check_model_timeout,
    "provider_rate_limit": _check_provider_rate_limit,
    "tool_timeout": _check_tool_timeout,
    "tool_exception": _check_tool_exception,
    "retried_call": _check_retried_call,
    "parallel_tool_a": _check_parallel_tool_a,
    "parallel_tool_b": _check_parallel_tool_b,
    "malformed_output": _check_malformed_output,
    "large_context": _check_large_context,
    "secret_input": _check_secret_input,
    "secret_tool_result": _check_secret_tool_result,
    "nondeterministic_response": _check_nondeterministic_response,
    "changed_prompt": _check_changed_prompt,
    "changed_tool_schema": _check_changed_tool_schema,
    "unexpected_extra_tool": _check_unexpected_extra_tool,
    "destructive_proposal": _check_destructive_proposal,
    "interrupted_execution": _check_interrupted_execution,
    "nested_agent": _check_nested_agent,
    "partial_trace": _check_partial_trace,
    "corrupted_record": _check_corrupted_record,
    "retrieval_empty": _check_retrieval_empty,
    "retrieval_many": _check_retrieval_many,
    "authorization_allow": _check_authorization_allow,
    "authorization_deny": _check_authorization_deny,
    "artifact_created": _check_artifact_created,
    "evaluation_pass": _check_evaluation_pass,
    "evaluation_fail": _check_evaluation_fail,
    "zero_usage": _check_zero_usage,
    "token_usage": _check_token_usage,
    "zero_cost": _check_zero_cost,
    "nonzero_cost": _check_nonzero_cost,
    "unicode_content": _check_unicode_content,
    "binary_reference": _check_binary_reference,
    "null_response": _check_null_response,
    "list_response": _check_list_response,
    "deep_json": _check_deep_json,
    "duplicate_tool": _check_duplicate_tool,
    "parent_child": _check_parent_child,
    "custom_attributes": _check_custom_attributes,
    "long_tool_name": _check_long_tool_name,
    "error_redaction": _check_error_redaction,
    "missing_parent": _check_missing_parent,
    "cancelled_status": _check_cancelled_status,
    "model_alias": _check_model_alias,
    "multiple_models": _check_multiple_models,
    "tool_argument_change": _check_tool_argument_change,
    "response_change": _check_response_change,
    "latency_boundary": _check_latency_boundary,
    "cost_boundary": _check_cost_boundary,
    "conversation_boundary": _check_conversation_boundary,
    "agent_step_boundary": _check_agent_step_boundary,
    "retrieval_boundary": _check_retrieval_boundary,
    "artifact_boundary": _check_artifact_boundary,
    "evaluation_boundary": _check_evaluation_boundary,
}


@pytest.mark.parametrize("scenario", sorted(FAMILIES))
def test_scenario_exhibits_its_named_behavior(tmp_path, scenario):
    FAMILIES[scenario](LocalStore(tmp_path / scenario))


def test_corpus_has_at_least_50_cases():
    assert len(FAMILIES) >= 50
