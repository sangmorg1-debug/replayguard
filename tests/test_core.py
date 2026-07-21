from __future__ import annotations

import sqlite3

from replayguard.assertions import Assertion
from replayguard.compare import compare_runs
from replayguard.recorder import Recorder, model_call, tool_call
from replayguard.replay import ReplayMode, Replayer, assert_side_effect_free
from replayguard.schema import Event, EventKind, Run
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


def blob_paths(store: LocalStore) -> set:
    return set(store.blobs.rglob("*.json"))


def test_prune_deletes_the_pruned_runs_own_blob(tmp_path):
    store = LocalStore(tmp_path)
    for index in range(3):
        run = Run(f"run-{index}", status="ok")
        run.events.append(Event(EventKind.TOOL, "op", status="ok", response=f"unique-{index}"))
        store.save_run(run)
    assert len(blob_paths(store)) == 3
    removed = store.prune(keep=1)
    assert removed == 2
    assert len(blob_paths(store)) == 1, "prune() deleted index rows but left the orphaned blob files on disk"


def test_prune_keeps_a_blob_still_referenced_by_another_kept_run(tmp_path):
    """Content-addressed storage dedupes identical content (put_blob skips writing a digest that
    already exists) whenever two saved runs happen to serialize byte-identically - e.g. re-saving
    the exact same run, or re-importing the same deterministically-ID'd OTel trace twice. Pruning
    one index row that happens to share a blob with a still-kept row must not delete that blob."""
    store = LocalStore(tmp_path)
    run = Run("shared", id="fixed-id", status="ok")
    run.events.append(Event(EventKind.TOOL, "op", status="ok", response="content", id="fixed-event-id"))
    other = Run("other", status="ok")
    other.events.append(Event(EventKind.TOOL, "op", status="ok", response="other content"))
    store.save_run(run)
    store.save_run(other)
    # Re-saving the identical run dict again reuses the existing blob (put_blob is idempotent)
    # rather than writing a second copy, simulating two distinct index rows sharing one blob.
    reused_digest = store.put_blob(run.to_dict())
    with sqlite3.connect(store.db_path) as db:
        db.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                   ("second-row-same-blob", run.name, run.created_at, run.status, run.schema_version, reused_digest))
    assert len(blob_paths(store)) == 2
    store.prune(keep=2)  # keeps "other" and "second-row-same-blob"; prunes "shared"
    assert len(blob_paths(store)) == 2, "pruning one row must not delete a blob another kept row still references"

