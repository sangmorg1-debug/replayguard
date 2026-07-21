"""pytest-native recording, exact replay, and regression-suite collection."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

from .compare import compare_runs
from .recorder import Recorder
from .replay import ReplayMode, ReplayResult, Replayer, assert_side_effect_free
from .schema import Run
from .storage import LocalStore
from .suites import RegressionCase, RegressionSuite


@dataclass(slots=True)
class ReplayCaseContext:
    """A baseline case exposed to a pytest test."""

    source: Run
    case_id: str
    name: str
    kind: str = "positive"

    def replay(self) -> ReplayResult:
        result = Replayer().replay(self.source, mode=ReplayMode.EXACT)
        if not assert_side_effect_free(self.source, result):
            pytest.fail(f"ReplayGuard exact replay performed a live call for case {self.name!r}", pytrace=False)
        return result

    def assert_matches(self, candidate: Run) -> None:
        comparison = compare_runs(self.source, candidate)
        if not comparison.equal:
            detail = json.dumps(comparison.to_dict(), indent=2, ensure_ascii=False, default=str)
            pytest.fail(f"ReplayGuard regression for {self.name!r} ({self.case_id}):\n{detail}", pytrace=False)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("replayguard")
    group.addoption("--replayguard-store", help="persistent ReplayGuard store (default: per-session temporary store)")
    group.addoption("--replayguard-suite", action="append", default=[], help="JSON regression suite; repeatable")
    group.addoption("--replayguard-capture-content", action="store_true", default=False,
                    help="store locally redacted request/response content while recording")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "replay_case(run_id=None, suite=None, case=None): run a ReplayGuard regression case")


def _marked_suite_paths(metafunc: pytest.Metafunc, marker: pytest.Mark) -> list[str]:
    explicit = marker.kwargs.get("suite")
    if explicit:
        return [str(explicit)]
    return list(metafunc.config.getoption("--replayguard-suite") or [])


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "replay_case" not in metafunc.fixturenames:
        return
    marker = metafunc.definition.get_closest_marker("replay_case")
    if marker is None:
        return
    run_id = marker.kwargs.get("run_id") or (marker.args[0] if marker.args else None)
    if run_id:
        metafunc.parametrize("replay_case", [("run", str(run_id))], indirect=True, ids=[str(run_id)])
        return
    selected = marker.kwargs.get("case")
    parameters: list[tuple[str, str, str]] = []
    ids: list[str] = []
    for path in _marked_suite_paths(metafunc, marker):
        suite = RegressionSuite.load(path)
        for case in suite.cases:
            if selected and selected not in {case.id, case.name}:
                continue
            parameters.append(("suite", str(Path(path).resolve()), case.id))
            ids.append(f"{suite.name}:{case.name}")
    if not parameters:
        raise pytest.UsageError("@pytest.mark.replay_case needs a run_id or a suite via marker/--replayguard-suite")
    metafunc.parametrize("replay_case", parameters, indirect=True, ids=ids)


@pytest.fixture(scope="session")
def replayguard_store(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> LocalStore:
    configured = request.config.getoption("--replayguard-store")
    store = LocalStore(configured or tmp_path_factory.mktemp("replayguard") / "store")
    store.init()
    return store


@pytest.fixture
def replayguard_record(request: pytest.FixtureRequest, replayguard_store: LocalStore) -> Callable[..., Recorder]:
    capture = bool(request.config.getoption("--replayguard-capture-content"))

    def factory(name: str, **kwargs: Any) -> Recorder:
        kwargs.setdefault("capture_content", capture)
        return Recorder(name, store=replayguard_store, **kwargs)

    return factory


@pytest.fixture
def replayguard_replay(replayguard_store: LocalStore) -> Callable[[Run | str], ReplayResult]:
    def exact(source: Run | str) -> ReplayResult:
        run = replayguard_store.load_run(source) if isinstance(source, str) else source
        result = Replayer().replay(run, mode=ReplayMode.EXACT)
        if not assert_side_effect_free(run, result):
            pytest.fail("ReplayGuard exact replay was not side-effect free", pytrace=False)
        return result

    return exact


@pytest.fixture
def replay_case(request: pytest.FixtureRequest, replayguard_store: LocalStore) -> ReplayCaseContext:
    value = getattr(request, "param", None)
    if not value:
        pytest.fail("replay_case must be used with @pytest.mark.replay_case", pytrace=False)
    if value[0] == "run":
        run = replayguard_store.load_run(value[1])
        return ReplayCaseContext(run, run.id, run.name)
    suite = RegressionSuite.load(value[1])
    case: RegressionCase | None = next((item for item in suite.cases if item.id == value[2]), None)
    if case is None:
        pytest.fail(f"ReplayGuard suite case disappeared: {value[2]}", pytrace=False)
    return ReplayCaseContext(Run.from_dict(case.source_run), case.id, case.name, case.kind)
