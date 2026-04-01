from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentcoin.models import utc_now


@dataclass(frozen=True, slots=True)
class RuntimeAdapterDescriptor:
    runtime: str
    version: str
    title: str
    description: str
    task_payload_key: str = "_runtime"
    bind_endpoint: str = "/v1/runtimes/bind"

    def to_dict(self) -> dict[str, str]:
        return {
            "runtime": self.runtime,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "task_payload_key": self.task_payload_key,
            "bind_endpoint": self.bind_endpoint,
        }


class RuntimeRegistry:
    def __init__(self) -> None:
        self._runtimes: dict[str, RuntimeAdapterDescriptor] = {
            "http-json": RuntimeAdapterDescriptor(
                runtime="http-json",
                version="0.1",
                title="HTTP JSON Runtime Adapter",
                description="Execute a task by forwarding a normalized envelope to an HTTP JSON agent runtime.",
            ),
            "cli-json": RuntimeAdapterDescriptor(
                runtime="cli-json",
                version="0.1",
                title="CLI JSON Runtime Adapter",
                description="Execute a task by invoking a local CLI agent that accepts JSON over stdin/stdout.",
            ),
        }

    def list_runtimes(self) -> list[dict[str, str]]:
        return [descriptor.to_dict() for descriptor in self._runtimes.values()]

    def normalize_binding(self, runtime: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        runtime_key = str(runtime or "").strip().lower()
        if runtime_key not in self._runtimes:
            raise ValueError(f"unsupported runtime adapter: {runtime}")
        payload = dict(options or {})
        payload["runtime"] = runtime_key
        payload.setdefault("bound_at", utc_now())
        return payload
