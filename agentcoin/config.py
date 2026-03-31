from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentcoin.models import AgentCard


@dataclass(slots=True)
class NodeConfig:
    node_id: str = "agentcoin-local"
    name: str = "AgentCoin Reference Node"
    description: str = "Offline-first reference node for the AgentCoin swarm network."
    host: str = "127.0.0.1"
    port: int = 8080
    auth_token: str = "change-me"
    database_path: str = "./var/agentcoin.db"
    sync_interval_seconds: int = 15
    max_body_bytes: int = 262144
    capabilities: list[str] = field(
        default_factory=lambda: ["task-routing", "offline-queue", "agent-card", "secure-ingress"]
    )
    tags: list[str] = field(default_factory=lambda: ["reference", "cross-platform", "offline-first"])
    runtimes: list[str] = field(default_factory=lambda: ["python"])
    peers: list[dict[str, Any]] = field(default_factory=list)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def card(self) -> AgentCard:
        return AgentCard(
            node_id=self.node_id,
            name=self.name,
            description=self.description,
            capabilities=self.capabilities,
            tags=self.tags,
            runtimes=self.runtimes,
            endpoints={
                "health": f"{self.base_url}/healthz",
                "card": f"{self.base_url}/v1/card",
                "tasks": f"{self.base_url}/v1/tasks",
                "inbox": f"{self.base_url}/v1/inbox",
            },
        )


def load_config(path: str | None) -> NodeConfig:
    if not path:
        return NodeConfig()

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return NodeConfig(**data)

