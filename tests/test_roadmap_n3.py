from pathlib import Path

import pytest

from replayguard.pytest_plugin import ReplayCaseContext
from replayguard.schema import Event, EventKind, Run

pytest_plugins = ["pytester"]
ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SUITE = ROOT / "examples/public-regression-suite.json"


def test_context_exact_replay_is_side_effect_free_and_regressions_are_readable():
    source = Run("case", id="run1", events=[Event(EventKind.TOOL, "lookup", id="span1", status="ok")])
    context = ReplayCaseContext(source, "case1", "public lookup")
    replay = context.replay()
    assert replay.live_calls == 0 and replay.fixture_hits == 1
    changed = Run.from_dict(source.to_dict()); changed.events[0].name = "delete"
    with pytest.raises(pytest.fail.Exception) as failure:
        context.assert_matches(changed)
    assert "ReplayGuard regression" in str(failure.value) and "tool_behavior" in str(failure.value)


def test_plugin_record_and_exact_replay_fixtures(pytester):
    pytester.makepyfile("""
        from replayguard.recorder import tool_call

        @tool_call("lookup")
        def lookup(value):
            return {"value": value}

        def test_record_and_replay(replayguard_record, replayguard_replay):
            with replayguard_record("fixture-test") as recorder:
                assert lookup(7) == {"value": 7}
            result = replayguard_replay(recorder.run.id)
            assert result.fixture_hits == 1
            assert result.live_calls == 0
    """)
    result = pytester.runpytest("-p", "no:replayguard", "-p", "replayguard.pytest_plugin", "-q")
    result.assert_outcomes(passed=1)


def test_plugin_auto_collects_all_106_real_public_cases(pytester):
    pytester.makepyfile("""
        import pytest

        @pytest.mark.replay_case
        def test_public_case(replay_case):
            result = replay_case.replay()
            assert result.live_calls == 0
            assert result.fixture_hits == len(replay_case.source.events)
    """)
    result = pytester.runpytest("-p", "no:replayguard", "-p", "replayguard.pytest_plugin",
                                f"--replayguard-suite={PUBLIC_SUITE}", "-q")
    result.assert_outcomes(passed=106)
