from __future__ import annotations

import copy
import difflib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentcoin.models import AgentCard
from agentcoin.net import OutboundNetworkConfig
from agentcoin.onchain import OnchainBindings
from agentcoin.security import derive_local_did, ensure_local_ssh_identity, resolve_public_key

DEFAULT_POAW_SCORE_WEIGHTS: dict[str, int] = {
    "worker_base": 10,
    "reviewer_base": 8,
    "planner_base": 6,
    "aggregator_base": 9,
    "kind_code_bonus": 2,
    "kind_review_bonus": 2,
    "kind_merge_bonus": 3,
    "kind_plan_bonus": 1,
    "workflow_bonus": 1,
    "required_capability_bonus_cap": 3,
    "approved_bonus": 2,
    "merged_bonus": 1,
}


@dataclass(slots=True)
class PeerConfig:
    peer_id: str
    name: str
    url: str
    auth_token: str | None = None
    signing_secret: str | None = None
    identity_principal: str | None = None
    identity_public_key: str | None = None
    identity_public_keys: list[str] = field(default_factory=list)
    identity_revoked_public_keys: list[str] = field(default_factory=list)
    overlay_endpoint: str | None = None
    overlay_addresses: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    enabled: bool = True

    @property
    def revoked_identity_public_keys(self) -> list[str]:
        keys: list[str] = []
        for candidate in self.identity_revoked_public_keys:
            normalized = str(candidate or "").strip()
            if normalized and normalized not in keys:
                keys.append(normalized)
        return keys

    @property
    def trusted_identity_public_keys(self) -> list[str]:
        revoked = set(self.revoked_identity_public_keys)
        keys: list[str] = []
        for candidate in [self.identity_public_key, *self.identity_public_keys]:
            normalized = str(candidate or "").strip()
            if normalized and normalized not in revoked and normalized not in keys:
                keys.append(normalized)
        return keys

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OperatorIdentityConfig:
    key_id: str
    name: str | None = None
    shared_secret: str | None = None
    identity_principal: str | None = None
    identity_public_key: str | None = None
    identity_public_keys: list[str] = field(default_factory=list)
    identity_revoked_public_keys: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    source_restrictions: list[str] = field(default_factory=list)
    enabled: bool = True

    @property
    def revoked_identity_public_keys(self) -> list[str]:
        keys: list[str] = []
        for candidate in self.identity_revoked_public_keys:
            normalized = str(candidate or "").strip()
            if normalized and normalized not in keys:
                keys.append(normalized)
        return keys

    @property
    def trusted_identity_public_keys(self) -> list[str]:
        revoked = set(self.revoked_identity_public_keys)
        keys: list[str] = []
        for candidate in [self.identity_public_key, *self.identity_public_keys]:
            normalized = str(candidate or "").strip()
            if normalized and normalized not in revoked and normalized not in keys:
                keys.append(normalized)
        return keys

    @property
    def normalized_scopes(self) -> list[str]:
        scopes: list[str] = []
        for candidate in self.scopes:
            normalized = str(candidate or "").strip().lower()
            if normalized and normalized not in scopes:
                scopes.append(normalized)
        return scopes

    @property
    def normalized_source_restrictions(self) -> list[str]:
        restrictions: list[str] = []
        for candidate in self.source_restrictions:
            normalized = str(candidate or "").strip().lower()
            if normalized and normalized not in restrictions:
                restrictions.append(normalized)
        return restrictions

    @property
    def supports_signed_requests(self) -> bool:
        return bool(
            str(self.shared_secret or "").strip()
            or (
                str(self.identity_principal or "").strip()
                and self.trusted_identity_public_keys
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScopedBearerTokenConfig:
    token_id: str
    token: str
    name: str | None = None
    scopes: list[str] = field(default_factory=list)
    source_restrictions: list[str] = field(default_factory=list)
    enabled: bool = True

    @property
    def normalized_scopes(self) -> list[str]:
        scopes: list[str] = []
        for candidate in self.scopes:
            normalized = str(candidate or "").strip().lower()
            if normalized and normalized not in scopes:
                scopes.append(normalized)
        return scopes

    @property
    def normalized_source_restrictions(self) -> list[str]:
        restrictions: list[str] = []
        for candidate in self.source_restrictions:
            normalized = str(candidate or "").strip().lower()
            if normalized and normalized not in restrictions:
                restrictions.append(normalized)
        return restrictions

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
    auto_bootstrap_identity: bool = True
    identity_principal: str | None = None
    identity_private_key_path: str | None = None
    identity_public_key: str | None = None
    identity_public_keys: list[str] = field(default_factory=list)
    identity_revoked_public_keys: list[str] = field(default_factory=list)
    operator_identities: list[OperatorIdentityConfig] = field(default_factory=list)
    scoped_bearer_tokens: list[ScopedBearerTokenConfig] = field(default_factory=list)
    operator_allow_loopback_bearer_fallback: bool = False
    operator_auth_timestamp_skew_seconds: int = 300
    operator_auth_nonce_ttl_seconds: int = 900
    identity_auth_challenge_ttl_seconds: int = 300
    identity_auth_session_ttl_seconds: int = 900
    cors_allowed_origins: list[str] = field(default_factory=lambda: ["*"])
    config_path: str | None = field(default=None, repr=False, compare=False)
    database_path: str = "./var/agentcoin.db"
    git_root: str | None = None
    sync_interval_seconds: int = 15
    settlement_relay_poll_seconds: float = 2.0
    settlement_relay_max_in_flight: int = 1
    max_body_bytes: int = 262144
    outbox_max_attempts: int = 5
    task_retry_limit: int = 3
    task_retry_backoff_seconds: int = 5
    local_dispatch_fallback: bool = True
    payment_required_workflows: list[str] = field(default_factory=list)
    payment_quote_amount_wei: int = 10000000000000000
    payment_quote_asset: str = "AGENT"
    payment_quote_ttl_seconds: int = 300
    payment_receipt_ttl_seconds: int = 3600
    challenge_bond_required_wei: int = 0
    poaw_policy_version: str = "0.2"
    poaw_score_weights: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_POAW_SCORE_WEIGHTS))
    dispatch_peer_cooldown_seconds: int = 60
    dispatch_peer_blacklist_after_failures: int = 4
    dispatch_peer_blacklist_seconds: int = 300
    dispatch_weak_network_penalty_cap: int = 120
    dispatch_backlog_penalty_cap: int = 120
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
    def advertised_identity_public_keys(self) -> list[str]:
        revoked = set(self.advertised_identity_revoked_public_keys)
        keys: list[str] = []
        for candidate in [self.resolved_identity_public_key, *self.identity_public_keys]:
            normalized = str(candidate or "").strip()
            if normalized and normalized not in revoked and normalized not in keys:
                keys.append(normalized)
        return keys

    @property
    def advertised_identity_revoked_public_keys(self) -> list[str]:
        keys: list[str] = []
        for candidate in self.identity_revoked_public_keys:
            normalized = str(candidate or "").strip()
            if normalized and normalized not in keys:
                keys.append(normalized)
        return keys

    @property
    def resolved_local_did(self) -> str | None:
        return str(self.onchain.local_did or "").strip() or derive_local_did(
            private_key_path=self.identity_private_key_path,
            public_key=self.resolved_identity_public_key,
        )

    @property
    def card(self) -> AgentCard:
        from agentcoin.runtimes import RuntimeRegistry

        protocols = ["agentcoin/0.1", *[f"{protocol}-bridge/0.1" for protocol in self.bridges]]
        runtime_capabilities = RuntimeRegistry().advertisement(self.runtimes)
        return AgentCard(
            node_id=self.node_id,
            name=self.name,
            description=self.description,
            protocols=protocols,
            capabilities=self.capabilities,
            tags=self.tags,
            runtimes=self.runtimes,
            runtime_capabilities=runtime_capabilities,
            endpoints={
                "health": f"{self.base_url}/healthz",
                "card": f"{self.base_url}/v1/card",
                "manifest": f"{self.base_url}/v1/manifest",
                "auth_challenge": f"{self.base_url}/v1/auth/challenge",
                "auth_verify": f"{self.base_url}/v1/auth/verify",
                "workflow_execute": f"{self.base_url}/v1/workflow/execute",
                "payment_receipt_issue": f"{self.base_url}/v1/payments/receipts/issue",
                "payment_receipt_introspect": f"{self.base_url}/v1/payments/receipts/introspect",
                "payment_receipt_onchain_proof": f"{self.base_url}/v1/payments/receipts/onchain-proof",
                "payment_receipt_onchain_rpc_plan": f"{self.base_url}/v1/payments/receipts/onchain-rpc-plan",
                "payment_receipt_onchain_raw_bundle": f"{self.base_url}/v1/payments/receipts/onchain-raw-bundle",
                "payment_receipt_onchain_relay": f"{self.base_url}/v1/payments/receipts/onchain-relay",
                "payment_receipt_onchain_relays": f"{self.base_url}/v1/payments/receipts/onchain-relays",
                "payment_receipt_onchain_relay_latest": f"{self.base_url}/v1/payments/receipts/onchain-relays/latest",
                "payment_receipt_onchain_relay_latest_failed": f"{self.base_url}/v1/payments/receipts/onchain-relays/latest-failed",
                "payment_ops_summary": f"{self.base_url}/v1/payments/ops/summary",
                "payment_receipt_onchain_relay_queue": f"{self.base_url}/v1/payments/receipts/onchain-relay-queue",
                "payment_receipt_onchain_relay_queue_summary": f"{self.base_url}/v1/payments/receipts/onchain-relay-queue/summary",
                "payment_receipt_onchain_relay_queue_pause": f"{self.base_url}/v1/payments/receipts/onchain-relay-queue/pause",
                "payment_receipt_onchain_relay_queue_resume": f"{self.base_url}/v1/payments/receipts/onchain-relay-queue/resume",
                "payment_receipt_onchain_relay_queue_requeue": f"{self.base_url}/v1/payments/receipts/onchain-relay-queue/requeue",
                "payment_receipt_onchain_relay_queue_cancel": f"{self.base_url}/v1/payments/receipts/onchain-relay-queue/cancel",
                "payment_receipt_onchain_relay_queue_delete": f"{self.base_url}/v1/payments/receipts/onchain-relay-queue/delete",
                "payment_receipt_onchain_relay_replay_helper": f"{self.base_url}/v1/payments/receipts/onchain-relay/replay-helper",
                "payment_receipt_status": f"{self.base_url}/v1/payments/receipts/status",
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
                "peer_health": f"{self.base_url}/v1/peer-health",
                "peer_health_cooldown": f"{self.base_url}/v1/peer-health/cooldown",
                "peer_health_blacklist": f"{self.base_url}/v1/peer-health/blacklist",
                "peer_health_clear": f"{self.base_url}/v1/peer-health/clear",
                "peer_identity_trust_export": f"{self.base_url}/v1/peers/identity-trust/export",
                "peer_identity_trust_apply": f"{self.base_url}/v1/peers/identity-trust/apply",
                "disputes": f"{self.base_url}/v1/disputes",
                "disputes_vote": f"{self.base_url}/v1/disputes/vote",
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
                "public_keys": self.advertised_identity_public_keys,
                "revoked_public_keys": self.advertised_identity_revoked_public_keys,
                "did": self.resolved_local_did,
                "controller_address": self.onchain.local_controller_address,
            },
        )

    def resolve_peer(self, peer_id: str) -> PeerConfig:
        for peer in self.peers:
            if peer.enabled and peer.peer_id == peer_id:
                return peer
        raise KeyError(peer_id)

    def resolve_operator_identity(self, key_id: str) -> OperatorIdentityConfig:
        normalized_key_id = str(key_id or "").strip()
        for operator in self.operator_identities:
            if operator.enabled and operator.key_id == normalized_key_id:
                return operator
        raise KeyError(normalized_key_id)

    def resolve_scoped_bearer_token(self, token: str) -> ScopedBearerTokenConfig:
        normalized_token = str(token or "").strip()
        for bearer in self.scoped_bearer_tokens:
            if bearer.enabled and str(bearer.token or "").strip() == normalized_token:
                return bearer
        raise KeyError(normalized_token)

    def peers_view(self) -> list[dict[str, Any]]:
        return [peer.to_dict() for peer in self.peers]

    def operator_identities_view(self) -> list[dict[str, Any]]:
        return [operator.to_dict() for operator in self.operator_identities]

    def scoped_bearer_tokens_view(self) -> list[dict[str, Any]]:
        return [bearer.to_dict() for bearer in self.scoped_bearer_tokens]


