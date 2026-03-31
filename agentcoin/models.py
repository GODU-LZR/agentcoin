from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_after(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class AgentCard:
    node_id: str
    name: str
    description: str
    protocols: list[str] = field(default_factory=lambda: ["agentcoin/0.1"])
    capabilities: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    runtimes: list[str] = field(default_factory=list)
    offline_mode: bool = True
    secure_by_default: bool = True
    endpoints: dict[str, str] = field(default_factory=dict)
    network: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TaskEnvelope:
    id: str
    kind: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=utc_now)
    sender: str = "local"
    priority: int = 5
    status: str = "queued"
    deliver_to: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TaskEnvelope":
        return cls(
            id=str(raw.get("id") or uuid4()),
            kind=str(raw.get("kind") or "generic"),
            payload=dict(raw.get("payload") or {}),
            created_at=str(raw.get("created_at") or utc_now()),
            sender=str(raw.get("sender") or "local"),
            priority=int(raw.get("priority") or 5),
            status=str(raw.get("status") or "queued"),
            deliver_to=raw.get("deliver_to"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
