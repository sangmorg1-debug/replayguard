from replayguard import tool_call


@tool_call("public_lookup")
def lookup(topic):
    return {"topic": topic, "result": "fixture-safe"}


def test_agent_replays_without_live_calls(replayguard_record, replayguard_replay):
    with replayguard_record("pytest-quickstart") as recorder:
        assert lookup("TRAIL")["result"] == "fixture-safe"

    replay = replayguard_replay(recorder.run.id)
    assert replay.fixture_hits == 1
    assert replay.live_calls == 0