def load_config(path: str | None) -> NodeConfig:
    if not path:
        return prepare_runtime_config(NodeConfig())

    resolved_path = str(Path(path).resolve())
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    data["peers"] = [PeerConfig(**peer) for peer in data.get("peers", [])]
    data["operator_identities"] = [
        OperatorIdentityConfig(**operator) for operator in data.get("operator_identities", [])
    ]
    data["scoped_bearer_tokens"] = [
        ScopedBearerTokenConfig(**bearer) for bearer in data.get("scoped_bearer_tokens", [])
    ]
    data["network"] = OutboundNetworkConfig(**data.get("network", {}))
    data["onchain"] = OnchainBindings(**data.get("onchain", {}))
    return prepare_runtime_config(NodeConfig(config_path=resolved_path, **data))


def _config_runtime_base_dir(config: NodeConfig) -> Path:
    if config.config_path:
        return Path(config.config_path).resolve().parent
    database_path = str(config.database_path or "").strip()
    if database_path:
        return Path(database_path).expanduser().resolve().parent
    return Path.cwd()


def prepare_runtime_config(config: NodeConfig) -> NodeConfig:
    if config.auto_bootstrap_identity:
        principal = str(config.identity_principal or "").strip() or str(config.node_id or "agentcoin-local").strip()
        runtime_base_dir = _config_runtime_base_dir(config)
        private_key_path = str(config.identity_private_key_path or "").strip()
        if private_key_path:
            resolved_private_key_path = Path(private_key_path)
            if not resolved_private_key_path.is_absolute():
                resolved_private_key_path = (runtime_base_dir / resolved_private_key_path).resolve()
        else:
            resolved_private_key_path = (runtime_base_dir / "identity" / "id_ed25519").resolve()
        identity = ensure_local_ssh_identity(
            private_key_path=str(resolved_private_key_path),
            principal=principal,
        )
        config.identity_principal = identity["principal"]
        config.identity_private_key_path = identity["private_key_path"]
        if not str(config.identity_public_key or "").strip():
            config.identity_public_key = identity["public_key"]

    if not str(config.onchain.local_did or "").strip():
        resolved_did = config.resolved_local_did
        if resolved_did:
            config.onchain.local_did = resolved_did
    return config


