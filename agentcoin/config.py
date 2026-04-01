from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentcoin.models import AgentCard
from agentcoin.net import OutboundNetworkConfig
from agentcoin.onchain import OnchainBindings
from agentcoin.security import resolve_public_key


@dataclass(slots=True)
class PeerConfig:
    peer_id: str
    name: str
    url: str
    auth_token: str | None = None
    signing_secret: str | None = None
    identity_principal: str | None = None
    identity_public_key: str | None = None
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
    signing_secret: str | None = None
    require_signed_inbox: bool = False
    identity_principal: str | None = None
    identity_private_key_path: str | None = None
    identity_public_key: str | None = None
    database_path: str = "./var/agentcoin.db"
    git_root: str | None = None
    sync_interval_seconds: int = 15
    max_body_bytes: int = 262144
    outbox_max_attempts: int = 5
    task_retry_limit: int = 3
    task_retry_backoff_seconds: int = 5
    local_dispatch_fallback: bool = True
    challenge_bond_required_wei: int = 0
    bridges: list[str] = field(default_factory=lambda: ["mcp", "a2a"])
    network: OutboundNetworkConfig = field(default_factory=OutboundNetworkConfig)
    onchain: OnchainBindings = field(default_factory=OnchainBindings)
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
    def resolved_identity_public_key(self) -> str | None:
        return resolve_public_key(private_key_path=self.identity_private_key_path, public_key=self.identity_public_key)

    @property
    def card(self) -> AgentCard:
        protocols = ["agentcoin/0.1", *[f"{protocol}-bridge/0.1" for protocol in self.bridges]]
        return AgentCard(
            node_id=self.node_id,
            name=self.name,
            description=self.description,
            protocols=protocols,
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
                "bridges": f"{self.base_url}/v1/bridges",
                "bridge_import": f"{self.base_url}/v1/bridges/import",
                "bridge_export": f"{self.base_url}/v1/bridges/export",
                "runtimes": f"{self.base_url}/v1/runtimes",
                "runtime_bind": f"{self.base_url}/v1/runtimes/bind",
                "openclaw_bind": f"{self.base_url}/v1/integrations/openclaw/bind",
                "schema_context": f"{self.base_url}/v1/schema/context",
                "schema_capabilities": f"{self.base_url}/v1/schema/capabilities",
                "schema_examples": f"{self.base_url}/v1/schema/examples",
                "dispatch_preview": f"{self.base_url}/v1/tasks/dispatch/preview",
                "dispatch_evaluate": f"{self.base_url}/v1/tasks/dispatch/evaluate",
                "poaw_events": f"{self.base_url}/v1/poaw/events",
                "poaw_summary": f"{self.base_url}/v1/poaw/summary",
                "disputes": f"{self.base_url}/v1/disputes",
                "git_status": f"{self.base_url}/v1/git/status" if self.git_root else "",
                "git_diff": f"{self.base_url}/v1/git/diff" if self.git_root else "",
                "onchain_status": f"{self.base_url}/v1/onchain/status" if self.onchain.enabled else "",
                "onchain_bind": f"{self.base_url}/v1/onchain/task-bind" if self.onchain.enabled else "",
                "onchain_settlement_preview": f"{self.base_url}/v1/onchain/settlement-preview" if self.onchain.enabled else "",
                "onchain_settlement_rpc_plan": f"{self.base_url}/v1/onchain/settlement-rpc-plan" if self.onchain.enabled else "",
                "onchain_settlement_raw_bundle": f"{self.base_url}/v1/onchain/settlement-raw-bundle" if self.onchain.enabled else "",
                "onchain_settlement_relay": f"{self.base_url}/v1/onchain/settlement-relay" if self.onchain.enabled else "",
                "onchain_settlement_relays": f"{self.base_url}/v1/onchain/settlement-relays" if self.onchain.enabled else "",
                "onchain_settlement_relay_latest": f"{self.base_url}/v1/onchain/settlement-relays/latest" if self.onchain.enabled else "",
                "onchain_settlement_relay_replay": f"{self.base_url}/v1/onchain/settlement-relays/replay" if self.onchain.enabled else "",
                "onchain_rpc_payload": f"{self.base_url}/v1/onchain/rpc-payload" if self.onchain.enabled else "",
                "onchain_rpc_plan": f"{self.base_url}/v1/onchain/rpc-plan" if self.onchain.enabled else "",
                "onchain_rpc_send_raw": f"{self.base_url}/v1/onchain/rpc/send-raw" if self.onchain.enabled else "",
            },
            network={
                "overlay_network": self.overlay_network,
                "overlay_endpoint": self.overlay_endpoint,
                "overlay_addresses": self.overlay_addresses,
                "egress": self.network.transport_profile(),
                "onchain": self.onchain.to_dict(),
            },
            identity={
                "scheme": "ssh-ed25519" if self.resolved_identity_public_key and self.identity_principal else "",
                "principal": self.identity_principal,
                "public_key": self.resolved_identity_public_key,
                "did": self.onchain.local_did,
                "controller_address": self.onchain.local_controller_address,
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
    data["network"] = OutboundNetworkConfig(**data.get("network", {}))
    data["onchain"] = OnchainBindings(**data.get("onchain", {}))
    return NodeConfig(**data)
