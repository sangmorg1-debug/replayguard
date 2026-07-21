from __future__ import annotations

from replayguard.assertions import Assertion
from replayguard.compare import compare_runs
from replayguard.recorder import Recorder, model_call, tool_call
from replayguard.replay import ReplayMode, Replayer, assert_side_effect_free
from replayguard.schema import EventKind, Run
from replayguard.storage import LocalStore


def test_capture_off_by_default(tmp_path):
    store = LocalStore(tmp_path / ".verify")
    with Recorder("private", store=store) as recorder:
        with recorder.event(EventKind.MODEL, "answer", request={"secret": "value"}) as event:
            recorder.set_response(event, {"answer": 42})
    loaded = store.load_run(recorder.run.id)
    assert loaded.events[0].request is None
    assert loaded.events[0].response is None
    assert loaded.events[0].request_hash and loaded.events[0].response_hash


def test_decorators_capture_and_redact(tmp_path):
    @tool_call("lookup")
    def lookup(token):
        return {"authorization": token, "ok": True}

    with Recorder("capture", store=LocalStore(tmp_path), capture_content=True) as recorder:
        lookup("sk-abcdefghijklmnopqrstuvwxyz")
    event = recorder.run.events[0]
    assert "sk-" not in repr(event.request)
    assert "sk-" not in repr(event.response)


def test_top_level_exception_message_is_redacted(tmp_path):
    store = LocalStore(tmp_path)
    try:
        with Recorder("failing", store=store) as recorder:
            raise RuntimeError("Authentication failed for token sk-abcdefghijklmnopqrstuvwxyz")
    except RuntimeError:
        pass
    loaded = store.load_run(recorder.run.id)
    error_events = [event for event in loaded.events if event.kind == EventKind.ERROR]
    assert error_events, "Recorder.__exit__ did not record the top-level exception"
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in error_events[0].error["message"]


def test_async_decorators_await_and_capture_the_real_result(tmp_path):
    import asyncio

    @tool_call("async_lookup")
    async def lookup(token):
        await asyncio.sleep(0)
        return {"authorization": token, "ok": True}

    async def run():
        with Recorder("async-capture", store=LocalStore(tmp_path), capture_content=True) as recorder:
            result = await lookup("sk-abcdefghijklmnopqrstuvwxyz")
        return recorder, result

    recorder, result = asyncio.run(run())
    assert result == {"authorization": "sk-abcdefghijklmnopqrstuvwxyz", "ok": True}
    event = recorder.run.events[0]
    assert event.status == "ok"
    assert "sk-" not in repr(event.request)
    assert "sk-" not in repr(event.response)


def test_async_decorator_records_a_raised_exception(tmp_path):
    import asyncio

    @tool_call("async_failure")
    async def fails():
        await asyncio.sleep(0)
        raise RuntimeError("boom")

    async def run():
        with Recorder("async-error", store=LocalStore(tmp_path)) as recorder:
            try:
                await fails()
            except RuntimeError:
                pass
        return recorder

    recorder = asyncio.run(run())
    assert recorder.run.events[0].status == "error"


def test_exact_replay_has_no_live_path(tmp_path):
    called = 0
    source = Run("source")
    with Recorder("source", store=LocalStore(tmp_path), capture_content=True) as recorder:
        with recorder.event(EventKind.TOOL, "danger", request={"delete": True}) as event:
            recorder.set_response(event, "fixture")
    def live(_):
        nonlocal called
        called += 1
    result = Replayer().replay(recorder.run, mode=ReplayMode.EXACT, live={"danger": live}, live_names={"danger"})
    assert called == 0
    assert result.live_calls == 0
    assert assert_side_effect_free(recorder.run, result)


def test_compare_finds_regression():
    left, right = Run("a", status="ok"), Run("b", status="ok")
    from replayguard.schema import Event
    left.events.append(Event(EventKind.TOOL, "safe", status="ok"))
    right.events.append(Event(EventKind.TOOL, "unexpected", status="ok"))
    comparison = compare_runs(left, right)
    assert not comparison.equal
    assert comparison.changes[0]["category"] == "structure"


def test_assertions(tmp_path):
    with Recorder("assert", store=LocalStore(tmp_path), capture_content=True) as recorder:
        with recorder.event(EventKind.TOOL, "search") as event:
            recorder.set_response(event, "needle")
    assert Assertion("contains", "needle").evaluate(recorder.run).passed
    assert Assertion("tool_called", target="search").evaluate(recorder.run).passed
    assert Assertion("tool_count", expected=1).evaluate(recorder.run).passed
    assert Assertion("no_unhandled_error").evaluate(recorder.run).passed

