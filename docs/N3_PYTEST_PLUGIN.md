# N3 pytest plugin

ReplayGuard is registered through pytest's `pytest11` entry-point group. Installing the package
makes these fixtures available without a project `conftest.py`:

- `replayguard_store`: isolated temporary local store, or a persistent store selected with
  `--replayguard-store`.
- `replayguard_record`: factory for locally redacted `Recorder` contexts.
- `replayguard_replay`: exact-only replay by `Run` or stored run ID; fails if replay is not
  side-effect free.
- `replay_case`: a marked stored run or automatically parameterized regression-suite case.

## First replay test

```python
from replayguard import tool_call

@tool_call("lookup")
def lookup(query):
    return {"query": query, "result": "ok"}

def test_agent(replayguard_record, replayguard_replay):
    with replayguard_record("my-agent") as recorder:
        lookup("public data")
    replay = replayguard_replay(recorder.run.id)
    assert replay.live_calls == 0
```

Content capture remains off unless pytest is called with `--replayguard-capture-content`.

## Automatic suite collection

```python
import pytest

@pytest.mark.replay_case
def test_every_regression(replay_case):
    replay = replay_case.replay()
    assert replay.live_calls == 0
```

```powershell
pytest --replayguard-suite examples/public-regression-suite.json
```

The marker also accepts `run_id=`, `suite=`, and `case=` for focused selection. Calling
`replay_case.assert_matches(candidate_run)` emits ReplayGuard's structured behavior differences
in the pytest failure.

## Measured gate

`python tools/smoke_pytest_plugin.py` creates a clean temporary virtual environment, installs the
project, relies on automatic entry-point discovery, and runs the committed first-test example.
The script fails if total install-to-passing-test time exceeds 600 seconds. The plugin's automated
dogfood test also collects and exactly replays all 106 cases in the public regression suite.
