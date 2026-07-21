from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from .schema import Event, EventKind, Run, utcnow


class ReplayMode(str, Enum):
    EXACT = "exact"
    SELECTIVE = "selective"
    COMPARATIVE = "comparative"


@dataclass
class ReplayResult:
    run: Run
    fixture_hits: int
    live_calls: int


class Replayer:
    """Replays recorded interactions. Exact mode has no live-call code path."""

    def replay(self, source: Run, *, mode: ReplayMode = ReplayMode.EXACT,
               live: dict[str, Callable[[Any], Any]] | None = None,
               live_names: set[str] | None = None) -> ReplayResult:
        live = live or {}
        live_names = live_names or set()
        result = Run(name=f"replay:{source.name}", attributes={"source_run_id": source.id, "mode": mode.value})
        fixture_hits = live_calls = 0
        for original in source.events:
            item = Event.from_dict(original.to_dict())
            item.id = f"replay-{original.id}"
            item.started_at = utcnow()
            item.ended_at = utcnow()
            should_live = mode != ReplayMode.EXACT and item.name in live_names
            if should_live:
                if item.name not in live:
                    raise KeyError(f"no live adapter for {item.name}")
                item.response = live[item.name](item.request)
                live_calls += 1
            else:
                fixture_hits += 1
            result.events.append(item)
        result.status = "ok"
        result.ended_at = utcnow()
        return ReplayResult(result, fixture_hits, live_calls)


def assert_side_effect_free(source: Run, replayed: ReplayResult) -> bool:
    external = {EventKind.MODEL, EventKind.RETRIEVAL, EventKind.TOOL}
    expected = sum(event.kind in external for event in source.events)
    return replayed.live_calls == 0 and replayed.fixture_hits >= expected

