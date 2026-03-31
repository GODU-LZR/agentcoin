from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentcoin.models import AgentCard


@dataclass(slots=True)
class PeerConfig:
    peer_id: str
    name: str
    url: str
    auth_token: str | None = None
    overlay_endpoint: str | None = None
    overlay_addresses: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NodeConfig:
    node_id: str = "agentcoin-local"
    name: str = "AgentCoin Reference Node"
    description: str = "Offline-first reference node for the AgentCoin swarm network."
    host: str = "127.0.0.1"
    port: int = 8080
    advertise_url: str | None = None
    auth_token: str = "change-me"
    database_path: str = "./var/agentcoin.db"
    git_root: str | None = None
    sync_interval_seconds: int = 15
    max_body_bytes: int = 262144
    outbox_max_attempts: int = 5
    task_retry_limit: int = 3
    task_retry_backoff_seconds: int = 5
    local_dispatch_fallback: bool = True
    overlay_network: str = "tailnet"
    overlay_endpoint: str | None = None
    overlay_addresses: list[str] = field(default_factory=list)
    capabilities: list[str] = field(
        default_factory=lambda: ["task-routing", "offline-queue", "agent-card", "secure-ingress"]
    )
    tags: list[str] = field(default_factory=lambda: ["reference", "cross-platform", "offline-first"])
    runtimes: list[str] = field(default_factory=lambda: ["python"])
    peers: list[PeerConfig] = field(default_factory=list)

    @property
    def base_url(self) -> str:
        return self.advertise_url or f"http://{self.host}:{self.port}"

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
                "peers": f"{self.base_url}/v1/peers",
                "peer_cards": f"{self.base_url}/v1/peer-cards",
                "git_status": f"{self.base_url}/v1/git/status" if self.git_root else "",
                "git_diff": f"{self.base_url}/v1/git/diff" if self.git_root else "",
            },
            network={
                "overlay_network": self.overlay_network,
                "overlay_endpoint": self.overlay_endpoint,
                "overlay_addresses": self.overlay_addresses,
            },
        )

    def resolve_peer(self, peer_id: str) -> PeerConfig:
        for peer in self.peers:
            if peer.enabled and peer.peer_id == peer_id:
                return peer
        raise KeyError(peer_id)

    def peers_view(self) -> list[dict[str, Any]]:
        return [peer.to_dict() for peer in self.peers]


def load_config(path: str | None) -> NodeConfig:
    if not path:
        return NodeConfig()

    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    data["peers"] = [PeerConfig(**peer) for peer in data.get("peers", [])]
    return NodeConfig(**data)
