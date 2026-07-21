from __future__ import annotations

import contextvars
import functools
import hashlib
import json
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, TypeVar

from .redaction import Redactor
from .schema import Event, EventKind, Run, utcnow
from .storage import LocalStore

T = TypeVar("T")
_active: contextvars.ContextVar["Recorder | None"] = contextvars.ContextVar("replayguard_recorder", default=None)


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=repr, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class Recorder:
    def __init__(self, name: str, *, store: LocalStore | None = None,
                 capture_content: bool = False, attributes: dict[str, Any] | None = None,
                 redactor: Redactor | None = None) -> None:
        self.run = Run(name=name, attributes=attributes or {})
        self.store = store or LocalStore()
        self.capture_content = capture_content
        self.redactor = redactor or Redactor()
        self._token: contextvars.Token | None = None

    def __enter__(self) -> "Recorder":
        self._token = _active.set(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.run.ended_at = utcnow()
        self.run.status = "error" if exc else "ok"
        if exc:
            self.run.events.append(Event(kind=EventKind.ERROR, name=type(exc).__name__, status="error",
                                         ended_at=utcnow(), error={"type": type(exc).__name__, "message": str(exc)}))
        self.store.save_run(self.run)
        if self._token is not None:
            _active.reset(self._token)

    @contextmanager
    def event(self, kind: EventKind, name: str, *, request: Any = None,
              parent_id: str | None = None, attributes: dict[str, Any] | None = None) -> Iterator[Event]:
        safe_request = self.redactor.redact(request)
        item = Event(kind=kind, name=name, parent_id=parent_id, attributes=attributes or {},
                     request=safe_request if self.capture_content else None,
                     request_hash=_hash(safe_request) if request is not None else None)
        self.run.events.append(item)
        started = time.perf_counter()
        try:
            yield item
            item.status = "ok"
        except Exception as exc:
            item.status = "error"
            item.error = {"type": type(exc).__name__, "message": self.redactor.redact(str(exc))}
            raise
        finally:
            item.ended_at = utcnow()
            item.latency_ms = (time.perf_counter() - started) * 1000

    def set_response(self, event: Event, response: Any, *, usage: dict[str, int] | None = None,
                     cost_usd: float | None = None) -> Any:
        safe = self.redactor.redact(response)
        event.response_hash = _hash(safe)
        event.response = safe if self.capture_content else None
        event.usage = usage or {}
        event.cost_usd = cost_usd
        return response


def current_recorder() -> Recorder | None:
    return _active.get()


def _instrument(kind: EventKind, name: str | None = None):
    def decorate(function: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            recorder = current_recorder()
            if recorder is None:
                return function(*args, **kwargs)
            request = {"args": args, "kwargs": kwargs}
            with recorder.event(kind, name or function.__qualname__, request=request) as event:
                return recorder.set_response(event, function(*args, **kwargs))
        return wrapped
    return decorate


def model_call(name: str | None = None):
    return _instrument(EventKind.MODEL, name)


def tool_call(name: str | None = None):
    return _instrument(EventKind.TOOL, name)

