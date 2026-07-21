from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "1.0.0"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventKind(str, Enum):
    RUN = "run"
    CONVERSATION = "conversation"
    AGENT_STEP = "agent_step"
    MODEL = "model"
    RETRIEVAL = "retrieval"
    TOOL_PROPOSAL = "tool_proposal"
    AUTHORIZATION = "authorization"
    TOOL = "tool"
    ARTIFACT = "artifact"
    EVALUATION = "evaluation"
    ERROR = "error"


@dataclass(slots=True)
class Event:
    kind: EventKind
    name: str
    id: str = field(default_factory=lambda: uuid4().hex)
    parent_id: str | None = None
    started_at: str = field(default_factory=utcnow)
    ended_at: str | None = None
    status: str = "running"
    attributes: dict[str, Any] = field(default_factory=dict)
    request: Any = None
    response: Any = None
    request_hash: str | None = None
    response_hash: str | None = None
    latency_ms: float | None = None
    cost_usd: float | None = None
    usage: dict[str, int] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["kind"] = self.kind.value
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Event":
        data = dict(value)
        data["kind"] = EventKind(data["kind"])
        return cls(**data)


@dataclass(slots=True)
class Run:
    name: str
    id: str = field(default_factory=lambda: uuid4().hex)
    schema_version: str = SCHEMA_VERSION
    created_at: str = field(default_factory=utcnow)
    ended_at: str | None = None
    status: str = "running"
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["events"] = [event.to_dict() for event in self.events]
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Run":
        data = dict(value)
        data["events"] = [Event.from_dict(item) for item in data.get("events", [])]
        return cls(**data)