def _assign_optional_text(payload: dict[str, Any], key: str, value: str | None) -> None:
    normalized = str(value or "").strip()
    if normalized:
        payload[key] = normalized
    else:
        payload.pop(key, None)


def _assign_optional_list(payload: dict[str, Any], key: str, values: list[str]) -> None:
    normalized_values = [str(value or "").strip() for value in values if str(value or "").strip()]
    if normalized_values:
        payload[key] = normalized_values
    else:
        payload.pop(key, None)


def _render_config_payload(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _update_peer_identity_payload(
    payload: dict[str, Any],
    *,
    principal: str | None,
    trusted_public_keys: list[str],
    revoked_public_keys: list[str],
) -> dict[str, Any]:
    _assign_optional_text(payload, "identity_principal", principal)
    _assign_optional_text(payload, "identity_public_key", trusted_public_keys[0] if trusted_public_keys else None)
    _assign_optional_list(payload, "identity_public_keys", trusted_public_keys[1:])
    _assign_optional_list(payload, "identity_revoked_public_keys", revoked_public_keys)
    return dict(payload)


def _build_peer_identity_config_update(
    path: str,
    *,
    peer_id: str,
    principal: str | None,
    trusted_public_keys: list[str],
    revoked_public_keys: list[str],
) -> dict[str, Any]:
    config_path = Path(path)
    before_data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    peers = before_data.get("peers")
    if not isinstance(peers, list):
        raise ValueError("config file does not contain a peers list")

    after_data = copy.deepcopy(before_data)
    after_peers = after_data.get("peers")
    if not isinstance(after_peers, list):
        raise ValueError("config file does not contain a peers list")

    for index, peer_payload in enumerate(after_peers):
        if str(peer_payload.get("peer_id") or "").strip() != peer_id:
            continue

        before_peer = dict(peers[index])
        after_peer = _update_peer_identity_payload(
            peer_payload,
            principal=principal,
            trusted_public_keys=trusted_public_keys,
            revoked_public_keys=revoked_public_keys,
        )
        before_text = _render_config_payload(before_data)
        after_text = _render_config_payload(after_data)
        resolved_path = str(config_path.resolve())
        diff = "\n".join(
            difflib.unified_diff(
                before_text.splitlines(),
                after_text.splitlines(),
                fromfile=resolved_path,
                tofile=resolved_path,
                lineterm="",
            )
        )
        return {
            "config_path": resolved_path,
            "before_peer": before_peer,
            "after_peer": after_peer,
            "changed": before_text != after_text,
            "diff": diff,
            "rendered_config": after_text,
        }

    raise KeyError(peer_id)


def preview_peer_identity_config_update(
    path: str,
    *,
    peer_id: str,
    principal: str | None,
    trusted_public_keys: list[str],
    revoked_public_keys: list[str],
) -> dict[str, Any]:
    update = _build_peer_identity_config_update(
        path,
        peer_id=peer_id,
        principal=principal,
        trusted_public_keys=trusted_public_keys,
        revoked_public_keys=revoked_public_keys,
    )
    return {
        "config_path": update["config_path"],
        "before_peer": update["before_peer"],
        "after_peer": update["after_peer"],
        "changed": update["changed"],
        "diff": update["diff"],
    }


def persist_peer_identity_config(
    path: str,
    *,
    peer_id: str,
    principal: str | None,
    trusted_public_keys: list[str],
    revoked_public_keys: list[str],
) -> dict[str, Any]:
    config_path = Path(path)
    update = _build_peer_identity_config_update(
        path,
        peer_id=peer_id,
        principal=principal,
        trusted_public_keys=trusted_public_keys,
        revoked_public_keys=revoked_public_keys,
    )
    config_path.write_text(str(update["rendered_config"]), encoding="utf-8")
    return {
        "config_path": update["config_path"],
        "peer": update["after_peer"],
        "changed": update["changed"],
        "diff": update["diff"],
    }
