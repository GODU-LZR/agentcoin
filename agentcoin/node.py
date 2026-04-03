from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from agentcoin.bridges import BridgeRegistry
from agentcoin.config import NodeConfig, PeerConfig, persist_peer_identity_config, prepare_runtime_config, preview_peer_identity_config_update
from agentcoin.discovery import LocalAgentDiscovery
from agentcoin.gitops import GitWorkspace
from agentcoin.local_agents import LocalAgentManager
from agentcoin.models import TaskEnvelope, utc_after, utc_now
from agentcoin.net import OutboundTransport
from agentcoin.onchain import OnchainRuntime, as_bytes32_hex, sha256_hex
from agentcoin.receipts import (
    build_deterministic_execution_receipt,
    build_governance_action_receipt,
    build_policy_receipt,
    build_settlement_relay_receipt,
    build_subjective_review_receipt,
)
from agentcoin.runtimes import RuntimeRegistry
from agentcoin.semantics import (
    capabilities_satisfy,
    capability_match_report,
    capability_schema,
    context_document,
    semantic_examples,
    task_semantics,
)
from agentcoin.security import (
    CLIENT_REQUEST_NAMESPACE,
    IDENTITY_ALGORITHM,
    IDENTITY_SIGNATURE_FIELD,
    OPERATOR_REQUEST_NAMESPACE,
    SignatureError,
    build_operator_request_envelope,
    canonicalize_query_string,
    derive_local_did,
    operator_request_body_digest,
    sign_document,
    sign_document_with_ssh,
    sign_identity_request_headers,
    sign_operator_request_hmac_value,
    verify_document,
    verify_identity_request_signature,
    verify_document_with_ssh,
)
from agentcoin.store import NodeStore

LOG = logging.getLogger("agentcoin.node")


class AgentCoinNode:
    def __init__(self, config: NodeConfig) -> None:
        self.config = prepare_runtime_config(config)
        self.store = NodeStore(
            self.config.database_path,
            poaw_policy_version=self.config.poaw_policy_version,
            poaw_score_weights=self.config.poaw_score_weights,
        )
        self.git = GitWorkspace(self.config.git_root) if self.config.git_root else None
        self.transport = OutboundTransport(self.config.network)
        self.onchain = OnchainRuntime(self.config.onchain)
        self.bridges = BridgeRegistry(self.config.bridges)
        self.runtimes = RuntimeRegistry()
        self.discovery = LocalAgentDiscovery()
        self.local_agents = LocalAgentManager()
        self._server = ThreadingHTTPServer((self.config.host, self.config.port), self._build_handler())
        self._sync_stop = threading.Event()
        self._sync_thread = threading.Thread(target=self._sync_loop, name="agentcoin-outbox", daemon=True)
        self._settlement_relay_thread = threading.Thread(
            target=self._settlement_relay_loop,
            name="agentcoin-settlement-relay",
            daemon=True,
        )
        self._payment_relay_thread = threading.Thread(
            target=self._payment_relay_loop,
            name="agentcoin-payment-relay",
            daemon=True,
        )
        self._auth_challenges: dict[str, dict[str, Any]] = {}
        self._auth_challenge_lock = threading.Lock()
        self._identity_sessions: dict[str, dict[str, Any]] = {}
        self._identity_session_lock = threading.Lock()
        self._payment_challenges: dict[str, dict[str, Any]] = {}
        self._payment_challenge_lock = threading.Lock()
        self._payment_receipts: dict[str, dict[str, Any]] = {}
        self._payment_receipt_lock = threading.Lock()

    def local_identity_view(self) -> dict[str, Any]:
        return {
            "scheme": "ssh-ed25519" if self.config.resolved_identity_public_key and self.config.identity_principal else "",
            "principal": self.config.identity_principal,
            "public_key": self.config.resolved_identity_public_key,
            "did": self.config.resolved_local_did,
            "auto_bootstrap_identity": bool(self.config.auto_bootstrap_identity),
            "private_key_path": self.config.identity_private_key_path,
        }

    def manifest(self) -> dict[str, Any]:
        card = self.config.card.to_dict()
        return {
            "kind": "agentcoin-manifest",
            "version": "0.1",
            "generated_at": utc_now(),
            "node_id": self.config.node_id,
            "name": self.config.name,
            "description": self.config.description,
            "identity": dict(card.get("identity") or {}),
            "service": {
                "base_url": self.config.base_url,
                "host": self.config.host,
                "port": self.config.port,
                "offline_first": True,
                "secure_by_default": True,
            },
            "discovery": {
                "card_url": card.get("endpoints", {}).get("card"),
                "manifest_url": card.get("endpoints", {}).get("manifest"),
                "local_agent_discovery_url": card.get("endpoints", {}).get("local_agent_discovery"),
                "local_agent_registrations_url": card.get("endpoints", {}).get("local_agent_registrations"),
                "local_agent_register_url": card.get("endpoints", {}).get("local_agent_register"),
                "local_agent_start_url": card.get("endpoints", {}).get("local_agent_start"),
                "local_agent_stop_url": card.get("endpoints", {}).get("local_agent_stop"),
                "local_agent_acp_sessions_url": card.get("endpoints", {}).get("local_agent_acp_sessions"),
                "local_agent_acp_session_open_url": card.get("endpoints", {}).get("local_agent_acp_session_open"),
                "local_agent_acp_session_close_url": card.get("endpoints", {}).get("local_agent_acp_session_close"),
                "local_agent_acp_session_initialize_url": card.get("endpoints", {}).get("local_agent_acp_session_initialize"),
                "auth_challenge_url": card.get("endpoints", {}).get("auth_challenge"),
                "auth_verify_url": card.get("endpoints", {}).get("auth_verify"),
                "cors_allowed_origins": list(self.config.cors_allowed_origins),
                "mdns": {
                    "enabled": False,
                    "planned": True,
                },
            },
            "auth": {
                "passwordless": True,
                "shared_bearer_enabled": bool(self.config.auth_token),
                "scoped_bearer_token_count": len(self.config.scoped_bearer_tokens),
                "operator_identity_count": len(self.config.operator_identities),
                "request_signing": {
                    "supported": ["ssh-ed25519"],
                    "operator_namespace": OPERATOR_REQUEST_NAMESPACE,
                    "client_namespace": CLIENT_REQUEST_NAMESPACE,
                    "planned": ["eip-191", "eip-712", "secp256k1"],
                },
            },
            "payment": {
                "http_payment_required_status": 402,
                "enabled": bool(self.config.payment_required_workflows),
                "planned": True,
                "required_workflows": list(self.config.payment_required_workflows),
                "receipt_introspection_url": self.config.card.endpoints.get("payment_receipt_introspect"),
                "receipt_onchain_proof_url": self.config.card.endpoints.get("payment_receipt_onchain_proof"),
                "receipt_onchain_rpc_plan_url": self.config.card.endpoints.get("payment_receipt_onchain_rpc_plan"),
                "receipt_onchain_raw_bundle_url": self.config.card.endpoints.get("payment_receipt_onchain_raw_bundle"),
                "receipt_onchain_relay_url": self.config.card.endpoints.get("payment_receipt_onchain_relay"),
                "receipt_onchain_relays_url": self.config.card.endpoints.get("payment_receipt_onchain_relays"),
                "receipt_onchain_relay_latest_url": self.config.card.endpoints.get("payment_receipt_onchain_relay_latest"),
                "receipt_onchain_relay_latest_failed_url": self.config.card.endpoints.get("payment_receipt_onchain_relay_latest_failed"),
                "ops_summary_url": self.config.card.endpoints.get("payment_ops_summary"),
                "receipt_onchain_relay_queue_url": self.config.card.endpoints.get("payment_receipt_onchain_relay_queue"),
                "receipt_onchain_relay_queue_summary_url": self.config.card.endpoints.get("payment_receipt_onchain_relay_queue_summary"),
                "receipt_onchain_replay_helper_url": self.config.card.endpoints.get("payment_receipt_onchain_relay_replay_helper"),
                "receipt_kind": "agentcoin-payment-receipt",
                "proof_type": "local-operator-attestation",
                "quote": {
                    "amount_wei": str(int(self.config.payment_quote_amount_wei or 0)),
                    "asset": self.config.payment_quote_asset,
                    "ttl_seconds": int(self.config.payment_quote_ttl_seconds or 300),
                    "receipt_ttl_seconds": int(self.config.payment_receipt_ttl_seconds or 3600),
                    "recipient": self.config.onchain.local_controller_address,
                    "bounty_escrow_address": self.config.onchain.bounty_escrow_address,
                },
            },
            "protocols": {
                "native": "agentcoin/0.1",
                "bridges": list(self.config.bridges),
                "manifest_format": "json",
            },
            "capabilities": list(card.get("capabilities") or []),
            "runtimes": list(card.get("runtimes") or []),
            "runtime_capabilities": dict(card.get("runtime_capabilities") or {}),
            "routes": {
                "health": card.get("endpoints", {}).get("health"),
                "card": card.get("endpoints", {}).get("card"),
                "manifest": card.get("endpoints", {}).get("manifest"),
                "tasks": card.get("endpoints", {}).get("tasks"),
                "schema_context": card.get("endpoints", {}).get("schema_context"),
            },
            "card": card,
        }

    def _resolve_cors_origin(self, origin: str | None) -> str | None:
        allowed_origins = [str(item or "").strip() for item in self.config.cors_allowed_origins if str(item or "").strip()]
        if not allowed_origins:
            return None
        if "*" in allowed_origins:
            return "*"
        normalized_origin = str(origin or "").strip()
        if not normalized_origin:
            return None
        if normalized_origin in allowed_origins:
            return normalized_origin
        return None

    def issue_identity_auth_challenge(self) -> dict[str, Any]:
        challenge_id = str(uuid4())
        challenge = {
            "challenge_id": challenge_id,
            "nonce": str(uuid4()),
            "node_id": self.config.node_id,
            "issued_at": utc_now(),
            "expires_at": utc_after(int(self.config.identity_auth_challenge_ttl_seconds or 300)),
            "namespace": CLIENT_REQUEST_NAMESPACE,
            "local_identity": self.local_identity_view(),
        }
        with self._auth_challenge_lock:
            self._prune_auth_challenges_locked()
            self._auth_challenges[challenge_id] = challenge
        return dict(challenge)

    def _prune_auth_challenges_locked(self) -> None:
        now_value = datetime.now(timezone.utc)
        expired: list[str] = []
        for challenge_id, challenge in self._auth_challenges.items():
            expires_at = str(challenge.get("expires_at") or "").strip()
            if not expires_at:
                expired.append(challenge_id)
                continue
            try:
                expires_at_value = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError:
                expired.append(challenge_id)
                continue
            if expires_at_value <= now_value:
                expired.append(challenge_id)
        for challenge_id in expired:
            self._auth_challenges.pop(challenge_id, None)

    def get_identity_auth_challenge(self, challenge_id: str) -> dict[str, Any]:
        normalized_challenge_id = str(challenge_id or "").strip()
        if not normalized_challenge_id:
            raise ValueError("challenge_id is required")
        with self._auth_challenge_lock:
            self._prune_auth_challenges_locked()
            challenge = self._auth_challenges.get(normalized_challenge_id)
        if not challenge:
            raise ValueError("identity auth challenge not found or expired")
        return dict(challenge)

    def finalize_identity_auth_challenge(self, challenge_id: str) -> None:
        normalized_challenge_id = str(challenge_id or "").strip()
        if not normalized_challenge_id:
            raise ValueError("challenge_id is required")
        with self._auth_challenge_lock:
            self._prune_auth_challenges_locked()
            challenge = self._auth_challenges.pop(normalized_challenge_id, None)
        if not challenge:
            raise ValueError("identity auth challenge not found or expired")

    def _prune_identity_sessions_locked(self) -> None:
        now_value = datetime.now(timezone.utc)
        expired: list[str] = []
        for session_token, session in self._identity_sessions.items():
            expires_at = str(session.get("expires_at") or "").strip()
            if not expires_at:
                expired.append(session_token)
                continue
            try:
                expires_at_value = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError:
                expired.append(session_token)
                continue
            if expires_at_value <= now_value:
                expired.append(session_token)
        for session_token in expired:
            self._identity_sessions.pop(session_token, None)

    def issue_identity_auth_session(
        self,
        *,
        principal: str,
        public_key: str,
        did: str | None,
        allow_endpoints: list[str],
    ) -> dict[str, Any]:
        session_token = str(uuid4())
        session = {
            "session_token": session_token,
            "principal": principal,
            "public_key": public_key,
            "did": did,
            "issued_at": utc_now(),
            "expires_at": utc_after(int(self.config.identity_auth_session_ttl_seconds or 900)),
            "allow_endpoints": list(allow_endpoints),
            "loopback_only": True,
            "scheme": "Agentcoin-Session",
        }
        with self._identity_session_lock:
            self._prune_identity_sessions_locked()
            self._identity_sessions[session_token] = session
        return dict(session)

    def get_identity_auth_session(self, session_token: str) -> dict[str, Any] | None:
        normalized_session_token = str(session_token or "").strip()
        if not normalized_session_token:
            return None
        with self._identity_session_lock:
            self._prune_identity_sessions_locked()
            session = self._identity_sessions.get(normalized_session_token)
        return dict(session) if session else None

    def _prune_payment_challenges_locked(self) -> None:
        now_value = datetime.now(timezone.utc)
        expired: list[str] = []
        for challenge_id, challenge in self._payment_challenges.items():
            expires_at = str(challenge.get("expires_at") or "").strip()
            if not expires_at:
                expired.append(challenge_id)
                continue
            try:
                expires_at_value = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError:
                expired.append(challenge_id)
                continue
            if expires_at_value <= now_value:
                expired.append(challenge_id)
        for challenge_id in expired:
            self._payment_challenges.pop(challenge_id, None)

    def _prune_payment_receipts_locked(self) -> None:
        now_value = datetime.now(timezone.utc)
        expired: list[str] = []
        for receipt_id, receipt in self._payment_receipts.items():
            expires_at = str(receipt.get("expires_at") or "").strip()
            if not expires_at:
                expired.append(receipt_id)
                continue
            try:
                expires_at_value = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError:
                expired.append(receipt_id)
                continue
            if expires_at_value <= now_value:
                expired.append(receipt_id)
                continue
            if str(receipt.get("status") or "").strip() == "issued":
                continue
        for receipt_id in expired:
            self._payment_receipts.pop(receipt_id, None)

    @staticmethod
    def _payment_quote_digest(quote: dict[str, Any]) -> str:
        serialized = json.dumps(dict(quote or {}), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    @staticmethod
    def _payment_proof_digest(payment_proof: dict[str, Any]) -> str:
        serialized = json.dumps(
            dict(payment_proof or {}),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    def build_payment_quote(
        self,
        *,
        workflow_name: str,
        challenge_id: str,
        issued_at: str,
        expires_at: str,
        payer_hint: str | None = None,
    ) -> dict[str, Any]:
        quote = {
            "quote_id": challenge_id,
            "workflow_name": workflow_name,
            "amount_wei": str(int(self.config.payment_quote_amount_wei or 0)),
            "asset": self.config.payment_quote_asset,
            "recipient": self.config.onchain.local_controller_address,
            "bounty_escrow_address": self.config.onchain.bounty_escrow_address,
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
        if payer_hint:
            quote["payer_hint"] = payer_hint
        quote["quote_digest"] = self._payment_quote_digest(quote)
        return quote

    def issue_payment_challenge(self, *, workflow_name: str, payer_hint: str | None = None) -> dict[str, Any]:
        challenge_id = str(uuid4())
        issued_at = utc_now()
        expires_at = utc_after(int(self.config.payment_quote_ttl_seconds or 300))
        quote = self.build_payment_quote(
            workflow_name=workflow_name,
            challenge_id=challenge_id,
            issued_at=issued_at,
            expires_at=expires_at,
            payer_hint=payer_hint,
        )
        challenge = {
            "challenge_id": challenge_id,
            "workflow_name": workflow_name,
            "amount_wei": quote.get("amount_wei"),
            "asset": quote.get("asset"),
            "recipient": quote.get("recipient"),
            "bounty_escrow_address": quote.get("bounty_escrow_address"),
            "issued_at": issued_at,
            "expires_at": expires_at,
            "payer_hint": payer_hint,
            "quote": quote,
            "quote_digest": quote.get("quote_digest"),
            "status": "pending",
        }
        with self._payment_challenge_lock:
            self._prune_payment_challenges_locked()
            self._payment_challenges[challenge_id] = challenge
        return dict(challenge)

    def get_payment_challenge(self, challenge_id: str) -> dict[str, Any]:
        normalized_challenge_id = str(challenge_id or "").strip()
        if not normalized_challenge_id:
            raise ValueError("challenge_id is required")
        with self._payment_challenge_lock:
            self._prune_payment_challenges_locked()
            challenge = self._payment_challenges.get(normalized_challenge_id)
        if not challenge:
            raise ValueError("payment challenge not found or expired")
        return dict(challenge)

    def get_payment_receipt(self, receipt_id: str) -> dict[str, Any]:
        normalized_receipt_id = str(receipt_id or "").strip()
        if not normalized_receipt_id:
            raise ValueError("receipt_id is required")
        with self._payment_receipt_lock:
            self._prune_payment_receipts_locked()
            receipt = self._payment_receipts.get(normalized_receipt_id)
        if not receipt:
            raise ValueError("payment receipt not found or expired")
        return dict(receipt)

    def mark_payment_challenge_paid(self, challenge_id: str) -> dict[str, Any]:
        normalized_challenge_id = str(challenge_id or "").strip()
        if not normalized_challenge_id:
            raise ValueError("challenge_id is required")
        with self._payment_challenge_lock:
            self._prune_payment_challenges_locked()
            challenge = self._payment_challenges.get(normalized_challenge_id)
            if not challenge:
                raise ValueError("payment challenge not found or expired")
            challenge["status"] = "paid"
            self._payment_challenges[normalized_challenge_id] = challenge
        return dict(challenge)

    def issue_payment_receipt(self, *, challenge_id: str, payer: str, tx_hash: str) -> tuple[dict[str, Any], bool]:
        challenge = self.mark_payment_challenge_paid(challenge_id)
        existing_receipt_id = str(challenge.get("receipt_id") or "").strip()
        if existing_receipt_id:
            existing_receipt = self.get_payment_receipt(existing_receipt_id)
            return existing_receipt, False
        receipt_id = str(uuid4())
        quote = dict(challenge.get("quote") or {})
        payment_proof = {
            "proof_type": "local-operator-attestation",
            "payer": payer,
            "tx_hash": tx_hash,
            "challenge_id": challenge_id,
            "quote_digest": str(quote.get("quote_digest") or ""),
            "attestor_node_id": self.config.node_id,
            "attestor_did": self.config.resolved_local_did,
        }
        payment_proof_digest = self._payment_proof_digest(payment_proof)
        receipt = {
            "kind": "agentcoin-payment-receipt",
            "receipt_id": receipt_id,
            "challenge_id": challenge_id,
            "workflow_name": challenge.get("workflow_name"),
            "amount_wei": challenge.get("amount_wei"),
            "asset": challenge.get("asset"),
            "recipient": challenge.get("recipient"),
            "bounty_escrow_address": challenge.get("bounty_escrow_address"),
            "payer": payer,
            "tx_hash": tx_hash,
            "issued_at": utc_now(),
            "expires_at": utc_after(int(self.config.payment_receipt_ttl_seconds or 3600)),
            "quote": quote,
            "quote_digest": quote.get("quote_digest"),
            "payment_proof": payment_proof,
            "payment_proof_digest": payment_proof_digest,
            "status": "issued",
        }
        signed_receipt = self._sign_document(
            receipt,
            hmac_scope="payment-receipt",
            identity_namespace="agentcoin-payment",
        )
        with self._payment_receipt_lock:
            self._prune_payment_receipts_locked()
            self._payment_receipts[receipt_id] = signed_receipt
        with self._payment_challenge_lock:
            self._prune_payment_challenges_locked()
            refreshed = self._payment_challenges.get(challenge_id)
            if not refreshed:
                raise ValueError("payment challenge not found or expired")
            refreshed["receipt_id"] = receipt_id
            refreshed["status"] = "paid"
            self._payment_challenges[challenge_id] = refreshed
        return dict(signed_receipt), True

    def build_payment_attestation(
        self,
        *,
        challenge: dict[str, Any],
        receipt: dict[str, Any],
        receipt_status: dict[str, Any],
        active: bool,
        reason: str,
    ) -> dict[str, Any]:
        payment_proof = dict(receipt.get("payment_proof") or {})
        attestation = {
            "kind": "agentcoin-payment-attestation",
            "receipt_id": receipt.get("receipt_id"),
            "challenge_id": challenge.get("challenge_id"),
            "workflow_name": challenge.get("workflow_name"),
            "quote_digest": challenge.get("quote_digest"),
            "payment_proof_digest": self._payment_proof_digest(payment_proof),
            "active": bool(active),
            "status": str(receipt_status.get("status") or receipt.get("status") or ""),
            "reason": str(reason or ""),
            "consumed_task_id": receipt_status.get("consumed_task_id"),
            "attested_at": utc_now(),
            "attestor_node_id": self.config.node_id,
            "attestor_did": self.config.resolved_local_did,
        }
        return self._sign_document(
            attestation,
            hmac_scope="payment-attestation",
            identity_namespace="agentcoin-payment-attestation",
        )

    def build_payment_onchain_proof(
        self,
        receipt: dict[str, Any],
        *,
        workflow_name: str | None = None,
    ) -> dict[str, Any]:
        if not self.onchain.enabled:
            raise ValueError("onchain payment proof requires onchain bindings to be enabled")
        introspection = self.introspect_payment_receipt(receipt, workflow_name=workflow_name)
        challenge = dict(introspection.get("challenge") or {})
        attestation = dict(introspection.get("attestation") or {})
        proof = {
            "kind": "agentcoin-payment-onchain-proof",
            "workflow_name": challenge.get("workflow_name"),
            "receipt_id": receipt.get("receipt_id"),
            "challenge_id": challenge.get("challenge_id"),
            "quote_digest": introspection.get("quote_digest"),
            "payment_proof_digest": introspection.get("payment_proof_digest"),
            "attestation_digest": sha256_hex(attestation) if attestation else None,
            "active": bool(introspection.get("active")),
            "status": introspection.get("status"),
            "reason": introspection.get("reason"),
            "payment_receipt_kind": receipt.get("kind"),
            "payment_attestation_kind": attestation.get("kind"),
            "chain": {
                "chain_id": self.config.onchain.chain_id,
                "rpc_url": self.config.onchain.rpc_url,
                "explorer_base_url": self.config.onchain.explorer_base_url,
            },
            "contracts": {
                "bounty_escrow": self.config.onchain.bounty_escrow_address,
                "controller_address": self.config.onchain.local_controller_address,
                "did_registry": self.config.onchain.did_registry_address,
            },
            "projection": {
                "action": "submitPaymentProof",
                "contract": "BountyEscrow",
                "proof_type": "local-operator-attestation",
                "args": {
                    "challenge_id": challenge.get("challenge_id"),
                    "receipt_id": receipt.get("receipt_id"),
                    "quote_digest": introspection.get("quote_digest"),
                    "payment_proof_digest": introspection.get("payment_proof_digest"),
                    "attestation_digest": sha256_hex(attestation) if attestation else None,
                },
            },
            "attestation": attestation,
            "generated_at": utc_now(),
        }
        return self._sign_document(
            proof,
            hmac_scope="payment-onchain-proof",
            identity_namespace="agentcoin-payment-onchain",
        )

    def build_payment_onchain_intent(self, proof: dict[str, Any]) -> dict[str, Any]:
        if not self.onchain.enabled:
            raise ValueError("onchain payment intent requires onchain bindings to be enabled")
        contracts = dict(proof.get("contracts") or {})
        projection = dict(proof.get("projection") or {})
        args = dict(projection.get("args") or {})
        return {
            "kind": "evm-transaction-intent",
            "action": str(projection.get("action") or "submitPaymentProof"),
            "task_id": str(proof.get("receipt_id") or ""),
            "workflow_id": str(proof.get("workflow_name") or ""),
            "job_id": None,
            "job_ref": None,
            "chain_id": self.config.onchain.chain_id,
            "rpc_url": self.config.onchain.rpc_url,
            "from": self.config.onchain.local_controller_address,
            "to": contracts.get("bounty_escrow"),
            "contract": "BountyEscrow",
            "function": "submitPaymentProof",
            "signature": "submitPaymentProof(bytes32,bytes32,bytes32,bytes32,bytes32)",
            "args": {
                "challenge_id": as_bytes32_hex(str(args.get("challenge_id") or "")),
                "receipt_id": as_bytes32_hex(str(args.get("receipt_id") or "")),
                "quote_digest": as_bytes32_hex(str(args.get("quote_digest") or "")),
                "payment_proof_digest": as_bytes32_hex(str(args.get("payment_proof_digest") or "")),
                "attestation_digest": as_bytes32_hex(str(args.get("attestation_digest") or "")),
            },
            "value_wei": "0",
            "generated_at": utc_now(),
            "proof_kind": proof.get("kind"),
        }

    def build_payment_onchain_rpc_plan(
        self,
        receipt: dict[str, Any],
        *,
        workflow_name: str | None = None,
        rpc: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        proof = self.build_payment_onchain_proof(receipt, workflow_name=workflow_name)
        intent = self.build_payment_onchain_intent(proof)
        rpc_payload = self.onchain.rpc_payload_for_intent(intent, rpc=rpc or {})
        probes = self.onchain.rpc_probe_payloads(rpc_payload, rpc=rpc or {})
        plan = {
            "kind": "agentcoin-payment-onchain-rpc-plan",
            "proof": proof,
            "intent": intent,
            "rpc_payload": rpc_payload,
            "probes": probes,
            "generated_at": utc_now(),
        }
        return self._sign_document(
            plan,
            hmac_scope="payment-onchain-rpc-plan",
            identity_namespace="agentcoin-payment-onchain-rpc-plan",
        )

    def build_payment_onchain_raw_bundle(
        self,
        receipt: dict[str, Any],
        *,
        workflow_name: str | None = None,
        raw_transactions: list[dict[str, Any]],
        rpc: dict[str, Any] | None = None,
        rpc_url: str | None = None,
    ) -> dict[str, Any]:
        plan = self.build_payment_onchain_rpc_plan(receipt, workflow_name=workflow_name, rpc=rpc or {})
        items = list(raw_transactions or [])
        steps = [
            {
                "index": 0,
                "action": str(plan.get("intent", {}).get("action") or "submitPaymentProof"),
                "intent": dict(plan.get("intent") or {}),
                "rpc_payload": dict(plan.get("rpc_payload") or {}),
            }
        ]
        if len(items) != len(steps):
            raise ValueError("raw_transactions length must match payment proof steps")
        bundled_steps: list[dict[str, Any]] = []
        for step, item in zip(steps, items, strict=False):
            action = str(step.get("action") or "")
            raw_action = str(item.get("action") or action).strip()
            if raw_action and raw_action != action:
                raise ValueError(f"raw transaction action mismatch for step {action}")
            raw_tx = str(item.get("raw_transaction") or "").strip()
            if not raw_tx:
                raise ValueError(f"raw_transaction is required for step {action}")
            step_rpc_url = str(item.get("rpc_url") or "").strip() or rpc_url or str(step.get("rpc_payload", {}).get("rpc_url") or "").strip()
            raw_payload = self.onchain.raw_transaction_payload(
                raw_tx,
                rpc_url=step_rpc_url or None,
                request_id=str(item.get("request_id") or "").strip() or None,
            )
            bundled_steps.append(
                {
                    "index": step.get("index"),
                    "action": action,
                    "intent": step.get("intent"),
                    "rpc_payload": step.get("rpc_payload"),
                    "raw_transaction": raw_tx,
                    "raw_relay_payload": raw_payload,
                    "signed_by": item.get("signed_by"),
                    "signature_ref": item.get("signature_ref"),
                }
            )
        bundle = {
            "kind": "evm-payment-raw-bundle",
            "receipt_id": plan.get("proof", {}).get("receipt_id"),
            "workflow_name": plan.get("proof", {}).get("workflow_name"),
            "proof": dict(plan.get("proof") or {}),
            "plan": plan,
            "step_count": len(bundled_steps),
            "steps": bundled_steps,
            "generated_at": utc_now(),
        }
        return self._sign_document(
            bundle,
            hmac_scope="payment-onchain-raw-bundle",
            identity_namespace="agentcoin-payment-onchain-raw-bundle",
        )

    def execute_payment_onchain_relay(
        self,
        receipt: dict[str, Any],
        *,
        workflow_name: str | None = None,
        raw_transactions: list[dict[str, Any]],
        rpc: dict[str, Any] | None = None,
        rpc_url: str | None = None,
        timeout: float = 10,
        continue_on_error: bool = False,
    ) -> dict[str, Any]:
        bundle = self.build_payment_onchain_raw_bundle(
            receipt,
            workflow_name=workflow_name,
            raw_transactions=raw_transactions,
            rpc=rpc or {},
            rpc_url=rpc_url,
        )
        relayed_steps: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for step in list(bundle.get("steps") or []):
            raw_payload = dict(step.get("raw_relay_payload") or {})
            step_rpc_url = str(raw_payload.get("rpc_url") or "").strip()
            if not step_rpc_url:
                raise ValueError("rpc_url is required for payment relay")
            try:
                response = self._chain_rpc_call(step_rpc_url, raw_payload["request"], timeout=timeout)
                if "error" in response:
                    raise ValueError(f"rpc error: {response.get('error')}")
                if "result" not in response:
                    raise ValueError("rpc response missing result")
                relayed_steps.append(
                    {
                        "index": step.get("index"),
                        "action": step.get("action"),
                        "response": response,
                        "tx_hash": response.get("result"),
                        "raw_relay_payload": raw_payload,
                    }
                )
            except Exception as exc:
                failures.append(
                    {
                        "index": step.get("index"),
                        "action": step.get("action"),
                        "error": str(exc),
                        "category": self._classify_relay_failure(str(exc)),
                        "raw_relay_payload": raw_payload,
                    }
                )
                if not continue_on_error:
                    break
        relay = {
            "kind": "evm-payment-relay",
            "receipt_id": bundle.get("receipt_id"),
            "workflow_name": bundle.get("workflow_name"),
            "proof": dict(bundle.get("proof") or {}),
            "step_count": int(bundle.get("step_count") or 0),
            "submitted_steps": relayed_steps,
            "failures": failures,
            "completed_steps": len(relayed_steps),
            "stopped_on_error": bool(failures) and not continue_on_error,
            "final_status": self._relay_final_status(
                step_count=int(bundle.get("step_count") or 0),
                failures=failures,
                next_index=len(relayed_steps) if not failures else int(failures[0].get("index") or 0),
            ),
            "transport": self.config.network.transport_profile(),
            "generated_at": utc_now(),
        }
        persisted = self.store.save_payment_relay(relay)
        relay["relay_record_id"] = persisted["id"]
        return self._sign_document(
            relay,
            hmac_scope="payment-onchain-relay",
            identity_namespace="agentcoin-payment-onchain-relay",
        )

    def process_payment_relay_queue(self, *, max_items: int | None = None) -> list[dict[str, Any]]:
        processed: list[dict[str, Any]] = []
        max_in_flight = int(self.config.settlement_relay_max_in_flight or 0)
        claim_limit = max_in_flight if max_in_flight > 0 else None
        while max_items is None or len(processed) < max_items:
            item = self.store.claim_next_payment_relay_queue_item(max_in_flight=claim_limit)
            if not item:
                break

            payload = dict(item.get("payload") or {})
            try:
                receipt = dict(payload.get("payment_receipt") or {})
                if not receipt:
                    raise ValueError("payment_receipt is required")
                relay = self.execute_payment_onchain_relay(
                    receipt,
                    workflow_name=str(payload.get("workflow_name") or item.get("workflow_name") or "").strip() or None,
                    raw_transactions=list(payload.get("raw_transactions") or []),
                    rpc=dict(payload.get("rpc") or {}),
                    rpc_url=str(payload.get("rpc_url") or "").strip() or None,
                    timeout=float(payload.get("timeout_seconds") or 10),
                    continue_on_error=bool(payload.get("continue_on_error")),
                )
                last_relay_id = str(relay.get("relay_record_id") or "").strip() or None
                if relay.get("final_status") == "completed":
                    queue_item = self.store.complete_payment_relay_queue_item(item["id"], last_relay_id=last_relay_id)
                else:
                    failure_message = str(relay.get("final_status") or "payment relay incomplete")
                    if relay.get("failures"):
                        failure_message = str(relay["failures"][0].get("error") or failure_message)
                    queue_item = self.store.fail_payment_relay_queue_item(
                        item["id"],
                        error=failure_message,
                        last_relay_id=last_relay_id,
                        payload=payload,
                    )
                processed.append({"item": queue_item, "relay": relay})
            except Exception as exc:
                LOG.warning(
                    "payment relay queue execution failed queue_id=%s receipt_id=%s error=%s",
                    item.get("id"),
                    item.get("receipt_id"),
                    exc,
                )
                queue_item = self.store.fail_payment_relay_queue_item(
                    item["id"],
                    error=str(exc),
                    last_relay_id=str(item.get("last_relay_id") or "").strip() or None,
                    payload=payload,
                )
                processed.append({"item": queue_item, "error": str(exc)})
        return processed

    def auto_requeue_dead_letter_payment_relays(self, *, max_items: int | None = None) -> list[dict[str, Any]]:
        if not bool(self.config.payment_relay_auto_requeue_enabled):
            return []
        processed: list[dict[str, Any]] = []
        max_requeues = max(0, int(self.config.payment_relay_auto_requeue_max_requeues or 0))
        delay_seconds = max(0, int(self.config.payment_relay_auto_requeue_delay_seconds or 0))
        if max_requeues <= 0:
            return []
        items = self.store.list_payment_relay_queue(status="dead-letter", limit=200)
        retryable_categories = {"network", "transport", "rpc"}
        for item in items:
            if max_items is not None and len(processed) >= max_items:
                break
            payload = dict(item.get("payload") or {})
            if bool(payload.get("_auto_requeue_disabled")):
                continue
            auto_requeue_count = int(payload.get("_auto_requeue_count") or 0)
            if auto_requeue_count >= max_requeues:
                continue
            failure_category = self._classify_relay_failure(str(item.get("last_error") or ""))
            if failure_category not in retryable_categories:
                continue
            updated_payload = dict(payload)
            updated_payload["_auto_requeue_count"] = auto_requeue_count + 1
            updated_payload["_auto_requeue_reason"] = "transient-payment-relay-failure"
            queue_item = self.store.requeue_payment_relay_queue_item(
                str(item.get("id") or ""),
                delay_seconds=delay_seconds,
                payload=updated_payload,
            )
            if queue_item and str(queue_item.get("status") or "") == "queued":
                processed.append(
                    {
                        "item": queue_item,
                        "auto_requeue_count": auto_requeue_count + 1,
                        "failure_category": failure_category,
                    }
                )
        return processed

    @staticmethod
    def _merge_payment_relay_queue_payload(
        current_payload: dict[str, Any],
        overrides: dict[str, Any],
        *,
        receipt: dict[str, Any],
        workflow_name: str,
    ) -> dict[str, Any]:
        merged = dict(current_payload or {})
        merged["payment_receipt"] = dict(receipt or {})
        merged["workflow_name"] = workflow_name
        if "raw_transactions" in overrides:
            merged["raw_transactions"] = list(overrides.get("raw_transactions") or [])
        if "rpc" in overrides:
            merged["rpc"] = dict(overrides.get("rpc") or {})
        if "rpc_url" in overrides:
            merged["rpc_url"] = str(overrides.get("rpc_url") or "").strip() or None
        if "timeout_seconds" in overrides:
            merged["timeout_seconds"] = float(overrides.get("timeout_seconds") or 10)
        if "continue_on_error" in overrides:
            merged["continue_on_error"] = bool(overrides.get("continue_on_error"))
        return merged

    def build_payment_relay_replay_helper(
        self,
        *,
        receipt_id: str | None = None,
        relay_id: str | None = None,
        queue_id: str | None = None,
    ) -> dict[str, Any]:
        source: dict[str, Any] | None = None
        source_type = ""
        normalized_receipt_id = str(receipt_id or "").strip() or None
        normalized_relay_id = str(relay_id or "").strip() or None
        normalized_queue_id = str(queue_id or "").strip() or None

        if normalized_queue_id:
            source = self.store.get_payment_relay_queue_item(normalized_queue_id)
            source_type = "queue-item"
            if not source:
                raise ValueError("payment relay queue item not found")
            normalized_receipt_id = str(source.get("receipt_id") or normalized_receipt_id or "").strip() or None
        elif normalized_relay_id:
            relay_items = self.store.list_payment_relays(limit=1000)
            source = next((item for item in relay_items if str(item.get("id") or "") == normalized_relay_id), None)
            source_type = "relay-record"
            if not source:
                raise ValueError("payment relay not found")
            normalized_receipt_id = str(source.get("receipt_id") or normalized_receipt_id or "").strip() or None
        elif normalized_receipt_id:
            queue_items = self.store.list_payment_relay_queue(receipt_id=normalized_receipt_id, limit=1000)
            source = next((item for item in queue_items if str(item.get("status") or "") == "dead-letter"), None)
            if source:
                source_type = "queue-item"
            else:
                source = self.store.get_latest_failed_payment_relay(normalized_receipt_id)
                source_type = "relay-record"
            if not source:
                raise ValueError("no failed payment relay history found for receipt_id")
        else:
            raise ValueError("receipt_id, relay_id, or queue_id is required")

        receipt = self.get_payment_receipt(str(normalized_receipt_id or ""))
        workflow_name = ""
        raw_transactions: list[dict[str, Any]] = []
        rpc_url = None
        timeout_seconds = 10.0
        continue_on_error = False
        max_attempts = None
        suggested_requeue = None

        if source_type == "queue-item":
            payload = dict(source.get("payload") or {})
            workflow_name = str(source.get("workflow_name") or payload.get("workflow_name") or receipt.get("workflow_name") or "").strip()
            raw_transactions = list(payload.get("raw_transactions") or [])
            rpc_url = str(payload.get("rpc_url") or "").strip() or None
            timeout_seconds = float(payload.get("timeout_seconds") or 10)
            continue_on_error = bool(payload.get("continue_on_error"))
            max_attempts = int(source.get("max_attempts") or 0) or None
            suggested_requeue = {
                "queue_id": source.get("id"),
                "workflow_name": workflow_name,
                "payment_receipt": receipt,
                "raw_transactions": raw_transactions,
                "rpc_url": rpc_url,
                "timeout_seconds": timeout_seconds,
                "continue_on_error": continue_on_error,
                "max_attempts": max_attempts,
                "delay_seconds": 0,
            }
        else:
            workflow_name = str(source.get("workflow_name") or receipt.get("workflow_name") or "").strip()
            raw_transactions = self._rebuild_payment_raw_transactions_from_relay_record(source)
            relay_payload = dict(source.get("relay") or {})
            for item in raw_transactions:
                if not rpc_url and str(item.get("rpc_url") or "").strip():
                    rpc_url = str(item.get("rpc_url") or "").strip()
            if relay_payload.get("stopped_on_error"):
                continue_on_error = False
            suggested_requeue = None

        helper = {
            "kind": "agentcoin-payment-relay-replay-helper",
            "receipt_id": normalized_receipt_id,
            "workflow_name": workflow_name,
            "source_type": source_type,
            "source_id": source.get("id"),
            "payment_receipt": receipt,
            "direct_relay_request": {
                "workflow_name": workflow_name,
                "payment_receipt": receipt,
                "raw_transactions": raw_transactions,
                "rpc_url": rpc_url,
                "timeout_seconds": timeout_seconds,
                "continue_on_error": continue_on_error,
            },
            "queue_requeue_request": suggested_requeue,
            "generated_at": utc_now(),
        }
        return self._sign_document(
            helper,
            hmac_scope="payment-onchain-relay-replay-helper",
            identity_namespace="agentcoin-payment-onchain-relay-replay-helper",
        )

    def set_payment_relay_auto_requeue_disabled(
        self,
        queue_id: str,
        *,
        disabled: bool,
        reason: str | None = None,
    ) -> dict[str, Any]:
        item = self.store.get_payment_relay_queue_item(queue_id)
        if not item:
            raise ValueError("payment relay queue item not found")
        payload = dict(item.get("payload") or {})
        if disabled:
            payload["_auto_requeue_disabled"] = True
            payload["_auto_requeue_disabled_reason"] = str(reason or "").strip() or "manual-override"
            payload["_auto_requeue_disabled_at"] = utc_now()
        else:
            payload.pop("_auto_requeue_disabled", None)
            payload.pop("_auto_requeue_disabled_reason", None)
            payload.pop("_auto_requeue_disabled_at", None)
            payload["_auto_requeue_reenabled_at"] = utc_now()
        updated = self.store.update_payment_relay_queue_payload(queue_id, payload=payload)
        if not updated:
            raise ValueError("payment relay queue item not found")
        return updated

    def register_local_discovered_agent(self, discovered_id: str) -> dict[str, Any]:
        normalized_id = str(discovered_id or "").strip()
        if not normalized_id:
            raise ValueError("discovered_id is required")
        discovered = next((item for item in self.discovery.discover() if str(item.get("id") or "").strip() == normalized_id), None)
        if not discovered:
            raise ValueError("discovered local agent not found")
        if "acp" not in set(discovered.get("protocols") or []) and not list(
            discovered.get("agentcoin_compatibility", {}).get("launch_hint") or []
        ):
            raise ValueError("discovered local agent is not launchable")
        return self.local_agents.register_discovered_agent(discovered)

    def payment_ops_summary(self, *, receipt_id: str | None = None, relay_limit: int = 5) -> dict[str, Any]:
        normalized_receipt_id = str(receipt_id or "").strip() or None
        recent_relays = self.store.list_payment_relays(receipt_id=normalized_receipt_id, limit=max(1, int(relay_limit or 5)))
        queue_summary = self.store.summarize_payment_relay_queue(receipt_id=normalized_receipt_id)
        quote_template = {
            "amount_wei": str(int(self.config.payment_quote_amount_wei or 0)),
            "asset": self.config.payment_quote_asset,
            "ttl_seconds": int(self.config.payment_quote_ttl_seconds or 300),
            "receipt_ttl_seconds": int(self.config.payment_receipt_ttl_seconds or 3600),
            "recipient": self.config.onchain.local_controller_address,
            "bounty_escrow_address": self.config.onchain.bounty_escrow_address,
        }
        summary = {
            "kind": "agentcoin-payment-ops-summary",
            "receipt_id": normalized_receipt_id,
            "required_workflows": list(self.config.payment_required_workflows),
            "quote_template": quote_template,
            "auto_requeue_policy": {
                "enabled": bool(self.config.payment_relay_auto_requeue_enabled),
                "delay_seconds": int(self.config.payment_relay_auto_requeue_delay_seconds or 0),
                "max_requeues": int(self.config.payment_relay_auto_requeue_max_requeues or 0),
            },
            "latest_relay": self.store.get_latest_payment_relay(normalized_receipt_id),
            "latest_failed_relay": self.store.get_latest_failed_payment_relay(normalized_receipt_id),
            "queue_summary": queue_summary,
            "auto_requeue_disabled_items": list(queue_summary.get("auto_requeue_disabled_items") or []),
            "latest_auto_requeue_override": queue_summary.get("latest_auto_requeue_override"),
            "recent_relays": recent_relays,
            "stats": {
                key: value
                for key, value in self.store.stats().items()
                if str(key).startswith("payment_relay") or str(key).startswith("payment_relays")
            },
            "generated_at": utc_now(),
        }
        return self._sign_document(
            summary,
            hmac_scope="payment-ops-summary",
            identity_namespace="agentcoin-payment-ops-summary",
        )

    def consume_payment_receipt(self, receipt_id: str, *, workflow_name: str, task_id: str) -> dict[str, Any]:
        normalized_receipt_id = str(receipt_id or "").strip()
        if not normalized_receipt_id:
            raise SignatureError("payment receipt_id is required")
        with self._payment_receipt_lock:
            self._prune_payment_receipts_locked()
            receipt = self._payment_receipts.get(normalized_receipt_id)
            if not receipt:
                raise SignatureError("payment receipt not found or expired")
            if str(receipt.get("workflow_name") or "").strip() != str(workflow_name or "").strip():
                raise SignatureError("payment receipt workflow does not match request")
            if str(receipt.get("status") or "").strip() != "issued":
                raise SignatureError("payment receipt has already been consumed")
            receipt["status"] = "consumed"
            receipt["consumed_at"] = utc_now()
            receipt["consumed_task_id"] = task_id
            self._payment_receipts[normalized_receipt_id] = receipt
        return dict(receipt)

    def _verify_local_signed_document(
        self,
        payload: dict[str, Any],
        *,
        hmac_scope: str,
        identity_namespace: str,
    ) -> dict[str, Any]:
        results: dict[str, dict[str, Any]] = {}
        if self.config.signing_secret:
            results["hmac"] = verify_document(
                payload,
                secret=self.config.signing_secret,
                expected_scope=hmac_scope,
                expected_key_id=self.config.node_id,
            )
        if self.config.identity_principal and self.config.advertised_identity_public_keys:
            results["identity"] = verify_document_with_ssh(
                payload,
                public_keys=self.config.advertised_identity_public_keys,
                revoked_public_keys=self.config.advertised_identity_revoked_public_keys,
                principal=self.config.identity_principal,
                expected_namespace=identity_namespace,
            )
        if not results:
            raise SignatureError("no local signing material is available to verify payment receipt")
        collapsed = self._collapse_verification(results)
        if not isinstance(collapsed, dict):
            raise SignatureError("payment receipt verification failed")
        return collapsed

    def verify_payment_receipt(self, receipt: dict[str, Any], *, workflow_name: str) -> dict[str, Any]:
        introspection = self.introspect_payment_receipt(receipt, workflow_name=workflow_name)
        if not bool(introspection.get("active")):
            raise SignatureError(str(introspection.get("reason") or "payment receipt is not active"))
        return introspection

    def introspect_payment_receipt(
        self,
        receipt: dict[str, Any],
        *,
        workflow_name: str | None = None,
    ) -> dict[str, Any]:
        receipt_id = str(receipt.get("receipt_id") or "").strip()
        if not receipt_id:
            raise ValueError("payment_receipt.receipt_id is required")
        challenge_id = str(receipt.get("challenge_id") or "").strip()
        if not challenge_id:
            raise ValueError("payment_receipt.challenge_id is required")
        verification = self._verify_local_signed_document(
            receipt,
            hmac_scope="payment-receipt",
            identity_namespace="agentcoin-payment",
        )
        receipt_status = self.get_payment_receipt(receipt_id)
        challenge = self.get_payment_challenge(challenge_id)
        if str(receipt_status.get("challenge_id") or "").strip() != challenge_id:
            raise SignatureError("payment receipt challenge does not match issued receipt")
        quote = dict(challenge.get("quote") or {})
        quote_digest = str(quote.get("quote_digest") or "").strip()
        expected_workflow = str(workflow_name or "").strip()
        challenge_workflow = str(challenge.get("workflow_name") or "").strip()
        if expected_workflow and challenge_workflow != expected_workflow:
            raise SignatureError("payment receipt workflow does not match request")
        if str(receipt.get("workflow_name") or "").strip() != challenge_workflow:
            raise SignatureError("payment receipt workflow does not match quote")
        if str(receipt.get("quote_digest") or "").strip() != quote_digest:
            raise SignatureError("payment receipt quote digest does not match quote")
        if str(receipt.get("amount_wei") or "").strip() != str(challenge.get("amount_wei") or "").strip():
            raise SignatureError("payment receipt amount does not match quote")
        if str(receipt.get("asset") or "").strip() != str(challenge.get("asset") or "").strip():
            raise SignatureError("payment receipt asset does not match quote")
        if str(receipt.get("recipient") or "").strip() != str(challenge.get("recipient") or "").strip():
            raise SignatureError("payment receipt recipient does not match quote")
        payment_proof = dict(receipt.get("payment_proof") or {})
        payment_proof_digest = self._payment_proof_digest(payment_proof)
        if str(payment_proof.get("challenge_id") or "").strip() != challenge_id:
            raise SignatureError("payment receipt proof challenge does not match quote")
        if str(payment_proof.get("quote_digest") or "").strip() != quote_digest:
            raise SignatureError("payment receipt proof quote digest does not match quote")
        if str(receipt.get("payment_proof_digest") or "").strip() != payment_proof_digest:
            raise SignatureError("payment receipt proof digest does not match proof")
        if str(receipt.get("payer") or "").strip() != str(receipt_status.get("payer") or "").strip():
            raise SignatureError("payment receipt payer does not match issued receipt")
        if str(receipt.get("tx_hash") or "").strip() != str(receipt_status.get("tx_hash") or "").strip():
            raise SignatureError("payment receipt tx_hash does not match issued receipt")
        if str(challenge.get("status") or "").strip() != "paid":
            raise SignatureError("payment receipt challenge is not marked paid")
        receipt_state = str(receipt_status.get("status") or "").strip() or "unknown"
        active = receipt_state == "issued"
        reason = "" if active else "payment receipt has already been consumed"
        attestation = self.build_payment_attestation(
            challenge=challenge,
            receipt=receipt,
            receipt_status=receipt_status,
            active=active,
            reason=reason,
        )
        return {
            "verified": True,
            "active": active,
            "status": receipt_state,
            "reason": reason,
            "quote": quote,
            "quote_digest": quote_digest,
            "payment_proof": payment_proof,
            "payment_proof_digest": payment_proof_digest,
            "attestation": attestation,
            "challenge": challenge,
            "receipt": receipt,
            "receipt_status": receipt_status,
            "signature": verification,
        }

    def _resolve_delivery(self, target: str) -> tuple[str, str | None, str]:
        parsed = urlparse(target)
        if parsed.scheme in {"http", "https"}:
            return target, self.config.auth_token, "url"

        peer = self.config.resolve_peer(target)
        return f"{peer.url.rstrip('/')}/v1/inbox", peer.auth_token, peer.peer_id

    @staticmethod
    def _peer_target_url(peer: PeerConfig) -> str:
        return f"{peer.url.rstrip('/')}/v1/inbox"

    @staticmethod
    def _sanitize_peer(peer: PeerConfig) -> dict:
        payload = peer.to_dict()
        if payload.get("auth_token"):
            payload["auth_token"] = "***"
        if payload.get("signing_secret"):
            payload["signing_secret"] = "***"
        if payload.get("identity_public_key"):
            payload["identity_public_key"] = f"{str(payload['identity_public_key'])[:32]}..."
        if payload.get("identity_public_keys"):
            payload["identity_public_keys"] = [f"{str(value)[:32]}..." for value in payload["identity_public_keys"]]
        if payload.get("identity_revoked_public_keys"):
            payload["identity_revoked_public_keys"] = [
                f"{str(value)[:32]}..." for value in payload["identity_revoked_public_keys"]
            ]
        return payload

    @staticmethod
    def _collapse_verification(results: dict[str, dict]) -> dict | None:
        if not results:
            return None
        if len(results) == 1:
            return next(iter(results.values()))
        return {"verified": True, **results}

    @staticmethod
    def _normalize_identity_keys(*candidates: Any) -> list[str]:
        keys: list[str] = []
        for candidate in candidates:
            values = candidate if isinstance(candidate, list) else [candidate]
            for value in values:
                normalized = str(value or "").strip()
                if normalized and normalized not in keys:
                    keys.append(normalized)
        return keys

    @staticmethod
    def _ordered_unique_strings(*candidates: Any) -> list[str]:
        values: list[str] = []
        for candidate in candidates:
            items = candidate if isinstance(candidate, list) else [candidate]
            for item in items:
                normalized = str(item or "").strip()
                if normalized and normalized not in values:
                    values.append(normalized)
        return values

    @staticmethod
    def _expand_operator_scopes(*candidates: Any) -> list[str]:
        implications = {
            "bridge-admin": ["read-only"],
            "committee-member": ["read-only"],
            "settlement-admin": ["read-only"],
            "trust-admin": ["read-only"],
            "workflow-admin": ["read-only"],
        }
        pending: list[str] = []
        resolved: list[str] = []
        for candidate in candidates:
            items = candidate if isinstance(candidate, list) else [candidate]
            for item in items:
                normalized = str(item or "").strip().lower()
                if normalized and normalized not in pending and normalized not in resolved:
                    pending.append(normalized)
        while pending:
            scope = pending.pop(0)
            if scope in resolved:
                continue
            resolved.append(scope)
            for implied in implications.get(scope, []):
                if implied not in resolved and implied not in pending:
                    pending.append(implied)
        return resolved

    def _identity_trust_report(self, peer: PeerConfig, card: dict[str, Any]) -> dict[str, Any] | None:
        identity = card.get("identity")
        if not isinstance(identity, dict):
            identity = {}

        configured_principal = str(peer.identity_principal or "").strip()
        advertised_principal = str(identity.get("principal") or "").strip()
        advertised_public_keys = self._normalize_identity_keys(identity.get("public_key"), identity.get("public_keys") or [])
        advertised_revoked_public_keys = self._normalize_identity_keys(identity.get("revoked_public_keys") or [])
        advertised_active_public_keys = [
            key for key in advertised_public_keys if key not in advertised_revoked_public_keys
        ]
        configured_trusted_public_keys = peer.trusted_identity_public_keys
        configured_revoked_public_keys = peer.revoked_identity_public_keys

        if not any(
            [
                configured_principal,
                advertised_principal,
                configured_trusted_public_keys,
                configured_revoked_public_keys,
                advertised_public_keys,
                advertised_revoked_public_keys,
            ]
        ):
            return None

        principal_match = configured_principal == advertised_principal if configured_principal or advertised_principal else True
        pending_trust_public_keys = [
            key
            for key in advertised_active_public_keys
            if key not in configured_trusted_public_keys and key not in configured_revoked_public_keys
        ]
        pending_revocation_public_keys = [
            key for key in advertised_revoked_public_keys if key not in configured_revoked_public_keys
        ]
        stale_trusted_public_keys = [
            key for key in configured_trusted_public_keys if key not in advertised_active_public_keys
        ]
        local_only_revoked_public_keys = [
            key for key in configured_revoked_public_keys if key not in advertised_revoked_public_keys
        ]
        revoked_still_advertised_public_keys = [
            key for key in advertised_public_keys if key in configured_revoked_public_keys
        ]
        requires_review = bool(
            not principal_match
            or pending_trust_public_keys
            or pending_revocation_public_keys
            or stale_trusted_public_keys
            or revoked_still_advertised_public_keys
        )
        severity, severity_rank, severity_reasons = self._identity_trust_severity(
            requires_review=requires_review,
            principal_match=principal_match,
            pending_trust_public_keys=pending_trust_public_keys,
            pending_revocation_public_keys=pending_revocation_public_keys,
            stale_trusted_public_keys=stale_trusted_public_keys,
            revoked_still_advertised_public_keys=revoked_still_advertised_public_keys,
        )
        return {
            "aligned": not requires_review,
            "requires_review": requires_review,
            "severity": severity,
            "severity_rank": severity_rank,
            "severity_reasons": severity_reasons,
            "configured_principal": configured_principal,
            "advertised_principal": advertised_principal,
            "principal_match": principal_match,
            "configured_trusted_public_keys": configured_trusted_public_keys,
            "configured_revoked_public_keys": configured_revoked_public_keys,
            "advertised_public_keys": advertised_public_keys,
            "advertised_active_public_keys": advertised_active_public_keys,
            "advertised_revoked_public_keys": advertised_revoked_public_keys,
            "pending_trust_public_keys": pending_trust_public_keys,
            "pending_revocation_public_keys": pending_revocation_public_keys,
            "stale_trusted_public_keys": stale_trusted_public_keys,
            "local_only_revoked_public_keys": local_only_revoked_public_keys,
            "revoked_still_advertised_public_keys": revoked_still_advertised_public_keys,
        }

    def _peer_card_view(self, item: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item)
        try:
            peer = self.config.resolve_peer(str(item.get("peer_id") or ""))
        except KeyError:
            peer = None
        if peer:
            payload["identity_trust"] = self._identity_trust_report(peer, payload.get("card") or {})
        return payload

    @staticmethod
    def _identity_trust_severity(
        *,
        requires_review: bool,
        principal_match: bool,
        pending_trust_public_keys: list[str],
        pending_revocation_public_keys: list[str],
        stale_trusted_public_keys: list[str],
        revoked_still_advertised_public_keys: list[str],
    ) -> tuple[str, int, list[str]]:
        if not requires_review:
            return "none", 0, []

        severity_rank = 0
        reasons: list[str] = []
        if pending_trust_public_keys:
            severity_rank = max(severity_rank, 2)
            reasons.append("pending-trust-key")
        if stale_trusted_public_keys:
            severity_rank = max(severity_rank, 2)
            reasons.append("stale-trusted-key")
        if not principal_match:
            severity_rank = max(severity_rank, 3)
            reasons.append("principal-mismatch")
        if pending_revocation_public_keys:
            severity_rank = max(severity_rank, 3)
            reasons.append("pending-revocation")
        if revoked_still_advertised_public_keys:
            severity_rank = max(severity_rank, 4)
            reasons.append("revoked-key-still-advertised")

        severity = {
            0: "none",
            1: "low",
            2: "medium",
            3: "high",
            4: "critical",
        }.get(severity_rank, "unknown")
        return severity, severity_rank, reasons

    def _stored_peer_card(self, peer_id: str) -> dict[str, Any] | None:
        for item in self.store.list_peer_cards():
            if str(item.get("peer_id") or "") == peer_id:
                return item
        return None

    @staticmethod
    def _set_peer_identity_material(
        peer: PeerConfig,
        *,
        principal: str | None,
        trusted_public_keys: list[str],
        revoked_public_keys: list[str],
    ) -> None:
        filtered_revoked: list[str] = []
        for key in revoked_public_keys:
            normalized = str(key or "").strip()
            if normalized and normalized not in filtered_revoked:
                filtered_revoked.append(normalized)

        filtered_trusted: list[str] = []
        for key in trusted_public_keys:
            normalized = str(key or "").strip()
            if normalized and normalized not in filtered_revoked and normalized not in filtered_trusted:
                filtered_trusted.append(normalized)

        peer.identity_principal = str(principal or "").strip() or None
        peer.identity_public_key = filtered_trusted[0] if filtered_trusted else None
        peer.identity_public_keys = filtered_trusted[1:]
        peer.identity_revoked_public_keys = filtered_revoked

    def _candidate_peer_identity_state(
        self,
        peer: PeerConfig,
        *,
        principal: str | None,
        trusted_public_keys: list[str],
        revoked_public_keys: list[str],
    ) -> PeerConfig:
        candidate = PeerConfig(**peer.to_dict())
        self._set_peer_identity_material(
            candidate,
            principal=principal,
            trusted_public_keys=trusted_public_keys,
            revoked_public_keys=revoked_public_keys,
        )
        return candidate

    @staticmethod
    def _suggested_peer_identity_trust_actions(report: dict[str, Any] | None) -> list[str]:
        if not report:
            return []
        actions: list[str] = []
        advertised_principal = str(report.get("advertised_principal") or "").strip()
        if advertised_principal and not bool(report.get("principal_match", True)):
            actions.append("adopt-advertised-principal")
        if report.get("pending_trust_public_keys"):
            actions.append("apply-pending-trust")
        if report.get("pending_revocation_public_keys"):
            actions.append("apply-pending-revocations")
        if report.get("stale_trusted_public_keys"):
            actions.append("remove-stale-trusted")
        return actions

    def export_peer_identity_trust_reconciliation(
        self,
        *,
        peer_id: str | None = None,
        actions: list[str] | None = None,
        include_preview: bool = True,
    ) -> dict[str, Any]:
        if peer_id:
            peers = [self.config.resolve_peer(peer_id)]
        else:
            peers = list(self.config.peers)

        items: list[dict[str, Any]] = []
        for peer in peers:
            stored_card = self._stored_peer_card(peer.peer_id)
            card = dict(stored_card.get("card") or {}) if stored_card else {}
            report = self._identity_trust_report(peer, card) if stored_card else None
            suggested_actions = self._suggested_peer_identity_trust_actions(report)
            requested_actions = [str(item or "").strip().lower() for item in (actions or []) if str(item or "").strip()]
            preview_actions = requested_actions or suggested_actions
            severity = str(report.get("severity") or "unknown") if report else "unknown"
            severity_rank = int(report.get("severity_rank") or 0) if report else -1
            severity_reasons = list(report.get("severity_reasons") or []) if report else []

            item: dict[str, Any] = {
                "peer_id": peer.peer_id,
                "peer": self._sanitize_peer(peer),
                "has_peer_card": bool(stored_card),
                "card_source_url": str(stored_card.get("source_url") or "") if stored_card else "",
                "severity": severity,
                "severity_rank": severity_rank,
                "severity_reasons": severity_reasons,
                "identity_trust": report,
                "suggested_actions": suggested_actions,
                "requested_actions": requested_actions,
                "actionable": bool(suggested_actions),
                "preview": None,
            }

            if include_preview and stored_card and report and preview_actions:
                item["preview"] = self.apply_peer_identity_trust_update(
                    peer_id=peer.peer_id,
                    actions=preview_actions,
                    operator_id=None,
                    reason="peer identity trust reconciliation export preview",
                    persist_to_config=bool(self.config.config_path),
                    preview_only=True,
                    context={"export": True},
                )

            items.append(item)

        items.sort(key=lambda item: (-int(item.get("severity_rank", -1)), str(item.get("peer_id") or "")))

        return {
            "ok": True,
            "generated_at": utc_now(),
            "config_path": str(self.config.config_path or "").strip() or None,
            "include_preview": include_preview,
            "items": items,
        }

    def apply_peer_identity_trust_update(
        self,
        *,
        peer_id: str,
        actions: list[str],
        operator_id: str | None,
        reason: str,
        persist_to_config: bool = False,
        preview_only: bool = False,
        context: dict[str, Any] | None = None,
        auth_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        allowed_actions = {
            "apply-pending-trust",
            "apply-pending-revocations",
            "remove-stale-trusted",
            "adopt-advertised-principal",
        }
        normalized_actions: list[str] = []
        for action in actions:
            normalized = str(action or "").strip().lower()
            if normalized and normalized not in normalized_actions:
                normalized_actions.append(normalized)
        if not normalized_actions:
            raise ValueError("actions are required")
        invalid_actions = [action for action in normalized_actions if action not in allowed_actions]
        if invalid_actions:
            raise ValueError(f"unsupported identity trust actions: {', '.join(invalid_actions)}")

        peer = self.config.resolve_peer(peer_id)
        stored_card = self._stored_peer_card(peer_id)
        if not stored_card:
            raise ValueError("peer card not found; sync the peer first")
        card = dict(stored_card.get("card") or {})
        before_report = self._identity_trust_report(peer, card)
        if not before_report:
            raise ValueError("peer card does not expose identity trust data")

        updated_principal = str(peer.identity_principal or "").strip() or None
        updated_trusted = list(before_report.get("configured_trusted_public_keys") or [])
        updated_revoked = list(before_report.get("configured_revoked_public_keys") or [])
        applied_actions: list[str] = []
        noop_actions: list[str] = []

        for action in normalized_actions:
            if action == "adopt-advertised-principal":
                advertised_principal = str(before_report.get("advertised_principal") or "").strip() or None
                if advertised_principal and advertised_principal != updated_principal:
                    updated_principal = advertised_principal
                    applied_actions.append(action)
                else:
                    noop_actions.append(action)
                continue

            if action == "apply-pending-trust":
                pending_trust = list(before_report.get("pending_trust_public_keys") or [])
                next_trusted = self._normalize_identity_keys(updated_trusted, pending_trust)
                if next_trusted != updated_trusted:
                    updated_trusted = next_trusted
                    applied_actions.append(action)
                else:
                    noop_actions.append(action)
                continue

            if action == "apply-pending-revocations":
                pending_revocations = list(before_report.get("pending_revocation_public_keys") or [])
                next_revoked = self._normalize_identity_keys(updated_revoked, pending_revocations)
                next_trusted = [key for key in updated_trusted if key not in next_revoked]
                if next_revoked != updated_revoked or next_trusted != updated_trusted:
                    updated_revoked = next_revoked
                    updated_trusted = next_trusted
                    applied_actions.append(action)
                else:
                    noop_actions.append(action)
                continue

            if action == "remove-stale-trusted":
                stale_trusted = set(before_report.get("stale_trusted_public_keys") or [])
                next_trusted = [key for key in updated_trusted if key not in stale_trusted]
                if next_trusted != updated_trusted:
                    updated_trusted = next_trusted
                    applied_actions.append(action)
                else:
                    noop_actions.append(action)

        candidate_peer = self._candidate_peer_identity_state(
            peer,
            principal=updated_principal,
            trusted_public_keys=updated_trusted,
            revoked_public_keys=updated_revoked,
        )
        after_report = self._identity_trust_report(candidate_peer, card)

        config_preview: dict[str, Any] | None = None
        config_path = str(self.config.config_path or "").strip()
        if persist_to_config and not config_path:
            raise ValueError("config preview or persistence requires a node config file loaded via --config")
        if (persist_to_config or preview_only) and config_path:
            try:
                config_preview = preview_peer_identity_config_update(
                    config_path,
                    peer_id=peer.peer_id,
                    principal=updated_principal,
                    trusted_public_keys=updated_trusted,
                    revoked_public_keys=updated_revoked,
                )
            except KeyError as exc:
                raise ValueError(f"peer {exc.args[0]} is not present in the loaded config file") from exc

        if preview_only:
            return {
                "ok": True,
                "preview_only": True,
                "peer_id": peer.peer_id,
                "requested_actions": normalized_actions,
                "applied_actions": applied_actions,
                "noop_actions": noop_actions,
                "runtime_only": True,
                "persisted_to_config": False,
                "would_persist_to_config": bool(config_preview and config_preview.get("changed")),
                "config_path": config_preview.get("config_path") if config_preview else None,
                "before": before_report,
                "after": after_report,
                "config_preview": config_preview,
                "peer": self._sanitize_peer(candidate_peer),
            }

        persisted_config: dict[str, Any] | None = None
        if persist_to_config:
            try:
                persisted_config = persist_peer_identity_config(
                    str(self.config.config_path or "").strip(),
                    peer_id=peer.peer_id,
                    principal=updated_principal,
                    trusted_public_keys=updated_trusted,
                    revoked_public_keys=updated_revoked,
                )
            except KeyError as exc:
                raise ValueError(f"peer {exc.args[0]} is not present in the loaded config file") from exc

        self._set_peer_identity_material(
            peer,
            principal=updated_principal,
            trusted_public_keys=updated_trusted,
            revoked_public_keys=updated_revoked,
        )
        trust_mutation = {
            "requested_actions": list(normalized_actions),
            "applied_actions": list(applied_actions),
            "noop_actions": list(noop_actions),
            "runtime_only": not bool(persisted_config),
            "persisted_to_config": bool(persisted_config),
            "config_preview_changed": bool(config_preview and config_preview.get("changed")),
            "aligned_before": bool(before_report.get("aligned")),
            "aligned_after": bool(after_report.get("aligned")),
            "severity_before": before_report.get("severity"),
            "severity_after": after_report.get("severity"),
            "severity_rank_before": int(before_report.get("severity_rank") or 0),
            "severity_rank_after": int(after_report.get("severity_rank") or 0),
            "principal_changed": before_report.get("configured_principal") != after_report.get("configured_principal"),
            "trusted_keys_added": [
                key
                for key in list(after_report.get("configured_trusted_public_keys") or [])
                if key not in list(before_report.get("configured_trusted_public_keys") or [])
            ],
            "trusted_keys_removed": [
                key
                for key in list(before_report.get("configured_trusted_public_keys") or [])
                if key not in list(after_report.get("configured_trusted_public_keys") or [])
            ],
            "revoked_keys_added": [
                key
                for key in list(after_report.get("configured_revoked_public_keys") or [])
                if key not in list(before_report.get("configured_revoked_public_keys") or [])
            ],
            "revoked_keys_removed": [
                key
                for key in list(before_report.get("configured_revoked_public_keys") or [])
                if key not in list(after_report.get("configured_revoked_public_keys") or [])
            ],
        }
        receipt_payload = {
            "requested_actions": normalized_actions,
            "applied_actions": applied_actions,
            "noop_actions": noop_actions,
            "before": before_report,
            "after": after_report,
            "runtime_only": not bool(persisted_config),
            "persisted_to_config": bool(persisted_config),
            "config_path": persisted_config.get("config_path") if persisted_config else None,
            "config_preview": config_preview,
            "context": dict(context or {}),
        }
        receipt = self._governance_receipt(
            action_type="peer-identity-trust-apply",
            actor_id=peer.peer_id,
            actor_type="peer",
            operator_id=operator_id,
            reason=reason,
            payload=receipt_payload,
            reason_codes=self._ordered_unique_strings(
                before_report.get("severity_reasons") or [],
                [f"requested-{action}" for action in normalized_actions],
                [f"applied-{action}" for action in applied_actions],
                [f"noop-{action}" for action in noop_actions],
                "config-persisted" if persisted_config else "runtime-only",
            ),
            target={
                "kind": "peer-identity-trust",
                "peer_id": peer.peer_id,
                "principal": after_report.get("configured_principal"),
            },
            mutation=trust_mutation,
            auth_context=auth_context,
            evidence={
                "severity_before": before_report.get("severity"),
                "severity_after": after_report.get("severity"),
            },
            before_state=before_report,
            after_state=after_report,
        )
        action = self.store.record_governance_action(
            actor_id=peer.peer_id,
            actor_type="peer",
            action_type="peer-identity-trust-apply",
            reason=reason,
            payload={
                "operator_id": operator_id,
                "receipt": receipt,
                **receipt_payload,
            },
        )
        return {
            "ok": True,
            "peer_id": peer.peer_id,
            "requested_actions": normalized_actions,
            "applied_actions": applied_actions,
            "noop_actions": noop_actions,
            "runtime_only": not bool(persisted_config),
            "persisted_to_config": bool(persisted_config),
            "config_path": persisted_config.get("config_path") if persisted_config else None,
            "before": before_report,
            "after": after_report,
            "config_preview": config_preview,
            "peer": self._sanitize_peer(peer),
            "action": action,
        }

    def _sign_document(self, document: dict, *, hmac_scope: str, identity_namespace: str) -> dict:
        signed = dict(document)
        if self.config.signing_secret:
            signed = sign_document(signed, secret=self.config.signing_secret, key_id=self.config.node_id, scope=hmac_scope)
        if self.config.identity_private_key_path and self.config.identity_principal:
            signed = sign_document_with_ssh(
                signed,
                private_key_path=self.config.identity_private_key_path,
                principal=self.config.identity_principal,
                namespace=identity_namespace,
                public_key=self.config.resolved_identity_public_key,
            )
        return signed

    @staticmethod
    def _peer_trust_required(peer: PeerConfig | None) -> bool:
        if not peer:
            return False
        return bool(peer.signing_secret or (peer.identity_principal and peer.trusted_identity_public_keys))

    def _verify_signed_document(
        self,
        payload: dict,
        *,
        peer: PeerConfig | None,
        hmac_scope: str,
        identity_namespace: str,
        required: bool,
    ) -> dict | None:
        results: dict[str, dict] = {}
        if peer and peer.signing_secret:
            results["hmac"] = verify_document(payload, secret=peer.signing_secret, expected_scope=hmac_scope, expected_key_id=peer.peer_id)
        if peer and peer.identity_principal and peer.trusted_identity_public_keys:
            results["identity"] = verify_document_with_ssh(
                payload,
                public_keys=peer.trusted_identity_public_keys,
                revoked_public_keys=peer.revoked_identity_public_keys,
                principal=peer.identity_principal,
                expected_namespace=identity_namespace,
            )
        if required and not results:
            raise SignatureError("no trusted signature configuration is available for sender")
        return self._collapse_verification(results)

    def _verify_peer_card(self, peer: PeerConfig, card: dict) -> dict | None:
        return self._verify_signed_document(
            card,
            peer=peer,
            hmac_scope="agent-card",
            identity_namespace="agentcoin-card",
            required=self._peer_trust_required(peer),
        )

    def _verify_inbox_document(self, payload: dict) -> dict | None:
        sender = str(payload.get("sender") or "").strip()
        peer = None
        if sender:
            try:
                peer = self.config.resolve_peer(sender)
            except KeyError:
                peer = None

        requires_signature = self.config.require_signed_inbox or self._peer_trust_required(peer) or "_signature" in payload or "_identity_signature" in payload
        return self._verify_signed_document(
            payload,
            peer=peer,
            hmac_scope="task-envelope",
            identity_namespace="agentcoin-task",
            required=requires_signature,
        )

    def _verify_receipt_payload(self, peer: PeerConfig | None, payload: dict) -> dict | None:
        requires_signature = self._peer_trust_required(peer) or "_signature" in payload or "_identity_signature" in payload
        return self._verify_signed_document(
            payload,
            peer=peer,
            hmac_scope="delivery-receipt",
            identity_namespace="agentcoin-receipt",
            required=requires_signature,
        )

    def _resolve_outbox_peer(self, item: dict) -> PeerConfig | None:
        target_url = str(item.get("target_url") or "")
        for peer in self.config.peers:
            if f"{peer.url.rstrip('/')}/v1/inbox" == target_url:
                return peer

        try:
            payload = json.loads(str(item.get("payload_json") or "{}"))
        except json.JSONDecodeError:
            return None
        target_ref = (
            payload.get("payload", {}).get("_delivery", {}).get("target_ref")
            or payload.get("deliver_to")
        )
        if not target_ref:
            return None
        try:
            return self.config.resolve_peer(str(target_ref))
        except KeyError:
            return None

    def sync_peer_cards(self) -> list[dict]:
        synced: list[dict] = []
        for peer in self.config.peers:
            if not peer.enabled:
                continue
            source_url = f"{peer.url.rstrip('/')}/v1/card"
            started_at = time.monotonic()
            try:
                card = self.transport.request_json(
                    source_url,
                    method="GET",
                    headers={"Accept": "application/json"},
                    timeout=5,
                )
                latency_ms = int((time.monotonic() - started_at) * 1000)
                verification = self._verify_peer_card(peer, card)
                self.store.save_peer_card(peer.peer_id, source_url, card)
                peer_health = self.store.record_peer_health(
                    peer.peer_id,
                    source="sync",
                    success=True,
                    metadata={"latency_ms": latency_ms, "source_url": source_url},
                )
                synced.append(
                    {
                        "peer_id": peer.peer_id,
                        "status": "ok",
                        "signed": bool(verification),
                        "hmac_signed": isinstance(verification, dict) and ("scope" in verification or "hmac" in verification),
                        "identity_signed": isinstance(verification, dict) and ("namespace" in verification or "identity" in verification),
                        "identity_trust": self._identity_trust_report(peer, card),
                        "peer_health": peer_health,
                    }
                )
            except (error.URLError, TimeoutError, ValueError, json.JSONDecodeError, SignatureError) as exc:
                latency_ms = int((time.monotonic() - started_at) * 1000)
                peer_health = self.store.record_peer_health(
                    peer.peer_id,
                    source="sync",
                    success=False,
                    error_message=str(exc),
                    cooldown_seconds=self.config.dispatch_peer_cooldown_seconds,
                    blacklist_after_failures=self.config.dispatch_peer_blacklist_after_failures,
                    blacklist_seconds=self.config.dispatch_peer_blacklist_seconds,
                    metadata={"latency_ms": latency_ms, "source_url": source_url},
                )
                synced.append({"peer_id": peer.peer_id, "status": "error", "error": str(exc), "peer_health": peer_health})
        return synced

    def _supports_capabilities(self, capabilities: list[str]) -> bool:
        if not capabilities:
            return True
        return capabilities_satisfy(capabilities, self.config.capabilities)

    def _persist_task_delivery(self, task: TaskEnvelope, dispatch_mode: str | None = None) -> None:
        self.store.add_task(task)
        if not task.deliver_to:
            return
        target_url, auth_token, target_ref = self._resolve_delivery(task.deliver_to)
        task.payload.setdefault("_delivery", {})
        task.payload["_delivery"].update({"target_ref": target_ref})
        if dispatch_mode:
            task.payload["_delivery"]["dispatch_mode"] = dispatch_mode
        self.store.add_task(task)
        outbound = self._sign_document(
            task.to_dict(),
            hmac_scope="task-envelope",
            identity_namespace="agentcoin-task",
        )
        self.store.queue_outbox(task.id, target_url, auth_token, outbound, task_id=task.id)

    def _require_git(self) -> GitWorkspace:
        if not self.git:
            raise ValueError("git integration is not configured")
        return self.git

    def _task_git_proof_bundle(self, task: dict[str, Any]) -> dict[str, Any] | None:
        git_context = dict(task.get("payload", {}).get("_git") or {})
        if not git_context:
            return None
        bundle = {
            "kind": "git-proof-bundle",
            "task_id": task.get("id"),
            "workflow_id": task.get("workflow_id"),
            "role": task.get("role"),
            "branch": task.get("branch"),
            "revision": task.get("revision"),
            "git": git_context,
        }
        review_meta = dict(task.get("payload", {}).get("_review") or {})
        if review_meta:
            bundle["review"] = review_meta
        merge_policy = dict(task.get("payload", {}).get("_merge_policy") or {})
        if merge_policy:
            bundle["merge_policy"] = merge_policy
        return bundle

    def _governance_receipt(
        self,
        *,
        action_type: str,
        actor_id: str,
        actor_type: str,
        operator_id: str | None,
        reason: str,
        payload: dict[str, Any] | None = None,
        reason_codes: list[str] | None = None,
        target: dict[str, Any] | None = None,
        mutation: dict[str, Any] | None = None,
        auth_context: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        task_id: str | None = None,
        workflow_id: str | None = None,
    ) -> dict:
        document = build_governance_action_receipt(
            action_type=action_type,
            node_id=self.config.node_id,
            actor_id=actor_id,
            actor_type=actor_type,
            operator_id=operator_id,
            reason=reason,
            reason_codes=reason_codes,
            task_id=task_id,
            workflow_id=workflow_id,
            target=target,
            mutation=mutation,
            auth_context=auth_context,
            evidence=evidence,
            context=payload,
            before_state=before_state,
            after_state=after_state,
        )
        return self._sign_document(document, hmac_scope="governance-receipt", identity_namespace="agentcoin-governance")

    def _record_workflow_governance_action(
        self,
        *,
        workflow_id: str,
        action_type: str,
        operator_id: str | None,
        reason: str,
        payload: dict[str, Any] | None = None,
        reason_codes: list[str] | None = None,
        target: dict[str, Any] | None = None,
        mutation: dict[str, Any] | None = None,
        auth_context: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        stored_payload = dict(payload or {})
        receipt = self._governance_receipt(
            action_type=action_type,
            actor_id=workflow_id,
            actor_type="workflow",
            operator_id=operator_id,
            reason=reason,
            payload=stored_payload,
            reason_codes=reason_codes,
            target=target,
            mutation=mutation,
            auth_context=auth_context,
            evidence=evidence,
            before_state=before_state,
            after_state=after_state,
            task_id=task_id,
            workflow_id=workflow_id,
        )
        return self.store.record_governance_action(
            actor_id=workflow_id,
            actor_type="workflow",
            action_type=action_type,
            reason=reason,
            payload={
                **stored_payload,
                "operator_id": operator_id,
                "receipt": receipt,
            },
        )

    def _record_bridge_governance_action(
        self,
        *,
        task: dict[str, Any],
        protocol: str,
        action_type: str,
        operator_id: str | None,
        reason: str,
        payload: dict[str, Any] | None = None,
        reason_codes: list[str] | None = None,
        target: dict[str, Any] | None = None,
        mutation: dict[str, Any] | None = None,
        auth_context: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id = str(task.get("id") or "").strip()
        workflow_id = str(task.get("workflow_id") or "").strip() or None
        stored_payload = {"protocol": protocol}
        stored_payload.update(dict(payload or {}))
        receipt = self._governance_receipt(
            action_type=action_type,
            actor_id=task_id,
            actor_type="task",
            operator_id=operator_id,
            reason=reason,
            payload=stored_payload,
            reason_codes=reason_codes,
            target=target,
            mutation=mutation,
            auth_context=auth_context,
            evidence=evidence,
            before_state=before_state,
            after_state=after_state,
            task_id=task_id,
            workflow_id=workflow_id,
        )
        return self.store.record_governance_action(
            actor_id=task_id,
            actor_type="task",
            action_type=action_type,
            reason=reason,
            payload={
                **stored_payload,
                "operator_id": operator_id,
                "receipt": receipt,
            },
        )

    def _bind_onchain_context(self, task: TaskEnvelope, *, job_id: int | None = None) -> TaskEnvelope:
        if not self.onchain.enabled:
            return task
        payload = dict(task.payload)
        task_dict = task.to_dict()
        task_dict["payload"] = payload
        payload["_onchain"] = self.onchain.task_context(task_dict, job_id=job_id)
        task.payload = payload
        return task

    def _task_onchain_receipt(self, task: dict, *, result: dict[str, Any]) -> dict[str, Any] | None:
        if not self.onchain.enabled:
            return None
        if not task.get("payload", {}).get("_onchain"):
            return None
        action = "completeJob" if result.get("adapter", {}).get("status") != "rejected" else "rejectJob"
        receipt = self.onchain.result_receipt(task, result=result, action=action)
        return self._sign_document(receipt, hmac_scope="onchain-receipt", identity_namespace="agentcoin-onchain")

    def _attach_result_receipts(self, task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(result or {})
        worker_id = str(enriched.get("worker_id") or task.get("locked_by") or "").strip()
        if worker_id and not enriched.get("execution_receipt"):
            protocol = str(enriched.get("adapter", {}).get("protocol") or "agentcoin").strip() or "agentcoin"
            status = str(enriched.get("adapter", {}).get("status") or "completed").strip() or "completed"
            enriched["execution_receipt"] = build_deterministic_execution_receipt(
                task,
                worker_id=worker_id,
                protocol=protocol,
                status=status,
                outcome="ack-result",
            )

        is_review = (
            str(task.get("role") or "").strip().lower() == "reviewer"
            or str(task.get("kind") or "").strip().lower() == "review"
        )
        if is_review and worker_id and not enriched.get("review_receipt"):
            review_meta = dict(task.get("payload", {}).get("_review") or {})
            reviewer_type = str(review_meta.get("reviewer_type") or "human").strip().lower() or "human"
            score = enriched.get("score")
            if score is not None:
                try:
                    score = int(score)
                except (TypeError, ValueError):
                    score = None
            enriched["review_receipt"] = build_subjective_review_receipt(
                task,
                worker_id=worker_id,
                reviewer_type=reviewer_type,
                approved=bool(enriched.get("approved")),
                score=score,
                notes=str(enriched.get("notes")) if enriched.get("notes") is not None else None,
                target_task_id=str(review_meta.get("target_task_id") or "").strip() or None,
            )
        return enriched

    def _task_settlement_preview(self, task: dict[str, Any]) -> dict[str, Any] | None:
        if not self.onchain.enabled:
            return None
        if not task.get("payload", {}).get("_onchain"):
            return None
        audits = self.store.list_execution_audits(task_id=str(task.get("id") or ""), limit=200)
        worker_id = ""
        if audits:
            worker_id = str(audits[0].get("worker_id") or "")
        task_result = dict(task.get("result") or {})
        if not worker_id:
            worker_id = str(task_result.get("worker_id") or "")
        reputation = self.store.get_actor_reputation(worker_id, actor_type="worker") if worker_id else {}
        violations = self.store.list_policy_violations(actor_id=worker_id, limit=200) if worker_id else []
        violations = [item for item in violations if item.get("task_id") == task.get("id")]
        disputes = self.store.list_disputes(task_id=str(task.get("id") or ""), limit=200)
        try:
            preview = self.onchain.settlement_preview(
                task,
                poaw_summary=self.store.summarize_score_events(task_id=str(task.get("id") or "")),
                reputation=reputation,
                violations=violations,
                disputes=disputes,
            )
        except ValueError:
            return None
        return self._sign_document(
            preview,
            hmac_scope="onchain-settlement-preview",
            identity_namespace="agentcoin-onchain-settlement",
        )

    def _task_settlement_ledger(self, task: dict[str, Any]) -> dict[str, Any] | None:
        if not self.onchain.enabled:
            return None
        if not task.get("payload", {}).get("_onchain"):
            return None
        audits = self.store.list_execution_audits(task_id=str(task.get("id") or ""), limit=200)
        worker_id = ""
        if audits:
            worker_id = str(audits[0].get("worker_id") or "")
        task_result = dict(task.get("result") or {})
        if not worker_id:
            worker_id = str(task_result.get("worker_id") or "")
        reputation = self.store.get_actor_reputation(worker_id, actor_type="worker") if worker_id else {}
        violations = self.store.list_policy_violations(actor_id=worker_id, limit=200) if worker_id else []
        violations = [item for item in violations if item.get("task_id") == task.get("id")]
        disputes = self.store.list_disputes(task_id=str(task.get("id") or ""), limit=200)
        poaw_summary = self.store.summarize_score_events(task_id=str(task.get("id") or ""))
        try:
            preview = self.onchain.settlement_preview(
                task,
                poaw_summary=poaw_summary,
                reputation=reputation,
                violations=violations,
                disputes=disputes,
            )
            ledger = self.onchain.settlement_ledger(
                task,
                poaw_summary=poaw_summary,
                reputation=reputation,
                violations=violations,
                disputes=disputes,
                settlement_preview=preview,
            )
        except ValueError:
            return None
        return self._sign_document(
            ledger,
            hmac_scope="onchain-settlement-ledger",
            identity_namespace="agentcoin-onchain-settlement-ledger",
        )

    @staticmethod
    def _dispute_escrow_alignment(dispute: dict[str, Any]) -> tuple[str | None, str | None]:
        status = str(dispute.get("status") or "").strip().lower()
        if status in {"open", "escalated"}:
            return "challengeJob", "Challenged"
        if status == "upheld":
            return "slashJob", "Slashed"
        if status == "dismissed":
            return "completeJob", "Completed"
        return None, None

    @staticmethod
    def _dispute_bond_projected_action(dispute: dict[str, Any]) -> str | None:
        bond_status = str(dispute.get("bond_status") or "").strip().lower()
        if bond_status == "locked":
            return "lockChallengerBond"
        if bond_status == "awarded":
            return "awardChallengerBond"
        if bond_status == "slashed":
            return "slashChallengerBond"
        return None

    @staticmethod
    def _dispute_committee_projected_action(dispute: dict[str, Any]) -> str | None:
        status = str(dispute.get("status") or "").strip().lower()
        committee_quorum = int(dispute.get("committee_quorum") or 0)
        if committee_quorum <= 0 and status != "escalated":
            return None
        if status == "open":
            return "collectCommitteeVotes"
        if status in {"upheld", "dismissed"}:
            return "finalizeCommitteeResolution"
        if status == "escalated":
            return "escalateDispute"
        return None

    def _dispute_contract_alignment(self, dispute: dict[str, Any], *, task: dict[str, Any] | None = None) -> dict[str, Any]:
        task_record = task
        if task_record is None:
            task_id = str(dispute.get("task_id") or "").strip()
            task_record = self.store.get_task(task_id) if task_id else None
        onchain_context = dict(task_record.get("payload", {}).get("_onchain") or {}) if task_record else {}
        escrow_action, projected_job_status = self._dispute_escrow_alignment(dispute)
        bond_amount_wei = str(dispute.get("bond_amount_wei") or "0")
        try:
            bond_amount_int = int(bond_amount_wei)
        except (TypeError, ValueError):
            bond_amount_int = 0
        committee_quorum = int(dispute.get("committee_quorum") or 0)
        committee_future = committee_quorum > 0 or str(dispute.get("status") or "").strip().lower() == "escalated"
        bond_future = bond_amount_int > 0 or str(dispute.get("bond_status") or "").strip().lower() in {"locked", "awarded", "slashed"}
        escrow_supported_now = bool(self.onchain.enabled and onchain_context and escrow_action)

        return {
            "escrow": {
                "contract": "BountyEscrow",
                "job_id": onchain_context.get("job_id"),
                "supported_now": escrow_supported_now,
                "action": escrow_action,
                "projected_job_status": projected_job_status,
                "gap": None if escrow_supported_now or not escrow_action else "task is not attached to on-chain settlement",
            },
            "bond": {
                "amount_wei": bond_amount_wei,
                "status": str(dispute.get("bond_status") or "none"),
                "current_mode": "local-ledger" if bond_future else "not-required",
                "supported_now": not bond_future,
                "current_contract": None,
                "gap": (
                    "current StakingPool only locks worker stake; challenger bond custody remains local until ChallengeManager exists"
                    if bond_future
                    else None
                ),
                "future_contract": "ChallengeManager" if bond_future else None,
                "projected_action": self._dispute_bond_projected_action(dispute),
            },
            "committee": {
                "quorum": committee_quorum,
                "tally": dict(dispute.get("committee_tally") or {}),
                "current_mode": "offchain" if committee_future else "not-required",
                "supported_now": not committee_future,
                "current_contract": None,
                "gap": (
                    "current BountyEscrow resolves challenge outcomes but does not store committee votes or escalation"
                    if committee_future
                    else None
                ),
                "future_contract": "ChallengeManager" if committee_future else None,
                "projected_action": self._dispute_committee_projected_action(dispute),
            },
        }

    def _decorate_dispute(self, dispute: dict[str, Any], *, task: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(dispute)
        payload["contract_alignment"] = self._dispute_contract_alignment(payload, task=task)
        return payload

    @staticmethod
    def _decorate_task(task: dict[str, Any]) -> dict[str, Any]:
        payload = dict(task)
        payload["semantics"] = task_semantics(payload)
        return payload

    def _chain_rpc_call(self, rpc_url: str, request_payload: dict[str, Any], *, timeout: float = 10) -> dict[str, Any]:
        return self.transport.request_json(
            rpc_url,
            method="POST",
            payload=request_payload,
            headers={"Accept": "application/json"},
            timeout=timeout,
        )

    @staticmethod
    def _classify_relay_failure(error_message: str) -> str:
        lowered = str(error_message or "").strip().lower()
        if not lowered:
            return "unknown"
        if any(
            token in lowered
            for token in [
                "timed out",
                "timeout",
                "connection refused",
                "connection reset",
                "unreachable",
                "name or service not known",
                "failed to establish a new connection",
                "max retries exceeded",
                "actively refused",
                "winerror 10061",
            ]
        ):
            return "network"
        if "missing result" in lowered or "invalid" in lowered or "required" in lowered or "mismatch" in lowered:
            return "validation"
        if "rpc" in lowered or "jsonrpc" in lowered or "json-rpc" in lowered:
            return "rpc"
        if lowered.startswith("{") and "code" in lowered:
            return "rpc"
        return "transport"

    @staticmethod
    def _relay_final_status(*, step_count: int, failures: list[dict[str, Any]], next_index: int) -> str:
        if failures and next_index <= 0:
            return "failed"
        if failures or next_index < step_count:
            return "partial"
        return "completed"

    @staticmethod
    def _rebuild_raw_transactions_from_relay_record(relay_record: dict[str, Any]) -> list[dict[str, Any]]:
        relay = dict(relay_record.get("relay") or {})
        indexed_steps: dict[int, dict[str, Any]] = {}
        for item in list(relay.get("submitted_steps") or []):
            index = int(item.get("index") or 0)
            raw_payload = dict(item.get("raw_relay_payload") or {})
            indexed_steps[index] = {
                "action": item.get("action"),
                "raw_transaction": raw_payload.get("raw_transaction"),
                "rpc_url": raw_payload.get("rpc_url"),
            }
        for item in list(relay.get("failures") or []):
            index = int(item.get("index") or 0)
            raw_payload = dict(item.get("raw_relay_payload") or {})
            indexed_steps[index] = {
                "action": item.get("action"),
                "raw_transaction": raw_payload.get("raw_transaction"),
                "rpc_url": raw_payload.get("rpc_url"),
            }
        raw_transactions: list[dict[str, Any]] = []
        for index in sorted(indexed_steps):
            raw_transactions.append(indexed_steps[index])
        if not raw_transactions:
            raise ValueError("relay record does not contain replayable raw transactions")
        return raw_transactions

    @staticmethod
    def _rebuild_payment_raw_transactions_from_relay_record(relay_record: dict[str, Any]) -> list[dict[str, Any]]:
        relay = dict(relay_record.get("relay") or {})
        indexed_steps: dict[int, dict[str, Any]] = {}
        for item in list(relay.get("submitted_steps") or []):
            index = int(item.get("index") or 0)
            raw_payload = dict(item.get("raw_relay_payload") or {})
            indexed_steps[index] = {
                "action": item.get("action"),
                "raw_transaction": raw_payload.get("raw_transaction"),
                "rpc_url": raw_payload.get("rpc_url"),
            }
        for item in list(relay.get("failures") or []):
            index = int(item.get("index") or 0)
            raw_payload = dict(item.get("raw_relay_payload") or {})
            indexed_steps[index] = {
                "action": item.get("action"),
                "raw_transaction": raw_payload.get("raw_transaction"),
                "rpc_url": raw_payload.get("rpc_url"),
            }
        raw_transactions: list[dict[str, Any]] = []
        for index in sorted(indexed_steps):
            raw_transactions.append(indexed_steps[index])
        if not raw_transactions:
            raise ValueError("payment relay record does not contain replayable raw transactions")
        return raw_transactions

    def _execute_settlement_relay(
        self,
        *,
        task_id: str,
        raw_transactions: list[dict[str, Any]],
        rpc_options: dict[str, Any] | None = None,
        rpc_url: str | None = None,
        timeout: float = 10,
        continue_on_error: bool = False,
        resume_from_index: int = 0,
        retry_count: int = 0,
        resumed_from_relay_id: str | None = None,
    ) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        if not task:
            raise ValueError("task not found")
        settlement = self._task_settlement_preview(task)
        if not settlement:
            raise ValueError("task is not bound to onchain settlement")
        settlement_ledger = self._task_settlement_ledger(task)
        plan = self.onchain.settlement_rpc_plan(
            task,
            settlement_preview=settlement,
            settlement_ledger=settlement_ledger,
            rpc=rpc_options or {},
        )
        bundle = self.onchain.settlement_raw_bundle(
            plan,
            raw_transactions=list(raw_transactions or []),
            rpc_url=rpc_url,
        )
        relayed_steps: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for step in bundle["steps"]:
            step_index = int(step.get("index") or 0)
            if step_index < resume_from_index:
                continue
            raw_payload = dict(step.get("raw_relay_payload") or {})
            step_rpc_url = str(raw_payload.get("rpc_url") or "").strip()
            if not step_rpc_url:
                raise ValueError("rpc_url is required for settlement relay")
            try:
                response = self._chain_rpc_call(step_rpc_url, raw_payload["request"], timeout=timeout)
                if "error" in response:
                    raise ValueError(f"rpc error: {response.get('error')}")
                if "result" not in response:
                    raise ValueError("rpc response missing result")
                relayed_steps.append(
                    {
                        "index": step_index,
                        "action": step.get("action"),
                        "response": response,
                        "tx_hash": response.get("result"),
                        "raw_relay_payload": raw_payload,
                    }
                )
            except Exception as exc:
                failure = {
                    "index": step_index,
                    "action": step.get("action"),
                    "error": str(exc),
                    "category": self._classify_relay_failure(str(exc)),
                    "raw_relay_payload": raw_payload,
                }
                failures.append(failure)
                if not continue_on_error:
                    break
        last_successful_index = max(
            (
                int(item["index"])
                if item.get("index") is not None
                else -1
                for item in relayed_steps
            ),
            default=-1,
        )
        next_index = failures[0]["index"] if failures else max(resume_from_index, last_successful_index + 1)
        relay = {
            "kind": "evm-settlement-relay",
            "task_id": task_id,
            "recommended_resolution": bundle.get("recommended_resolution"),
            "settlement_ledger": dict(bundle.get("settlement_ledger") or {}),
            "step_count": bundle.get("step_count"),
            "resume_from_index": resume_from_index,
            "resumed": resume_from_index > 0,
            "resumed_from_relay_id": resumed_from_relay_id,
            "retry_count": retry_count,
            "submitted_steps": relayed_steps,
            "failures": failures,
            "completed_steps": len(relayed_steps),
            "last_successful_index": last_successful_index,
            "stopped_on_error": bool(failures) and not continue_on_error,
            "next_index": next_index,
            "failure_category": failures[0]["category"] if failures else None,
            "final_status": self._relay_final_status(
                step_count=int(bundle.get("step_count") or 0),
                failures=failures,
                next_index=int(next_index),
            ),
            "transport": self.config.network.transport_profile(),
            "generated_at": utc_now(),
        }
        persisted = self.store.save_settlement_relay(
            relay,
            retry_count=retry_count,
            resumed_from_relay_id=resumed_from_relay_id,
        )
        relay["relay_record_id"] = persisted["id"]
        return relay

    def process_settlement_relay_queue(self, *, max_items: int | None = None) -> list[dict[str, Any]]:
        processed: list[dict[str, Any]] = []
        max_in_flight = int(self.config.settlement_relay_max_in_flight or 0)
        claim_limit = max_in_flight if max_in_flight > 0 else None
        while max_items is None or len(processed) < max_items:
            item = self.store.claim_next_settlement_relay_queue_item(max_in_flight=claim_limit)
            if not item:
                break

            payload = dict(item.get("payload") or {})
            try:
                relay = self._execute_settlement_relay(
                    task_id=str(payload.get("task_id") or item.get("task_id") or "").strip(),
                    raw_transactions=list(payload.get("raw_transactions") or []),
                    rpc_options=dict(payload.get("rpc") or {}),
                    rpc_url=str(payload.get("rpc_url") or "").strip() or None,
                    timeout=float(payload.get("timeout_seconds") or 10),
                    continue_on_error=bool(payload.get("continue_on_error")),
                    resume_from_index=int(payload.get("resume_from_index") or 0),
                    retry_count=max(0, int(item.get("attempts") or 1) - 1),
                    resumed_from_relay_id=str(item.get("last_relay_id") or "").strip() or None,
                )
                last_relay_id = str(relay.get("relay_record_id") or "").strip() or None
                if relay.get("final_status") == "completed":
                    queue_item = self.store.complete_settlement_relay_queue_item(item["id"], last_relay_id=last_relay_id)
                else:
                    updated_payload = dict(payload)
                    updated_payload["resume_from_index"] = int(
                        relay.get("next_index") or updated_payload.get("resume_from_index") or 0
                    )
                    failure_message = str(relay.get("final_status") or "settlement relay incomplete")
                    if relay.get("failures"):
                        failure_message = str(relay["failures"][0].get("error") or failure_message)
                    queue_item = self.store.fail_settlement_relay_queue_item(
                        item["id"],
                        error=failure_message,
                        last_relay_id=last_relay_id,
                        payload=updated_payload,
                    )
                processed.append({"item": queue_item, "relay": relay})
            except Exception as exc:
                LOG.warning(
                    "settlement relay queue execution failed queue_id=%s task_id=%s error=%s",
                    item.get("id"),
                    item.get("task_id"),
                    exc,
                )
                queue_item = self.store.fail_settlement_relay_queue_item(
                    item["id"],
                    error=str(exc),
                    last_relay_id=str(item.get("last_relay_id") or "").strip() or None,
                    payload=payload,
                )
                processed.append({"item": queue_item, "error": str(exc)})
        return processed

    @staticmethod
    def _merge_settlement_relay_queue_payload(
        current_payload: dict[str, Any],
        overrides: dict[str, Any],
        *,
        task_id: str,
    ) -> dict[str, Any]:
        merged = dict(current_payload or {})
        merged["task_id"] = task_id
        if "raw_transactions" in overrides:
            merged["raw_transactions"] = list(overrides.get("raw_transactions") or [])
        if "rpc" in overrides:
            merged["rpc"] = dict(overrides.get("rpc") or {})
        if "rpc_url" in overrides:
            merged["rpc_url"] = str(overrides.get("rpc_url") or "").strip() or None
        if "timeout_seconds" in overrides:
            merged["timeout_seconds"] = float(overrides.get("timeout_seconds") or 10)
        if "continue_on_error" in overrides:
            merged["continue_on_error"] = bool(overrides.get("continue_on_error"))
        if "resume_from_index" in overrides:
            merged["resume_from_index"] = int(overrides.get("resume_from_index") or 0)
        return merged

    @staticmethod
    def _receipt_reconciliation_status(receipt: dict[str, Any] | None) -> str:
        if not isinstance(receipt, dict):
            return "unknown"
        status = receipt.get("status")
        if isinstance(status, str):
            lowered = status.strip().lower()
            if lowered in {"0x1", "0x01", "1"}:
                return "confirmed"
            if lowered in {"0x0", "0x00", "0"}:
                return "reverted"
            return "unknown"
        if status == 1:
            return "confirmed"
        if status == 0:
            return "reverted"
        return "unknown"

    @staticmethod
    def _is_final_settlement_resolution(action: str) -> bool:
        return str(action or "").strip() in {"completeJob", "rejectJob", "slashJob"}

    def _auto_finalize_reconciled_workflow(self, relay_record: dict[str, Any]) -> dict[str, Any]:
        task_id = str(relay_record.get("task_id") or "").strip()
        task = self.store.get_task(task_id) if task_id else None
        if not task:
            return {"attempted": False, "reason": "task-not-found"}

        workflow_id = str(task.get("workflow_id") or "").strip()
        if not workflow_id:
            return {"attempted": False, "reason": "workflow-missing", "task_id": task_id}

        recommended_resolution = str(relay_record.get("recommended_resolution") or "").strip()
        if not self._is_final_settlement_resolution(recommended_resolution):
            return {
                "attempted": False,
                "reason": "resolution-not-final",
                "task_id": task_id,
                "workflow_id": workflow_id,
                "recommended_resolution": recommended_resolution,
            }

        finalized = self.store.finalize_workflow(workflow_id)
        return {
            "attempted": True,
            "task_id": task_id,
            "workflow_id": workflow_id,
            "recommended_resolution": recommended_resolution,
            "finalized": bool(finalized.get("ok")),
            "result": finalized,
        }

    def reconcile_settlement_relay(
        self,
        relay_id: str,
        *,
        rpc_url: str | None = None,
        timeout: float = 10,
    ) -> dict[str, Any]:
        relay_record = self.store.get_settlement_relay(relay_id)
        if not relay_record:
            raise ValueError("settlement relay not found")

        relay_payload = dict(relay_record.get("relay") or {})
        submitted_steps = list(relay_payload.get("submitted_steps") or [])
        checked_at = utc_now()
        chain_receipts: list[dict[str, Any]] = []

        for step in submitted_steps:
            step_index = int(step.get("index") or 0)
            raw_payload = dict(step.get("raw_relay_payload") or {})
            step_rpc_url = str(rpc_url or raw_payload.get("rpc_url") or "").strip() or None
            tx_hash = str(step.get("tx_hash") or step.get("response", {}).get("result") or "").strip() or None
            receipt_payload: dict[str, Any] | None = None
            error_message: str | None = None

            if tx_hash and step_rpc_url:
                request_payload = self.onchain.rpc_request(
                    "eth_getTransactionReceipt",
                    [tx_hash],
                    request_id=f"agentcoin-{relay_id}-{step_index}-receipt",
                )
                try:
                    response = self._chain_rpc_call(step_rpc_url, request_payload, timeout=timeout)
                    if "error" in response:
                        error_message = f"rpc error: {response.get('error')}"
                    else:
                        raw_receipt = response.get("result")
                        if isinstance(raw_receipt, dict):
                            receipt_payload = raw_receipt
                except Exception as exc:
                    error_message = str(exc)
            elif not tx_hash:
                error_message = "tx_hash is missing"
            else:
                error_message = "rpc_url is missing"

            chain_receipts.append(
                {
                    "index": step_index,
                    "action": step.get("action"),
                    "tx_hash": tx_hash,
                    "rpc_url": step_rpc_url,
                    "status": self._receipt_reconciliation_status(receipt_payload),
                    "receipt": receipt_payload,
                    "error": error_message,
                    "checked_at": checked_at,
                }
            )

        if chain_receipts and all(item.get("status") == "confirmed" for item in chain_receipts):
            reconciliation_status = "confirmed"
        elif any(item.get("status") == "reverted" for item in chain_receipts):
            reconciliation_status = "reverted"
        else:
            reconciliation_status = "unknown"
        confirmed_at = checked_at if reconciliation_status == "confirmed" and chain_receipts else None

        updated = self.store.update_settlement_relay_reconciliation(
            relay_id,
            reconciliation_status=reconciliation_status,
            reconciliation_checked_at=checked_at,
            confirmed_at=confirmed_at,
            chain_receipts=chain_receipts,
        )
        if not updated:
            raise ValueError("settlement relay not found")
        updated = dict(updated)
        updated["auto_finalize"] = self._auto_finalize_reconciled_workflow(updated)
        return updated

    def _task_settlement_reconciliation(self, task_id: str) -> dict[str, Any] | None:
        latest = self.store.get_latest_settlement_relay(task_id)
        if not latest:
            return None
        return {
            "relay_id": latest.get("id"),
            "task_id": latest.get("task_id"),
            "status": latest.get("reconciliation_status") or "unknown",
            "checked_at": latest.get("reconciliation_checked_at"),
            "confirmed_at": latest.get("confirmed_at"),
            "receipt_count": len(latest.get("chain_receipts") or []),
        }

    def _peer_dispatch_snapshot(self, peer_id: str) -> dict[str, Any]:
        peer = self.config.resolve_peer(peer_id)
        target_url = self._peer_target_url(peer)
        health = self.store.get_peer_health(peer_id)
        backlog = self.store.outbox_backlog(target_url)
        success_rate = float(health.get("success_rate") or 1.0)
        consecutive_failures = int(health.get("consecutive_failures") or 0)
        weak_network_penalty = min(
            int(self.config.dispatch_weak_network_penalty_cap),
            int(round((1.0 - success_rate) * 80)) + (consecutive_failures * 15),
        )
        relay_backlog_penalty = min(
            int(self.config.dispatch_backlog_penalty_cap),
            (int(backlog.get("pending") or 0) * 15)
            + (int(backlog.get("retrying") or 0) * 20)
            + (int(backlog.get("dead_letter") or 0) * 30),
        )
        blocked = dict(health.get("dispatch_blocked") or {})
        score_breakdown = {
            "recent_success_rate": int(round(success_rate * 100)),
            "weak_network_penalty": -weak_network_penalty,
            "relay_backlog_penalty": -relay_backlog_penalty,
            "cooldown_penalty": -200 if blocked.get("cooldown") else 0,
            "blacklist_penalty": -1000 if blocked.get("blacklisted") else 0,
        }
        return {
            "peer": peer,
            "target_url": target_url,
            "health": health,
            "backlog": backlog,
            "dispatchable": not any(bool(value) for value in blocked.values()),
            "score_breakdown": score_breakdown,
        }

    def dispatch_candidates(
        self,
        required_capabilities: list[str],
        prefer_local: bool = False,
        *,
        include_blocked: bool = False,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        if self._supports_capabilities(required_capabilities):
            local_report = capability_match_report(required_capabilities, self.config.capabilities)
            local_score = 100 + (len(local_report["exact_matches"]) * 100) + (len(local_report["expanded_matches"]) * 10)
            if prefer_local:
                local_score += 500
            candidates.append(
                {
                    "target_type": "local",
                    "target_ref": self.config.node_id,
                    "capabilities": list(self.config.capabilities),
                    "match": local_report,
                    "reputation": {"score": 100, "quarantined": False},
                    "dispatchable": True,
                    "health": {
                        "peer_id": self.config.node_id,
                        "success_rate": 1.0,
                        "dispatch_blocked": {"cooldown": False, "blacklisted": False},
                    },
                    "backlog": {"pending": 0, "retrying": 0, "dead_letter": 0, "delivered": 0, "total": 0},
                    "score_breakdown": {
                        "capability_exact": len(local_report["exact_matches"]) * 100,
                        "capability_semantic": len(local_report["expanded_matches"]) * 10,
                        "local_bias": 500 if prefer_local else 100,
                    },
                    "score": local_score,
                }
            )

        for peer_card in self.store.list_peer_cards():
            peer_id = peer_card["peer_id"]
            card = peer_card["card"]
            capabilities = list(card.get("capabilities", []))
            report = capability_match_report(required_capabilities, capabilities)
            if not report["satisfied"]:
                continue
            reputation = self.store.get_actor_reputation(peer_id, actor_type="peer")
            reputation_score = int(reputation.get("score", 100))
            snapshot = self._peer_dispatch_snapshot(peer_id)
            if not snapshot["dispatchable"] and not include_blocked:
                continue
            score_breakdown = {
                "capability_exact": len(report["exact_matches"]) * 100,
                "capability_semantic": len(report["expanded_matches"]) * 10,
                "reputation": reputation_score,
                **snapshot["score_breakdown"],
            }
            candidate_score = sum(int(value) for value in score_breakdown.values())
            candidates.append(
                {
                    "target_type": "peer",
                    "target_ref": peer_id,
                    "capabilities": capabilities,
                    "match": report,
                    "reputation": reputation,
                    "dispatchable": snapshot["dispatchable"],
                    "health": snapshot["health"],
                    "backlog": snapshot["backlog"],
                    "score_breakdown": score_breakdown,
                    "score": candidate_score,
                }
            )

        return sorted(
            candidates,
            key=lambda item: (
                bool(item.get("dispatchable", True)),
                item["score"],
                item["target_type"] == "local",
                item["target_ref"],
            ),
            reverse=True,
        )

    @staticmethod
    def _runtime_requirement(task: TaskEnvelope) -> str | None:
        runtime = str(task.payload.get("_runtime", {}).get("runtime") or "").strip()
        return runtime or None

    @staticmethod
    def _runtime_requirement_details(task: TaskEnvelope) -> dict[str, Any]:
        runtime_payload = dict(task.payload.get("_runtime") or {})
        runtime_name = str(runtime_payload.get("runtime") or "").strip() or None
        structured_output = runtime_payload.get("structured_output")
        response_format = runtime_payload.get("response_format")
        structured_output_required = bool(structured_output or response_format)
        json_schema_required = False
        schema_name = None
        if isinstance(structured_output, dict) and structured_output:
            json_schema_required = bool(structured_output.get("schema"))
            schema_name = str(structured_output.get("name") or "").strip() or None
        elif isinstance(response_format, dict) and response_format:
            response_format_type = str(response_format.get("type") or "").strip().lower()
            if response_format_type in {"json_schema", "json_object"}:
                structured_output_required = True
            if response_format_type == "json_schema":
                json_schema_required = True
                schema_name = str(dict(response_format.get("json_schema") or {}).get("name") or "").strip() or None
        return {
            "runtime": runtime_name,
            "structured_output_required": structured_output_required,
            "json_schema_required": json_schema_required,
            "schema_name": schema_name,
        }

    @staticmethod
    def _bridge_requirement(task: TaskEnvelope) -> str | None:
        protocol = str(task.payload.get("_bridge", {}).get("protocol") or "").strip().lower()
        return protocol or None

    def _task_dispatch_requirements(self, task: TaskEnvelope) -> dict[str, Any]:
        runtime_requirements = self._runtime_requirement_details(task)
        return {
            "required_capabilities": list(task.required_capabilities),
            "runtime": runtime_requirements["runtime"],
            "runtime_requirements": runtime_requirements,
            "structured_output_required": runtime_requirements["structured_output_required"],
            "json_schema_required": runtime_requirements["json_schema_required"],
            "bridge_protocol": self._bridge_requirement(task),
        }

    @staticmethod
    def _supports_runtime(runtime_name: str | None, available_runtimes: list[str]) -> bool:
        if not runtime_name:
            return True
        return runtime_name in {str(item).strip() for item in available_runtimes if str(item).strip()}

    @staticmethod
    def _supports_bridge_protocol(protocol_name: str | None, available_protocols: list[str]) -> bool:
        if not protocol_name:
            return True
        normalized = {str(item).strip().lower() for item in available_protocols if str(item).strip()}
        return protocol_name in normalized or f"{protocol_name}-bridge/0.1" in normalized

    @staticmethod
    def _runtime_capability_map(card: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        capabilities = dict((card or {}).get("runtime_capabilities") or {})
        normalized: dict[str, dict[str, Any]] = {}
        for runtime_name, descriptor in capabilities.items():
            key = str(runtime_name or "").strip().lower()
            if key:
                normalized[key] = dict(descriptor or {})
        return normalized

    def _runtime_match(self, task: TaskEnvelope, available_runtimes: list[str], runtime_capabilities: dict[str, dict[str, Any]]) -> dict[str, Any]:
        requirements = self._task_dispatch_requirements(task)["runtime_requirements"]
        runtime_name = requirements["runtime"]
        runtime_ok = self._supports_runtime(runtime_name, available_runtimes)
        descriptor = dict(runtime_capabilities.get(str(runtime_name or "").strip().lower()) or {})
        structured_supported = bool(descriptor.get("supports_structured_output"))
        json_schema_supported = bool(descriptor.get("supports_json_schema"))
        structured_required = bool(requirements["structured_output_required"])
        json_schema_required = bool(requirements["json_schema_required"])
        return {
            "required": runtime_name,
            "supported": runtime_ok and (not structured_required or structured_supported) and (not json_schema_required or json_schema_supported),
            "descriptor": descriptor,
            "structured_output_required": structured_required,
            "structured_output_supported": structured_supported,
            "json_schema_required": json_schema_required,
            "json_schema_supported": json_schema_supported,
            "schema_name": requirements["schema_name"],
        }

    def dispatch_candidates_for_task(
        self,
        task: TaskEnvelope,
        prefer_local: bool = False,
        *,
        include_blocked: bool = False,
    ) -> list[dict[str, Any]]:
        runtime_requirements = self._task_dispatch_requirements(task)["runtime_requirements"]
        runtime_requirement = runtime_requirements["runtime"]
        bridge_requirement = self._bridge_requirement(task)
        candidates: list[dict[str, Any]] = []

        local_report = capability_match_report(task.required_capabilities, self.config.capabilities)
        local_runtime_capabilities = self._runtime_capability_map(self.config.card.to_dict())
        local_runtime_match = self._runtime_match(task, self.config.runtimes, local_runtime_capabilities)
        local_bridge_ok = self._supports_bridge_protocol(bridge_requirement, self.config.card.protocols)
        if local_report["satisfied"] and local_runtime_match["supported"] and local_bridge_ok:
            score_breakdown = {
                "capability_exact": len(local_report["exact_matches"]) * 100,
                "capability_semantic": len(local_report["expanded_matches"]) * 10,
                "local_bias": 600 if prefer_local else 100,
                "runtime_bonus": 150 if runtime_requirement else 0,
                "structured_output_bonus": 80 if runtime_requirements["structured_output_required"] else 0,
                "bridge_bonus": 120 if bridge_requirement else 0,
            }
            candidates.append(
                {
                    "target_type": "local",
                    "target_ref": self.config.node_id,
                    "capabilities": list(self.config.capabilities),
                    "runtimes": list(self.config.runtimes),
                    "runtime_capabilities": local_runtime_capabilities,
                    "protocols": list(self.config.card.protocols),
                    "match": local_report,
                    "runtime_match": local_runtime_match,
                    "bridge_match": {"required": bridge_requirement, "supported": local_bridge_ok},
                    "reputation": {"score": 100, "quarantined": False},
                    "dispatchable": True,
                    "health": {
                        "peer_id": self.config.node_id,
                        "success_rate": 1.0,
                        "dispatch_blocked": {"cooldown": False, "blacklisted": False},
                    },
                    "backlog": {"pending": 0, "retrying": 0, "dead_letter": 0, "delivered": 0, "total": 0},
                    "score_breakdown": score_breakdown,
                    "score": sum(score_breakdown.values()),
                }
            )

        for peer_card in self.store.list_peer_cards():
            peer_id = peer_card["peer_id"]
            card = peer_card["card"]
            capabilities = list(card.get("capabilities", []))
            protocols = list(card.get("protocols", []))
            runtimes = list(card.get("runtimes", []))
            runtime_capabilities = self._runtime_capability_map(card)
            report = capability_match_report(task.required_capabilities, capabilities)
            runtime_match = self._runtime_match(task, runtimes, runtime_capabilities)
            bridge_ok = self._supports_bridge_protocol(bridge_requirement, protocols)
            if not report["satisfied"] or not runtime_match["supported"] or not bridge_ok:
                continue
            reputation = self.store.get_actor_reputation(peer_id, actor_type="peer")
            reputation_score = int(reputation.get("score", 100))
            snapshot = self._peer_dispatch_snapshot(peer_id)
            if not snapshot["dispatchable"] and not include_blocked:
                continue
            score_breakdown = {
                "capability_exact": len(report["exact_matches"]) * 100,
                "capability_semantic": len(report["expanded_matches"]) * 10,
                "reputation": reputation_score,
                "runtime_priority": 150 if runtime_requirement else 0,
                "structured_output_priority": 80 if runtime_requirements["structured_output_required"] else 0,
                "bridge_priority": 120 if bridge_requirement else 0,
                **snapshot["score_breakdown"],
            }
            candidates.append(
                {
                    "target_type": "peer",
                    "target_ref": peer_id,
                    "capabilities": capabilities,
                    "runtimes": runtimes,
                    "runtime_capabilities": runtime_capabilities,
                    "protocols": protocols,
                    "match": report,
                    "runtime_match": runtime_match,
                    "bridge_match": {"required": bridge_requirement, "supported": bridge_ok},
                    "reputation": reputation,
                    "dispatchable": snapshot["dispatchable"],
                    "health": snapshot["health"],
                    "backlog": snapshot["backlog"],
                    "score_breakdown": score_breakdown,
                    "score": sum(score_breakdown.values()),
                }
            )

        return sorted(
            candidates,
            key=lambda item: (
                bool(item.get("dispatchable", True)),
                item["score"],
                item["target_type"] == "local",
                item["target_ref"],
            ),
            reverse=True,
        )

    def select_dispatch_target(self, required_capabilities: list[str], prefer_local: bool = False) -> dict[str, str] | None:
        candidates = self.dispatch_candidates(required_capabilities, prefer_local=prefer_local, include_blocked=False)
        if not candidates:
            return None
        return {"target_type": candidates[0]["target_type"], "target_ref": candidates[0]["target_ref"]}

    def select_dispatch_target_for_task(self, task: TaskEnvelope, prefer_local: bool = False) -> dict[str, str] | None:
        candidates = self.dispatch_candidates_for_task(task, prefer_local=prefer_local, include_blocked=False)
        if not candidates:
            return None
        return {"target_type": candidates[0]["target_type"], "target_ref": candidates[0]["target_ref"]}

    @staticmethod
    def _normalize_task(task: TaskEnvelope, config: NodeConfig) -> TaskEnvelope:
        if not task.workflow_id:
            task.workflow_id = task.id
        if not task.branch:
            task.branch = "main"
        if task.revision <= 0:
            task.revision = 1
        if not task.commit_message:
            task.commit_message = f"{task.kind} on {task.branch}@r{task.revision}"
        if task.max_attempts <= 0:
            task.max_attempts = config.task_retry_limit
        if task.retry_backoff_seconds <= 0:
            task.retry_backoff_seconds = config.task_retry_backoff_seconds
        if not task.available_at:
            task.available_at = task.created_at
        if task.deliver_to:
            task.delivery_status = task.delivery_status or "remote-pending"
        else:
            task.delivery_status = "local"
        return task

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        node = self
        operator_endpoint_policies: dict[str, dict[str, Any]] = {
            "GET /v1/disputes": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/reputation": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/poaw/events": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/poaw/summary": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/violations": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/quarantines": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/governance-actions": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/audits": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/peer-health": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/git/status": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/git/diff": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/outbox": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/outbox/dead-letter": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/onchain/settlement-preview": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/onchain/settlement-ledger": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/onchain/settlement-relays": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/onchain/settlement-relay-queue": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/onchain/settlement-relays/latest": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/tasks/replay-inspect": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "GET /v1/tasks/dispatch/preview": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "/v1/tasks/dispatch/evaluate": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "/v1/peers/identity-trust/export": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "/v1/onchain/intents/build": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "/v1/onchain/rpc-payload": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "/v1/onchain/rpc-plan": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "/v1/onchain/settlement-rpc-plan": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "/v1/onchain/settlement-raw-bundle": {
                "policy_tier": "read-only",
                "policy_level": 1,
                "required_scopes": ["read-only"],
            },
            "/v1/tasks/requeue": {
                "policy_tier": "local-admin",
                "policy_level": 1,
                "required_scopes": ["local-admin"],
            },
            "/v1/outbox/flush": {
                "policy_tier": "local-admin",
                "policy_level": 1,
                "required_scopes": ["local-admin"],
            },
            "/v1/outbox/requeue": {
                "policy_tier": "local-admin",
                "policy_level": 1,
                "required_scopes": ["local-admin"],
            },
            "/v1/git/branch": {
                "policy_tier": "local-admin",
                "policy_level": 1,
                "required_scopes": ["local-admin"],
            },
            "/v1/git/task-context": {
                "policy_tier": "local-admin",
                "policy_level": 1,
                "required_scopes": ["local-admin"],
            },
            "/v1/workflows/fanout": {
                "policy_tier": "workflow-admin",
                "policy_level": 2,
                "required_scopes": ["workflow-admin"],
            },
            "/v1/workflows/review-gate": {
                "policy_tier": "workflow-admin",
                "policy_level": 2,
                "required_scopes": ["workflow-admin"],
            },
            "/v1/workflows/merge": {
                "policy_tier": "workflow-admin",
                "policy_level": 2,
                "required_scopes": ["workflow-admin"],
            },
            "/v1/workflows/finalize": {
                "policy_tier": "workflow-admin",
                "policy_level": 2,
                "required_scopes": ["workflow-admin"],
            },
            "/v1/bridges/import": {
                "policy_tier": "bridge-admin",
                "policy_level": 2,
                "required_scopes": ["bridge-admin"],
            },
            "/v1/bridges/export": {
                "policy_tier": "bridge-admin",
                "policy_level": 2,
                "required_scopes": ["bridge-admin"],
            },
            "/v1/peers/identity-trust/apply": {
                "policy_tier": "trust-admin",
                "policy_level": 3,
                "required_scopes": ["trust-admin"],
            },
            "/v1/quarantines": {
                "policy_tier": "trust-admin",
                "policy_level": 3,
                "required_scopes": ["trust-admin"],
            },
            "/v1/quarantines/release": {
                "policy_tier": "trust-admin",
                "policy_level": 3,
                "required_scopes": ["trust-admin"],
            },
            "/v1/disputes": {
                "policy_tier": "trust-admin",
                "policy_level": 3,
                "required_scopes": ["trust-admin"],
            },
            "/v1/disputes/resolve": {
                "policy_tier": "trust-admin",
                "policy_level": 3,
                "required_scopes": ["trust-admin"],
            },
            "/v1/disputes/vote": {
                "policy_tier": "committee-member",
                "policy_level": 3,
                "required_scopes": ["committee-member", "trust-admin"],
            },
            "/v1/onchain/rpc/send-raw": {
                "policy_tier": "settlement-admin",
                "policy_level": 4,
                "required_scopes": ["settlement-admin"],
            },
            "/v1/onchain/settlement-relay": {
                "policy_tier": "settlement-admin",
                "policy_level": 4,
                "required_scopes": ["settlement-admin"],
            },
            "/v1/onchain/settlement-relay-queue": {
                "policy_tier": "settlement-admin",
                "policy_level": 4,
                "required_scopes": ["settlement-admin"],
            },
            "/v1/onchain/settlement-relay-queue/pause": {
                "policy_tier": "settlement-admin",
                "policy_level": 4,
                "required_scopes": ["settlement-admin"],
            },
            "/v1/onchain/settlement-relay-queue/resume": {
                "policy_tier": "settlement-admin",
                "policy_level": 4,
                "required_scopes": ["settlement-admin"],
            },
            "/v1/onchain/settlement-relay-queue/requeue": {
                "policy_tier": "settlement-admin",
                "policy_level": 4,
                "required_scopes": ["settlement-admin"],
            },
            "/v1/onchain/settlement-relay-queue/cancel": {
                "policy_tier": "settlement-admin",
                "policy_level": 4,
                "required_scopes": ["settlement-admin"],
            },
            "/v1/onchain/settlement-relay-queue/delete": {
                "policy_tier": "settlement-admin",
                "policy_level": 4,
                "required_scopes": ["settlement-admin"],
            },
            "/v1/onchain/settlement-relays/reconcile": {
                "policy_tier": "settlement-admin",
                "policy_level": 4,
                "required_scopes": ["settlement-admin"],
            },
            "/v1/onchain/settlement-relays/replay": {
                "policy_tier": "settlement-admin",
                "policy_level": 4,
                "required_scopes": ["settlement-admin"],
            },
        }

        class Handler(BaseHTTPRequestHandler):
            server_version = "AgentCoin/0.1"

            def _send_cors_headers(self) -> None:
                allowed_origin = node._resolve_cors_origin(self.headers.get("Origin"))
                if not allowed_origin:
                    return
                self.send_header("Access-Control-Allow-Origin", allowed_origin)
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Authorization, Content-Type, X-Agentcoin-Key-Id, X-Agentcoin-Timestamp, "
                    "X-Agentcoin-Nonce, X-Agentcoin-Body-Digest, X-Agentcoin-Signature, "
                    "X-Agentcoin-Principal, X-Agentcoin-Public-Key, X-Agentcoin-Identity-Namespace, "
                    "X-Agentcoin-Identity-Signature",
                )
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Max-Age", "600")
                self.send_header("Vary", "Origin")

            def _json_response(self, status: int, payload: dict, *, extra_headers: dict[str, str] | None = None) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self._send_cors_headers()
                for key, value in dict(extra_headers or {}).items():
                    self.send_header(str(key), str(value))
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:
                self.send_response(HTTPStatus.NO_CONTENT)
                self._send_cors_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _read_body_bytes(self) -> bytes:
                if hasattr(self, "_cached_body_bytes"):
                    return self._cached_body_bytes
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length <= 0:
                    self._cached_body_bytes = b""
                    return self._cached_body_bytes
                if length > node.config.max_body_bytes:
                    raise ValueError("request body too large")
                self._cached_body_bytes = self.rfile.read(length)
                return self._cached_body_bytes

            def _read_json(self) -> dict:
                if hasattr(self, "_cached_json_payload"):
                    return self._cached_json_payload
                raw = self._read_body_bytes()
                if not raw:
                    self._cached_json_payload = {}
                    return self._cached_json_payload
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("json body must be an object")
                self._cached_json_payload = payload
                return self._cached_json_payload

            def _request_remote(self) -> tuple[str | None, int | None]:
                remote_address = None
                remote_port = None
                if isinstance(self.client_address, tuple) and self.client_address:
                    remote_address = str(self.client_address[0] or "").strip() or None
                    if len(self.client_address) > 1:
                        try:
                            remote_port = int(self.client_address[1])
                        except (TypeError, ValueError):
                            remote_port = None
                return remote_address, remote_port

            def _is_loopback_request(self) -> bool:
                remote_address, _ = self._request_remote()
                if not remote_address:
                    return False
                try:
                    return ipaddress.ip_address(remote_address).is_loopback
                except ValueError:
                    return remote_address.lower() == "localhost"

            def _identity_request_verification(self, *, principal: str, public_key: str) -> dict[str, Any]:
                timestamp = str(self.headers.get("X-Agentcoin-Timestamp") or "").strip()
                nonce = str(self.headers.get("X-Agentcoin-Nonce") or "").strip()
                body_digest = str(self.headers.get("X-Agentcoin-Body-Digest") or "").strip()
                signature = str(self.headers.get("X-Agentcoin-Identity-Signature") or "").strip()
                namespace = str(self.headers.get("X-Agentcoin-Identity-Namespace") or CLIENT_REQUEST_NAMESPACE).strip()
                if not timestamp or not nonce or not body_digest or not signature:
                    raise SignatureError("identity request signature headers are incomplete")
                try:
                    timestamp_value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise SignatureError("invalid identity request timestamp") from exc
                now_value = datetime.now(timezone.utc)
                skew = abs((now_value - timestamp_value).total_seconds())
                if skew > float(node.config.operator_auth_timestamp_skew_seconds or 300):
                    raise SignatureError("identity request timestamp is outside the allowed skew window")
                parsed_request = urlparse(self.path)
                return verify_identity_request_signature(
                    method=self.command,
                    path=parsed_request.path,
                    query=parsed_request.query,
                    body=self._read_body_bytes(),
                    principal=principal,
                    public_key=public_key,
                    timestamp=timestamp,
                    nonce=nonce,
                    body_digest=body_digest,
                    signature_b64=signature,
                    namespace=namespace,
                )

            def _require_client_identity(
                self,
                *,
                allow_endpoints: set[str],
            ) -> dict[str, Any] | None:
                parsed_request = urlparse(self.path)
                if parsed_request.path not in allow_endpoints:
                    self._json_response(HTTPStatus.FORBIDDEN, {"error": "client identity auth is not allowed for this endpoint"})
                    return None
                if not self._is_loopback_request():
                    self._json_response(HTTPStatus.FORBIDDEN, {"error": "client identity auth is restricted to loopback access"})
                    return None

                principal = str(self.headers.get("X-Agentcoin-Principal") or "").strip()
                public_key = str(self.headers.get("X-Agentcoin-Public-Key") or "").strip()
                if not principal or not public_key:
                    self._json_response(HTTPStatus.UNAUTHORIZED, {"error": "client identity principal and public key are required"})
                    return None

                timestamp = str(self.headers.get("X-Agentcoin-Timestamp") or "").strip()
                nonce = str(self.headers.get("X-Agentcoin-Nonce") or "").strip()
                if not timestamp or not nonce:
                    self._json_response(HTTPStatus.UNAUTHORIZED, {"error": "client identity timestamp and nonce are required"})
                    return None

                try:
                    verification = self._identity_request_verification(
                        principal=principal,
                        public_key=public_key,
                    )
                except SignatureError as exc:
                    self._json_response(HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
                    return None

                did = derive_local_did(public_key=public_key)
                nonce_key = str(did or principal or "client-identity")
                if not node.store.reserve_operator_auth_nonce(
                    key_id=f"client:{nonce_key}",
                    nonce=nonce,
                    ttl_seconds=int(node.config.operator_auth_nonce_ttl_seconds or 900),
                ):
                    self._json_response(HTTPStatus.UNAUTHORIZED, {"error": "client identity nonce has already been used"})
                    return None

                return {
                    "mode": "client-signed-ssh",
                    "principal": principal,
                    "public_key": public_key,
                    "did": did,
                    "verification": verification,
                    "loopback_only": True,
                }

            def _resolve_client_identity_session(self) -> dict[str, Any] | None:
                header = str(self.headers.get("Authorization") or "").strip()
                prefix = "Agentcoin-Session "
                if not header.startswith(prefix):
                    return None
                session_token = str(header[len(prefix):] or "").strip()
                if not session_token:
                    return None
                return node.get_identity_auth_session(session_token)

            def _require_local_client_or_auth(
                self,
                *,
                allow_endpoints: set[str],
                policy_tier: str | None = None,
                policy_level: int = 0,
                required_scopes: list[str] | None = None,
            ) -> dict[str, Any] | None:
                session = self._resolve_client_identity_session()
                if session is not None:
                    parsed_request = urlparse(self.path)
                    if not self._is_loopback_request():
                        self._json_response(HTTPStatus.FORBIDDEN, {"error": "client identity session is restricted to loopback access"})
                        return None
                    allowed_session_endpoints = set(session.get("allow_endpoints") or [])
                    if parsed_request.path not in allow_endpoints or parsed_request.path not in allowed_session_endpoints:
                        self._json_response(HTTPStatus.FORBIDDEN, {"error": "client identity session is not allowed for this endpoint"})
                        return None
                    return {
                        "mode": "client-session",
                        "principal": session.get("principal"),
                        "public_key": session.get("public_key"),
                        "did": session.get("did"),
                        "session_token": session.get("session_token"),
                        "expires_at": session.get("expires_at"),
                        "loopback_only": True,
                    }
                if self._resolve_bearer_auth() is not None:
                    return self._require_auth(
                        policy_tier=policy_tier,
                        policy_level=policy_level,
                        required_scopes=required_scopes,
                    )
                return self._require_client_identity(allow_endpoints=allow_endpoints)

            def _resolve_bearer_auth(self) -> dict[str, Any] | None:
                header = self.headers.get("Authorization", "")
                if not header.startswith("Bearer "):
                    return None
                token = str(header[7:] or "").strip()
                if not token:
                    return None

                configured = node.config.auth_token.strip()
                if configured and token == configured:
                    return {
                        "kind": "shared",
                        "token_id": "shared-bearer",
                        "granted_scopes": ["local-admin"],
                        "source_restrictions": [],
                    }
                try:
                    scoped = node.config.resolve_scoped_bearer_token(token)
                except KeyError:
                    return None
                return {
                    "kind": "scoped",
                    "token_id": scoped.token_id,
                    "granted_scopes": node._expand_operator_scopes(scoped.normalized_scopes),
                    "source_restrictions": scoped.normalized_source_restrictions,
                }

            def _has_valid_bearer_auth(self) -> bool:
                return self._resolve_bearer_auth() is not None

            @staticmethod
            def _parse_signed_timestamp(value: str) -> datetime:
                normalized = str(value or "").strip()
                if not normalized:
                    raise ValueError("timestamp is required")
                if normalized.endswith("Z"):
                    normalized = normalized[:-1] + "+00:00"
                parsed = datetime.fromisoformat(normalized)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)

            def _auth_context(
                self,
                *,
                policy_tier: str,
                policy_level: int = 0,
                required_scopes: list[str] | None = None,
                mode: str | None = None,
                key_id: str | None = None,
                operator_id: str | None = None,
                granted_scopes: list[str] | None = None,
                nonce: str | None = None,
                timestamp: str | None = None,
                body_digest: str | None = None,
                verification: dict[str, Any] | None = None,
                downgraded: bool = False,
            ) -> dict[str, Any]:
                remote_address, remote_port = self._request_remote()
                return {
                    "mode": mode or ("bearer-token" if node.config.auth_token.strip() else "none"),
                    "endpoint": urlparse(self.path).path,
                    "policy_tier": policy_tier,
                    "policy_level": int(policy_level or 0),
                    "required_scopes": list(required_scopes or []),
                    "granted_scopes": list(granted_scopes or []),
                    "key_id": key_id,
                    "operator_id": operator_id,
                    "nonce": nonce,
                    "timestamp": timestamp,
                    "body_digest": body_digest,
                    "verification": dict(verification or {}),
                    "downgraded": bool(downgraded),
                    "remote_address": remote_address,
                    "remote_port": remote_port,
                }

            def _policy_receipt(
                self,
                *,
                decision: str,
                reason: str,
                auth_context: dict[str, Any],
                reason_code: str,
                extra: dict[str, Any] | None = None,
            ) -> dict[str, Any]:
                receipt = build_policy_receipt(
                    protocol="agentcoin/operator-auth",
                    decision=decision,
                    reason=reason,
                    mode=str(auth_context.get("mode") or "operator-auth"),
                    endpoint=auth_context.get("endpoint"),
                    policy_tier=auth_context.get("policy_tier"),
                    policy_level=auth_context.get("policy_level"),
                    required_scopes=list(auth_context.get("required_scopes") or []),
                    granted_scopes=list(auth_context.get("granted_scopes") or []),
                    key_id=auth_context.get("key_id"),
                    operator_id=auth_context.get("operator_id"),
                    nonce=auth_context.get("nonce"),
                    timestamp=auth_context.get("timestamp"),
                    body_digest=auth_context.get("body_digest"),
                    remote_address=auth_context.get("remote_address"),
                    remote_port=auth_context.get("remote_port"),
                    reason_code=reason_code,
                    downgraded=bool(auth_context.get("downgraded")),
                    verification=dict(auth_context.get("verification") or {}),
                    **dict(extra or {}),
                )
                return node._sign_document(
                    receipt,
                    hmac_scope="operator-auth-receipt",
                    identity_namespace="agentcoin-operator-auth",
                )

            def _record_operator_auth_audit(
                self,
                *,
                decision: str,
                reason: str,
                auth_context: dict[str, Any],
                policy_receipt: dict[str, Any] | None = None,
                payload: dict[str, Any] | None = None,
            ) -> dict[str, Any]:
                audit_payload = {
                    "required_scopes": list(auth_context.get("required_scopes") or []),
                    "granted_scopes": list(auth_context.get("granted_scopes") or []),
                    "operator_id": auth_context.get("operator_id"),
                    "downgraded": bool(auth_context.get("downgraded")),
                    "verification": dict(auth_context.get("verification") or {}),
                }
                audit_payload.update(dict(payload or {}))
                if policy_receipt is not None:
                    audit_payload["policy_receipt"] = policy_receipt
                return node.store.record_operator_auth_audit(
                    endpoint=str(auth_context.get("endpoint") or urlparse(self.path).path),
                    method=self.command,
                    policy_tier=str(auth_context.get("policy_tier") or ""),
                    policy_level=int(auth_context.get("policy_level") or 0),
                    decision=decision,
                    reason=reason,
                    key_id=str(auth_context.get("key_id") or "").strip() or None,
                    auth_mode=str(auth_context.get("mode") or "none"),
                    remote_address=str(auth_context.get("remote_address") or "").strip() or None,
                    remote_port=auth_context.get("remote_port"),
                    nonce=str(auth_context.get("nonce") or "").strip() or None,
                    body_digest=str(auth_context.get("body_digest") or "").strip() or None,
                    payload=audit_payload,
                )

            def _deny_operator_auth(
                self,
                *,
                status: HTTPStatus,
                error_message: str,
                reason: str,
                reason_code: str,
                auth_context: dict[str, Any],
                payload: dict[str, Any] | None = None,
            ) -> None:
                policy_receipt = self._policy_receipt(
                    decision="rejected",
                    reason=reason,
                    auth_context=auth_context,
                    reason_code=reason_code,
                    extra=payload,
                )
                self._record_operator_auth_audit(
                    decision="denied",
                    reason=reason,
                    auth_context=auth_context,
                    policy_receipt=policy_receipt,
                    payload=payload,
                )
                self._json_response(status, {"error": error_message, "policy_receipt": policy_receipt})

            def _effective_operator_id(
                self,
                requested_operator_id: str | None,
                auth_context: dict[str, Any] | None,
            ) -> str | None:
                normalized_requested = str(requested_operator_id or "").strip() or None
                if not auth_context:
                    return normalized_requested
                authenticated_operator_id = str(auth_context.get("operator_id") or "").strip() or None
                if authenticated_operator_id:
                    if normalized_requested and normalized_requested != authenticated_operator_id:
                        auth_context["requested_operator_id"] = normalized_requested
                    return authenticated_operator_id
                if normalized_requested:
                    auth_context.setdefault("requested_operator_id", normalized_requested)
                return normalized_requested

            def _require_auth(
                self,
                *,
                policy_tier: str | None = None,
                policy_level: int = 0,
                required_scopes: list[str] | None = None,
            ) -> dict[str, Any] | None:
                session_header = str(self.headers.get("Authorization") or "").strip().startswith("Agentcoin-Session ")
                if session_header:
                    session = self._resolve_client_identity_session()
                    if session is None:
                        self._json_response(HTTPStatus.UNAUTHORIZED, {"error": "client identity session is missing or expired"})
                        return None
                    if not self._is_loopback_request():
                        self._json_response(HTTPStatus.FORBIDDEN, {"error": "client identity session is restricted to loopback access"})
                        return None
                    self._json_response(HTTPStatus.FORBIDDEN, {"error": "client identity session is not allowed for this endpoint"})
                    return None
                normalized_scopes = [
                    str(scope or "").strip().lower()
                    for scope in list(required_scopes or [])
                    if str(scope or "").strip()
                ]
                if not policy_tier:
                    parsed_request = urlparse(self.path)
                    default_policy = operator_endpoint_policies.get(f"{self.command} {parsed_request.path}")
                    if not default_policy:
                        default_policy = operator_endpoint_policies.get(parsed_request.path)
                    if default_policy:
                        return self._require_auth(
                            policy_tier=str(default_policy.get("policy_tier") or ""),
                            policy_level=int(default_policy.get("policy_level") or 0),
                            required_scopes=list(default_policy.get("required_scopes") or []),
                        )
                    bearer_auth = self._resolve_bearer_auth()
                    if bearer_auth and str(bearer_auth.get("kind") or "") == "shared":
                        return self._auth_context(policy_tier="local-admin")
                    if bearer_auth and str(bearer_auth.get("kind") or "") == "scoped":
                        auth_context = self._auth_context(
                            policy_tier="local-admin",
                            mode="scoped-bearer",
                            key_id=str(bearer_auth.get("token_id") or "").strip() or None,
                            operator_id=str(bearer_auth.get("token_id") or "").strip() or None,
                            granted_scopes=list(bearer_auth.get("granted_scopes") or []),
                            downgraded=True,
                        )
                        self._deny_operator_auth(
                            status=HTTPStatus.FORBIDDEN,
                            error_message="scoped bearer token cannot access endpoint without explicit scope policy",
                            reason="scoped bearer token requires an explicit endpoint scope policy",
                            reason_code="scoped-bearer-policy-missing",
                            auth_context=auth_context,
                        )
                        return None
                    self._json_response(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return None

                base_auth_context = self._auth_context(
                    policy_tier=policy_tier,
                    policy_level=policy_level,
                    required_scopes=normalized_scopes,
                )
                bearer_auth = self._resolve_bearer_auth()
                if not bearer_auth:
                    self._deny_operator_auth(
                        status=HTTPStatus.UNAUTHORIZED,
                        error_message="unauthorized",
                        reason="shared bearer token is missing or invalid",
                        reason_code="bearer-unauthorized",
                        auth_context=base_auth_context,
                    )
                    return None

                key_id = str(self.headers.get("X-Agentcoin-Key-Id") or "").strip()
                timestamp = str(self.headers.get("X-Agentcoin-Timestamp") or "").strip()
                nonce = str(self.headers.get("X-Agentcoin-Nonce") or "").strip()
                header_body_digest = str(self.headers.get("X-Agentcoin-Body-Digest") or "").strip()
                signature = str(self.headers.get("X-Agentcoin-Signature") or "").strip()
                signed_headers_present = any([key_id, timestamp, nonce, header_body_digest, signature])
                operators_configured = bool(node.config.operator_identities)

                if signed_headers_present:
                    auth_context = self._auth_context(
                        policy_tier=policy_tier,
                        policy_level=policy_level,
                        required_scopes=normalized_scopes,
                        mode="signed-request",
                        key_id=key_id or None,
                        operator_id=key_id or None,
                        nonce=nonce or None,
                        timestamp=timestamp or None,
                        body_digest=header_body_digest or None,
                    )
                    missing_headers = [
                        header_name
                        for header_name, value in {
                            "X-Agentcoin-Key-Id": key_id,
                            "X-Agentcoin-Timestamp": timestamp,
                            "X-Agentcoin-Nonce": nonce,
                            "X-Agentcoin-Body-Digest": header_body_digest,
                            "X-Agentcoin-Signature": signature,
                        }.items()
                        if not value
                    ]
                    if missing_headers:
                        self._deny_operator_auth(
                            status=HTTPStatus.UNAUTHORIZED,
                            error_message="operator request signature is incomplete",
                            reason="signed operator request is incomplete",
                            reason_code="signed-request-incomplete",
                            auth_context=auth_context,
                            payload={"missing_headers": missing_headers},
                        )
                        return None
                    if not operators_configured:
                        self._deny_operator_auth(
                            status=HTTPStatus.UNAUTHORIZED,
                            error_message="signed operator request cannot be verified",
                            reason="operator signing keys are not configured",
                            reason_code="signed-request-unconfigured",
                            auth_context=auth_context,
                        )
                        return None
                    try:
                        operator = node.config.resolve_operator_identity(key_id)
                    except KeyError:
                        self._deny_operator_auth(
                            status=HTTPStatus.UNAUTHORIZED,
                            error_message="unknown operator key",
                            reason="operator key_id is not configured",
                            reason_code="unknown-key-id",
                            auth_context=auth_context,
                        )
                        return None

                    granted_scopes = node._expand_operator_scopes(operator.normalized_scopes)
                    auth_context = self._auth_context(
                        policy_tier=policy_tier,
                        policy_level=policy_level,
                        required_scopes=normalized_scopes,
                        mode="signed-request",
                        key_id=operator.key_id,
                        operator_id=operator.key_id,
                        granted_scopes=granted_scopes,
                        nonce=nonce,
                        timestamp=timestamp,
                        body_digest=header_body_digest,
                    )
                    if not operator.supports_signed_requests:
                        self._deny_operator_auth(
                            status=HTTPStatus.FORBIDDEN,
                            error_message="operator key cannot authorize requests",
                            reason="configured operator identity does not expose verification material",
                            reason_code="operator-verification-unavailable",
                            auth_context=auth_context,
                        )
                        return None

                    computed_body_digest = operator_request_body_digest(self._read_body_bytes())
                    auth_context["body_digest"] = computed_body_digest
                    if computed_body_digest != header_body_digest:
                        self._deny_operator_auth(
                            status=HTTPStatus.UNAUTHORIZED,
                            error_message="operator request body digest mismatch",
                            reason="operator request body digest does not match payload",
                            reason_code="body-digest-mismatch",
                            auth_context=auth_context,
                            payload={"expected_body_digest": computed_body_digest},
                        )
                        return None

                    try:
                        parsed_timestamp = self._parse_signed_timestamp(timestamp)
                    except ValueError:
                        self._deny_operator_auth(
                            status=HTTPStatus.UNAUTHORIZED,
                            error_message="invalid operator request timestamp",
                            reason="operator request timestamp is invalid",
                            reason_code="invalid-timestamp",
                            auth_context=auth_context,
                        )
                        return None

                    skew_seconds = abs((datetime.now(timezone.utc) - parsed_timestamp).total_seconds())
                    if skew_seconds > int(node.config.operator_auth_timestamp_skew_seconds or 300):
                        self._deny_operator_auth(
                            status=HTTPStatus.UNAUTHORIZED,
                            error_message="operator request timestamp outside allowed skew",
                            reason="operator request timestamp exceeded skew window",
                            reason_code="timestamp-skew",
                            auth_context=auth_context,
                            payload={
                                "observed_skew_seconds": int(skew_seconds),
                                "allowed_skew_seconds": int(node.config.operator_auth_timestamp_skew_seconds or 300),
                            },
                        )
                        return None

                    parsed_request = urlparse(self.path)
                    envelope = build_operator_request_envelope(
                        method=self.command,
                        path=parsed_request.path,
                        canonical_query=canonicalize_query_string(parsed_request.query),
                        timestamp=timestamp,
                        nonce=nonce,
                        body_digest=header_body_digest,
                        key_id=operator.key_id,
                    )

                    verification: dict[str, Any]
                    if str(operator.shared_secret or "").strip():
                        expected_signature = sign_operator_request_hmac_value(
                            envelope,
                            shared_secret=str(operator.shared_secret or "").strip(),
                        )
                        if signature != expected_signature:
                            self._deny_operator_auth(
                                status=HTTPStatus.UNAUTHORIZED,
                                error_message="operator request signature verification failed",
                                reason="operator request signature did not verify",
                                reason_code="signature-verification-failed",
                                auth_context=auth_context,
                            )
                            return None
                        verification = {"verified": True, "alg": "hmac-sha256", "key_id": operator.key_id}
                        auth_context["mode"] = "signed-hmac"
                    else:
                        try:
                            signature_value = base64.b64decode(signature.encode("ascii"), validate=True).decode("utf-8")
                        except Exception:
                            self._deny_operator_auth(
                                status=HTTPStatus.UNAUTHORIZED,
                                error_message="operator request signature is malformed",
                                reason="operator request signature header is not valid base64 SSH signature material",
                                reason_code="signature-malformed",
                                auth_context=auth_context,
                            )
                            return None
                        signed_envelope = dict(envelope)
                        signed_envelope[IDENTITY_SIGNATURE_FIELD] = {
                            "alg": IDENTITY_ALGORITHM,
                            "principal": str(operator.identity_principal or "").strip(),
                            "namespace": OPERATOR_REQUEST_NAMESPACE,
                            "public_key": "",
                            "value": signature_value,
                        }
                        try:
                            verification = verify_document_with_ssh(
                                signed_envelope,
                                public_keys=operator.trusted_identity_public_keys,
                                revoked_public_keys=operator.revoked_identity_public_keys,
                                principal=str(operator.identity_principal or "").strip(),
                                expected_namespace=OPERATOR_REQUEST_NAMESPACE,
                            )
                        except SignatureError:
                            self._deny_operator_auth(
                                status=HTTPStatus.UNAUTHORIZED,
                                error_message="operator request signature verification failed",
                                reason="operator SSH request signature did not verify",
                                reason_code="signature-verification-failed",
                                auth_context=auth_context,
                            )
                            return None
                        auth_context["mode"] = "signed-ssh"
                    auth_context["verification"] = verification

                    if normalized_scopes and not set(normalized_scopes).intersection(granted_scopes):
                        self._deny_operator_auth(
                            status=HTTPStatus.FORBIDDEN,
                            error_message="operator scope is not allowed for this endpoint",
                            reason="operator scopes do not authorize this endpoint",
                            reason_code="scope-denied",
                            auth_context=auth_context,
                        )
                        return None

                    source_restrictions = operator.normalized_source_restrictions
                    if "loopback-only" in source_restrictions and not self._is_loopback_request():
                        self._deny_operator_auth(
                            status=HTTPStatus.FORBIDDEN,
                            error_message="operator source restriction denied request",
                            reason="operator identity is restricted to loopback sources",
                            reason_code="source-restriction-denied",
                            auth_context=auth_context,
                        )
                        return None

                    if not node.store.reserve_operator_auth_nonce(
                        key_id=operator.key_id,
                        nonce=nonce,
                        ttl_seconds=int(node.config.operator_auth_nonce_ttl_seconds or 900),
                    ):
                        self._deny_operator_auth(
                            status=HTTPStatus.UNAUTHORIZED,
                            error_message="operator request nonce has already been used",
                            reason="operator request nonce was already observed for this key",
                            reason_code="nonce-reused",
                            auth_context=auth_context,
                        )
                        return None

                    self._record_operator_auth_audit(
                        decision="allowed",
                        reason="signed operator request verified",
                        auth_context=auth_context,
                        payload={"signed_headers_present": True},
                    )
                    return auth_context

                if str(bearer_auth.get("kind") or "") == "scoped":
                    auth_context = self._auth_context(
                        policy_tier=policy_tier,
                        policy_level=policy_level,
                        required_scopes=normalized_scopes,
                        mode="scoped-bearer",
                        key_id=str(bearer_auth.get("token_id") or "").strip() or None,
                        operator_id=str(bearer_auth.get("token_id") or "").strip() or None,
                        granted_scopes=list(bearer_auth.get("granted_scopes") or []),
                        downgraded=True,
                    )
                    if not self._is_loopback_request():
                        self._deny_operator_auth(
                            status=HTTPStatus.FORBIDDEN,
                            error_message="scoped bearer tokens are restricted to loopback access",
                            reason="scoped bearer downgrade is only allowed from loopback",
                            reason_code="non-loopback-downgrade-denied",
                            auth_context=auth_context,
                        )
                        return None
                    source_restrictions = list(bearer_auth.get("source_restrictions") or [])
                    if "loopback-only" in source_restrictions and not self._is_loopback_request():
                        self._deny_operator_auth(
                            status=HTTPStatus.FORBIDDEN,
                            error_message="scoped bearer source restriction denied request",
                            reason="scoped bearer token is restricted to loopback sources",
                            reason_code="source-restriction-denied",
                            auth_context=auth_context,
                        )
                        return None
                    if normalized_scopes and not set(normalized_scopes).intersection(auth_context["granted_scopes"]):
                        self._deny_operator_auth(
                            status=HTTPStatus.FORBIDDEN,
                            error_message="scoped bearer scope is not allowed for this endpoint",
                            reason="scoped bearer scopes do not authorize this endpoint",
                            reason_code="scope-denied",
                            auth_context=auth_context,
                        )
                        return None
                    self._record_operator_auth_audit(
                        decision="allowed",
                        reason="loopback scoped bearer accepted",
                        auth_context=auth_context,
                        payload={"fallback": True, "token_kind": "scoped"},
                    )
                    return auth_context

                if str(bearer_auth.get("kind") or "") == "shared" and policy_tier == "local-admin":
                    auth_context = self._auth_context(
                        policy_tier=policy_tier,
                        policy_level=policy_level,
                        required_scopes=normalized_scopes,
                        mode="bearer-downgrade",
                        granted_scopes=["local-admin"],
                        downgraded=True,
                    )
                    if not self._is_loopback_request():
                        self._deny_operator_auth(
                            status=HTTPStatus.FORBIDDEN,
                            error_message="shared bearer downgrade is restricted to loopback access",
                            reason="shared bearer downgrade for local-admin endpoints is only allowed from loopback",
                            reason_code="non-loopback-downgrade-denied",
                            auth_context=auth_context,
                        )
                        return None
                    self._record_operator_auth_audit(
                        decision="allowed",
                        reason="loopback shared bearer accepted for local-admin endpoint",
                        auth_context=auth_context,
                        payload={"fallback": True, "token_kind": "shared"},
                    )
                    return auth_context

                if operators_configured:
                    fallback_allowed = self._is_loopback_request() and bool(node.config.operator_allow_loopback_bearer_fallback)
                    auth_context = self._auth_context(
                        policy_tier=policy_tier,
                        policy_level=policy_level,
                        required_scopes=normalized_scopes,
                        mode="bearer-downgrade" if fallback_allowed else "bearer-token",
                        downgraded=fallback_allowed,
                    )
                    if not fallback_allowed:
                        self._deny_operator_auth(
                            status=HTTPStatus.UNAUTHORIZED,
                            error_message="signed operator request required",
                            reason="configured operator identities require a signed operator request for this endpoint",
                            reason_code="signed-request-required",
                            auth_context=auth_context,
                        )
                        return None
                    self._record_operator_auth_audit(
                        decision="allowed",
                        reason="loopback bearer fallback accepted",
                        auth_context=auth_context,
                        payload={"fallback": True},
                    )
                    return auth_context

                auth_context = self._auth_context(
                    policy_tier=policy_tier,
                    policy_level=policy_level,
                    required_scopes=normalized_scopes,
                    mode="bearer-downgrade",
                    downgraded=True,
                )
                if not self._is_loopback_request():
                    self._deny_operator_auth(
                        status=HTTPStatus.FORBIDDEN,
                        error_message="signed operator requests are required for non-loopback access",
                        reason="tiered operator auth downgrade is only allowed from loopback when no operator identities are configured",
                        reason_code="non-loopback-downgrade-denied",
                        auth_context=auth_context,
                    )
                    return None
                self._record_operator_auth_audit(
                    decision="allowed",
                    reason="local bearer downgrade accepted",
                    auth_context=auth_context,
                    payload={"fallback": True, "operators_configured": False},
                )
                return auth_context

            def do_GET(self) -> None:
                parsed_request = urlparse(self.path)
                path = parsed_request.path
                query = parse_qs(parsed_request.query)

                # Preserve the current public MVP surface until operators explicitly configure signed identities.
                if node.config.operator_identities and operator_endpoint_policies.get(f"GET {path}"):
                    if not self._require_auth():
                        return

                if path == "/healthz":
                    self._json_response(
                        HTTPStatus.OK,
                        {
                            "status": "ok",
                            "node_id": node.config.node_id,
                            "local_identity": node.local_identity_view(),
                            "stats": node.store.stats(),
                        },
                    )
                    return
                if path == "/v1/card":
                    self._json_response(
                        HTTPStatus.OK,
                        node._sign_document(node.config.card.to_dict(), hmac_scope="agent-card", identity_namespace="agentcoin-card"),
                    )
                    return
                if path == "/v1/manifest":
                    self._json_response(HTTPStatus.OK, node.manifest())
                    return
                if path == "/v1/discovery/local-agents":
                    if not self._require_local_client_or_auth(
                        allow_endpoints={"/v1/discovery/local-agents"},
                    ):
                        return
                    self._json_response(
                        HTTPStatus.OK,
                        {
                            "generated_at": utc_now(),
                            "platform": node.discovery.system_name.lower(),
                            "wsl": node.discovery.is_wsl,
                            "items": node.discovery.discover(),
                        },
                    )
                    return
                if path == "/v1/discovery/local-agents/managed":
                    if not self._require_local_client_or_auth(
                        allow_endpoints={"/v1/discovery/local-agents/managed"},
                    ):
                        return
                    self._json_response(
                        HTTPStatus.OK,
                        {
                            "generated_at": utc_now(),
                            "items": node.local_agents.list_registrations(),
                        },
                    )
                    return
                if path == "/v1/discovery/local-agents/acp-sessions":
                    if not self._require_local_client_or_auth(
                        allow_endpoints={"/v1/discovery/local-agents/acp-sessions"},
                    ):
                        return
                    self._json_response(
                        HTTPStatus.OK,
                        {
                            "generated_at": utc_now(),
                            "items": node.local_agents.list_acp_sessions(),
                            "protocol_boundary": {
                                "transport_ready": True,
                                "protocol_messages_implemented": False,
                                "notes": [
                                    "ACP transport sessions are tracked, but AgentCoin does not yet exchange ACP protocol messages.",
                                    "Use these endpoints to manage local ACP process lifecycles and pending session handshakes.",
                                ],
                            },
                        },
                    )
                    return
                if path == "/v1/auth/challenge":
                    self._json_response(HTTPStatus.OK, {"challenge": node.issue_identity_auth_challenge()})
                    return
                if path == "/v1/payments/receipts/status":
                    auth_context = self._require_auth(
                        policy_tier="local-admin",
                        policy_level=1,
                        required_scopes=["local-admin"],
                    )
                    if not auth_context:
                        return
                    receipt_id = (query.get("receipt_id") or [""])[0]
                    if not receipt_id:
                        self._json_response(HTTPStatus.BAD_REQUEST, {"error": "receipt_id is required"})
                        return
                    receipt = node.get_payment_receipt(receipt_id)
                    self._json_response(HTTPStatus.OK, {"receipt": receipt})
                    return
                if path == "/v1/payments/receipts/onchain-relays":
                    if not self._require_local_client_or_auth(
                        allow_endpoints={"/v1/payments/receipts/onchain-relays"},
                    ):
                        return
                    receipt_id = (query.get("receipt_id") or [None])[0]
                    limit = int((query.get("limit") or ["200"])[0])
                    self._json_response(
                        HTTPStatus.OK,
                        {"items": node.store.list_payment_relays(receipt_id=receipt_id, limit=limit)},
                    )
                    return
                if path == "/v1/payments/ops/summary":
                    if not self._require_local_client_or_auth(
                        allow_endpoints={"/v1/payments/ops/summary"},
                    ):
                        return
                    receipt_id = (query.get("receipt_id") or [None])[0]
                    relay_limit = int((query.get("relay_limit") or ["5"])[0])
                    self._json_response(
                        HTTPStatus.OK,
                        node.payment_ops_summary(receipt_id=receipt_id, relay_limit=relay_limit),
                    )
                    return
                if path == "/v1/payments/receipts/onchain-relays/latest":
                    if not self._require_local_client_or_auth(
                        allow_endpoints={"/v1/payments/receipts/onchain-relays/latest"},
                    ):
                        return
                    receipt_id = (query.get("receipt_id") or [""])[0]
                    if not receipt_id:
                        self._json_response(HTTPStatus.BAD_REQUEST, {"error": "receipt_id is required"})
                        return
                    item = node.store.get_latest_payment_relay(receipt_id)
                    if not item:
                        self._json_response(HTTPStatus.NOT_FOUND, {"error": "payment relay not found"})
                        return
                    self._json_response(HTTPStatus.OK, item)
                    return
                if path == "/v1/payments/receipts/onchain-relays/latest-failed":
                    if not self._require_local_client_or_auth(
                        allow_endpoints={"/v1/payments/receipts/onchain-relays/latest-failed"},
                    ):
                        return
                    receipt_id = (query.get("receipt_id") or [""])[0]
                    if not receipt_id:
                        self._json_response(HTTPStatus.BAD_REQUEST, {"error": "receipt_id is required"})
                        return
                    item = node.store.get_latest_failed_payment_relay(receipt_id)
                    if not item:
                        self._json_response(HTTPStatus.NOT_FOUND, {"error": "failed payment relay not found"})
                        return
                    self._json_response(HTTPStatus.OK, item)
                    return
                if path == "/v1/payments/receipts/onchain-relay-queue":
                    if not self._require_local_client_or_auth(
                        allow_endpoints={"/v1/payments/receipts/onchain-relay-queue"},
                    ):
                        return
                    receipt_id = (query.get("receipt_id") or [None])[0]
                    status_name = (query.get("status") or [None])[0]
                    limit = int((query.get("limit") or ["200"])[0])
                    self._json_response(
                        HTTPStatus.OK,
                        {"items": node.store.list_payment_relay_queue(receipt_id=receipt_id, status=status_name, limit=limit)},
                    )
                    return
                if path == "/v1/payments/receipts/onchain-relay-queue/summary":
                    if not self._require_local_client_or_auth(
                        allow_endpoints={"/v1/payments/receipts/onchain-relay-queue/summary"},
                    ):
                        return
                    receipt_id = (query.get("receipt_id") or [None])[0]
                    self._json_response(HTTPStatus.OK, node.store.summarize_payment_relay_queue(receipt_id=receipt_id))
                    return
                if path == "/v1/schema/context":
                    self._json_response(HTTPStatus.OK, context_document())
                    return
                if path == "/v1/schema/examples":
                    self._json_response(HTTPStatus.OK, semantic_examples())
                    return
                if path == "/v1/schema/capabilities":
                    self._json_response(HTTPStatus.OK, capability_schema())
                    return
                if path == "/v1/onchain/status":
                    status_payload = node.onchain.status()
                    status_payload["transport"] = node.config.network.transport_profile()
                    status_payload["local_identity"] = {
                        **dict(status_payload.get("local_identity") or {}),
                        "did": node.config.resolved_local_did,
                        "principal": node.config.identity_principal,
                        "public_key": node.config.resolved_identity_public_key,
                    }
                    self._json_response(HTTPStatus.OK, status_payload)
                    return
                if path == "/v1/onchain/settlement-preview":
                    task_id = (query.get("task_id") or [""])[0]
                    if not task_id:
                        self._json_response(HTTPStatus.BAD_REQUEST, {"error": "task_id is required"})
                        return
                    task = node.store.get_task(task_id)
                    if not task:
                        self._json_response(HTTPStatus.NOT_FOUND, {"error": "task not found"})
                        return
                    preview = node._task_settlement_preview(task)
                    if not preview:
                        self._json_response(HTTPStatus.CONFLICT, {"error": "task is not bound to onchain settlement"})
                        return
                    self._json_response(HTTPStatus.OK, {"settlement": preview})
                    return
                if path == "/v1/onchain/settlement-ledger":
                    task_id = (query.get("task_id") or [""])[0]
                    if not task_id:
                        self._json_response(HTTPStatus.BAD_REQUEST, {"error": "task_id is required"})
                        return
                    task = node.store.get_task(task_id)
                    if not task:
                        self._json_response(HTTPStatus.NOT_FOUND, {"error": "task not found"})
                        return
                    ledger = node._task_settlement_ledger(task)
                    if not ledger:
                        self._json_response(HTTPStatus.CONFLICT, {"error": "task is not bound to onchain settlement"})
                        return
                    self._json_response(HTTPStatus.OK, {"ledger": ledger})
                    return
                if path == "/v1/onchain/settlement-rpc-plan":
                    self._json_response(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        {"error": "use POST /v1/onchain/settlement-rpc-plan with task_id"},
                    )
                    return
                if path == "/v1/onchain/settlement-raw-bundle":
                    self._json_response(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        {"error": "use POST /v1/onchain/settlement-raw-bundle with task_id and raw_transactions"},
                    )
                    return
                if path == "/v1/onchain/settlement-relay":
                    self._json_response(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        {"error": "use POST /v1/onchain/settlement-relay with task_id and raw_transactions"},
                    )
                    return
                if path == "/v1/onchain/settlement-relays/reconcile":
                    self._json_response(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        {"error": "use POST /v1/onchain/settlement-relays/reconcile with relay_id or task_id"},
                    )
                    return
                if path == "/v1/tasks":
                    self._json_response(HTTPStatus.OK, {"items": [node._decorate_task(item) for item in node.store.list_tasks()]})
                    return
                if path == "/v1/audits":
                    task_id = (query.get("task_id") or [None])[0]
                    limit = int((query.get("limit") or ["200"])[0])
                    self._json_response(HTTPStatus.OK, {"items": node.store.list_execution_audits(task_id=task_id, limit=limit)})
                    return
                if path == "/v1/reputation":
                    actor_id = (query.get("actor_id") or [None])[0]
                    actor_type = (query.get("actor_type") or ["worker"])[0]
                    limit = int((query.get("limit") or ["200"])[0])
                    if actor_id:
                        self._json_response(HTTPStatus.OK, node.store.get_actor_reputation(actor_id, actor_type=actor_type))
                    else:
                        self._json_response(
                            HTTPStatus.OK,
                            {"items": node.store.list_actor_reputations(actor_type=actor_type if actor_type else None, limit=limit)},
                        )
                    return
                if path == "/v1/poaw/events":
                    actor_id = (query.get("actor_id") or [None])[0]
                    actor_type = (query.get("actor_type") or [None])[0]
                    task_id = (query.get("task_id") or [None])[0]
                    event_type = (query.get("event_type") or [None])[0]
                    limit = int((query.get("limit") or ["200"])[0])
                    self._json_response(
                        HTTPStatus.OK,
                        {
                            "items": node.store.list_score_events(
                                actor_id=actor_id,
                                actor_type=actor_type,
                                task_id=task_id,
                                event_type=event_type,
                                limit=limit,
                            )
                        },
                    )
                    return
                if path == "/v1/poaw/summary":
                    actor_id = (query.get("actor_id") or [None])[0]
                    actor_type = (query.get("actor_type") or [None])[0]
                    task_id = (query.get("task_id") or [None])[0]
                    self._json_response(
                        HTTPStatus.OK,
                        node.store.summarize_score_events(actor_id=actor_id, actor_type=actor_type, task_id=task_id),
                    )
                    return
                if path == "/v1/peer-health":
                    peer_id = (query.get("peer_id") or [None])[0]
                    if peer_id:
                        self._json_response(HTTPStatus.OK, node.store.get_peer_health(peer_id))
                    else:
                        limit = int((query.get("limit") or ["200"])[0])
                        self._json_response(HTTPStatus.OK, {"items": node.store.list_peer_health(limit=limit)})
                    return
                if path == "/v1/tasks/dispatch/preview":
                    required_capabilities = [
                        str(item) for item in (query.get("required_capabilities") or []) if str(item).strip()
                    ]
                    prefer_local = (query.get("prefer_local") or ["0"])[0] in {"1", "true", "yes"}
                    include_blocked = (query.get("include_blocked") or ["0"])[0] in {"1", "true", "yes"}
                    self._json_response(
                        HTTPStatus.OK,
                        {
                            "required_capabilities": required_capabilities,
                            "prefer_local": prefer_local,
                            "include_blocked": include_blocked,
                            "candidates": node.dispatch_candidates(
                                required_capabilities,
                                prefer_local=prefer_local,
                                include_blocked=include_blocked,
                            ),
                        },
                    )
                    return
                if path == "/v1/tasks/dispatch/evaluate":
                    self._json_response(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        {"error": "use POST /v1/tasks/dispatch/evaluate with a full task payload"},
                    )
                    return
                if path == "/v1/violations":
                    actor_id = (query.get("actor_id") or [None])[0]
                    limit = int((query.get("limit") or ["200"])[0])
                    self._json_response(HTTPStatus.OK, {"items": node.store.list_policy_violations(actor_id=actor_id, limit=limit)})
                    return
                if path == "/v1/quarantines":
                    actor_id = (query.get("actor_id") or [None])[0]
                    active_only = (query.get("active_only") or ["1"])[0] in {"1", "true", "yes"}
                    limit = int((query.get("limit") or ["200"])[0])
                    self._json_response(
                        HTTPStatus.OK,
                        {"items": node.store.list_quarantines(actor_id=actor_id, active_only=active_only, limit=limit)},
                    )
                    return
                if path == "/v1/governance-actions":
                    actor_id = (query.get("actor_id") or [None])[0]
                    limit = int((query.get("limit") or ["200"])[0])
                    self._json_response(HTTPStatus.OK, {"items": node.store.list_governance_actions(actor_id=actor_id, limit=limit)})
                    return
                if path == "/v1/disputes":
                    task_id = (query.get("task_id") or [None])[0]
                    challenger_id = (query.get("challenger_id") or [None])[0]
                    status_name = (query.get("status") or [None])[0]
                    limit = int((query.get("limit") or ["200"])[0])
                    disputes = node.store.list_disputes(
                        task_id=task_id,
                        challenger_id=challenger_id,
                        status=status_name,
                        limit=limit,
                    )
                    self._json_response(
                        HTTPStatus.OK,
                        {"items": [node._decorate_dispute(item) for item in disputes]},
                    )
                    return
                if path == "/v1/onchain/settlement-relays":
                    task_id = (query.get("task_id") or [None])[0]
                    limit = int((query.get("limit") or ["200"])[0])
                    self._json_response(
                        HTTPStatus.OK,
                        {"items": node.store.list_settlement_relays(task_id=task_id, limit=limit)},
                    )
                    return
                if path == "/v1/onchain/settlement-relay-queue":
                    task_id = (query.get("task_id") or [None])[0]
                    status_name = (query.get("status") or [None])[0]
                    limit = int((query.get("limit") or ["200"])[0])
                    self._json_response(
                        HTTPStatus.OK,
                        {"items": node.store.list_settlement_relay_queue(task_id=task_id, status=status_name, limit=limit)},
                    )
                    return
                if path == "/v1/onchain/settlement-relays/latest":
                    task_id = (query.get("task_id") or [""])[0]
                    if not task_id:
                        self._json_response(HTTPStatus.BAD_REQUEST, {"error": "task_id is required"})
                        return
                    item = node.store.get_latest_settlement_relay(task_id)
                    if not item:
                        self._json_response(HTTPStatus.NOT_FOUND, {"error": "settlement relay not found"})
                        return
                    self._json_response(HTTPStatus.OK, item)
                    return
                if path == "/v1/bridges":
                    self._json_response(HTTPStatus.OK, {"items": node.bridges.list_bridges()})
                    return
                if path == "/v1/runtimes":
                    self._json_response(HTTPStatus.OK, {"items": node.runtimes.list_runtimes()})
                    return
                if path == "/v1/git/status":
                    self._json_response(HTTPStatus.OK, node._require_git().status())
                    return
                if path == "/v1/git/diff":
                    base_ref = (query.get("base_ref") or ["HEAD"])[0]
                    target_ref = (query.get("target_ref") or [None])[0]
                    name_only = (query.get("name_only") or ["0"])[0] in {"1", "true", "yes"}
                    self._json_response(HTTPStatus.OK, node._require_git().diff(base_ref=base_ref, target_ref=target_ref, name_only=name_only))
                    return
                if path == "/v1/tasks/dead-letter":
                    self._json_response(HTTPStatus.OK, {"items": [node._decorate_task(item) for item in node.store.list_dead_letter_tasks()]})
                    return
                if path == "/v1/workflows":
                    workflow_id = (query.get("workflow_id") or [""])[0]
                    if not workflow_id:
                        self._json_response(HTTPStatus.BAD_REQUEST, {"error": "workflow_id is required"})
                        return
                    self._json_response(HTTPStatus.OK, {"items": [node._decorate_task(item) for item in node.store.list_workflow_tasks(workflow_id)]})
                    return
                if path == "/v1/workflows/summary":
                    workflow_id = (query.get("workflow_id") or [""])[0]
                    if not workflow_id:
                        self._json_response(HTTPStatus.BAD_REQUEST, {"error": "workflow_id is required"})
                        return
                    self._json_response(HTTPStatus.OK, node.store.summarize_workflow(workflow_id))
                    return
                if path == "/v1/tasks/replay-inspect":
                    task_id = (query.get("task_id") or [""])[0]
                    if not task_id:
                        self._json_response(HTTPStatus.BAD_REQUEST, {"error": "task_id is required"})
                        return
                    task = node.store.get_task(task_id)
                    if not task:
                        self._json_response(HTTPStatus.NOT_FOUND, {"error": "task not found"})
                        return
                    bridge_protocol = str(task.get("payload", {}).get("_bridge", {}).get("protocol") or "").strip()
                    export_preview = None
                    if bridge_protocol:
                        export_preview = node.bridges.export_message(bridge_protocol, task)
                    workflow_tasks = node.store.list_workflow_tasks(str(task.get("workflow_id") or task_id))
                    related_reviews = [
                        item
                        for item in workflow_tasks
                        if str(item.get("payload", {}).get("_review", {}).get("target_task_id") or "").strip() == task_id
                    ]
                    git_proof_bundle = None
                    task_git_bundle = node._task_git_proof_bundle(task)
                    if task_git_bundle or related_reviews:
                        git_proof_bundle = {
                            "task": task_git_bundle,
                            "related_reviews": [node._task_git_proof_bundle(item) for item in related_reviews if node._task_git_proof_bundle(item)],
                            "merge_tasks": [
                                node._task_git_proof_bundle(item)
                                for item in workflow_tasks
                                if item.get("kind") == "merge" and node._task_git_proof_bundle(item)
                            ],
                            "dispute_evidence": [
                                {
                                    "dispute_id": item.get("id"),
                                    "challenge_evidence": item.get("challenge_evidence"),
                                    "git": item.get("payload", {}).get("_git"),
                                }
                                for item in node.store.list_disputes(task_id=task_id, limit=200)
                            ],
                        }
                    onchain_preview = None
                    if task.get("payload", {}).get("_onchain"):
                        task_result = dict(task.get("result") or {})
                        onchain_preview = {
                            "submitWork": node.onchain.transaction_intent(task, action="submitWork")
                            if task_result.get("_onchain_receipt")
                            else None,
                            "completeJob": node.onchain.transaction_intent(task, action="completeJob")
                            if task_result.get("_onchain_receipt")
                            else None,
                            "estimateGas": node.onchain.rpc_payload(task, action="submitWork", rpc={"method": "eth_estimateGas"})
                            if task_result.get("_onchain_receipt")
                            else None,
                        }
                    self._json_response(
                        HTTPStatus.OK,
                        {
                            "task": node._decorate_task(task),
                            "audits": node.store.list_execution_audits(task_id=task_id, limit=200),
                            "poaw_events": node.store.list_score_events(task_id=task_id, limit=200),
                            "poaw_summary": node.store.summarize_score_events(task_id=task_id),
                            "disputes": [
                                node._decorate_dispute(item, task=task)
                                for item in node.store.list_disputes(task_id=task_id, limit=200)
                            ],
                            "settlement_relays": node.store.list_settlement_relays(task_id=task_id, limit=200),
                            "settlement_relay_queue": node.store.list_settlement_relay_queue(task_id=task_id, limit=200),
                            "latest_settlement_relay": node.store.get_latest_settlement_relay(task_id),
                            "settlement_reconciliation": node._task_settlement_reconciliation(task_id),
                            "payment_relays": node.store.list_payment_relays(
                                receipt_id=str(dict(task.get("payload") or {}).get("_payment_receipt", {}).get("receipt_id") or "").strip() or None,
                                limit=200,
                            ),
                            "payment_relay_queue": node.store.list_payment_relay_queue(
                                receipt_id=str(dict(task.get("payload") or {}).get("_payment_receipt", {}).get("receipt_id") or "").strip() or None,
                                limit=200,
                            ),
                            "latest_payment_relay": (
                                node.store.get_latest_payment_relay(
                                    str(dict(task.get("payload") or {}).get("_payment_receipt", {}).get("receipt_id") or "").strip()
                                )
                                if str(dict(task.get("payload") or {}).get("_payment_receipt", {}).get("receipt_id") or "").strip()
                                else None
                            ),
                            "latest_failed_payment_relay": (
                                node.store.get_latest_failed_payment_relay(
                                    str(dict(task.get("payload") or {}).get("_payment_receipt", {}).get("receipt_id") or "").strip()
                                )
                                if str(dict(task.get("payload") or {}).get("_payment_receipt", {}).get("receipt_id") or "").strip()
                                else None
                            ),
                            "payment_relay_queue_summary": node.store.summarize_payment_relay_queue(
                                receipt_id=str(dict(task.get("payload") or {}).get("_payment_receipt", {}).get("receipt_id") or "").strip() or None
                            ),
                            "bridge_export_preview": export_preview,
                            "git_proof_bundle": git_proof_bundle,
                            "onchain_status": task.get("payload", {}).get("_onchain"),
                            "onchain_receipt": dict(task.get("result") or {}).get("_onchain_receipt"),
                            "onchain_intent_preview": onchain_preview,
                            "onchain_settlement_preview": node._task_settlement_preview(task),
                            "onchain_settlement_ledger": node._task_settlement_ledger(task),
                        },
                    )
                    return
                if path == "/v1/peers":
                    self._json_response(
                        HTTPStatus.OK,
                        {"items": [node._sanitize_peer(peer) for peer in node.config.peers]},
                    )
                    return
                if path == "/v1/peer-cards":
                    self._json_response(
                        HTTPStatus.OK,
                        {"items": [node._peer_card_view(item) for item in node.store.list_peer_cards()]},
                    )
                    return
                if path == "/v1/outbox":
                    self._json_response(HTTPStatus.OK, {"items": node.store.list_outbox()})
                    return
                if path == "/v1/outbox/dead-letter":
                    self._json_response(HTTPStatus.OK, {"items": node.store.list_outbox(status="dead-letter")})
                    return
                self._json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})

            def do_POST(self) -> None:
                try:
                    if self.path == "/v1/auth/verify":
                        payload = self._read_json()
                        challenge_id = str(payload.get("challenge_id") or "").strip()
                        principal = str(payload.get("principal") or "").strip()
                        public_key = str(payload.get("public_key") or "").strip()
                        if not challenge_id or not principal or not public_key:
                            raise ValueError("challenge_id, principal, and public_key are required")
                        challenge = node.get_identity_auth_challenge(challenge_id)
                        verification = self._identity_request_verification(
                            principal=principal,
                            public_key=public_key,
                        )
                        node.finalize_identity_auth_challenge(challenge_id)
                        identity = {
                            "principal": principal,
                            "public_key": public_key,
                            "did": derive_local_did(public_key=public_key),
                            "algorithm": IDENTITY_ALGORITHM,
                        }
                        session = node.issue_identity_auth_session(
                            principal=principal,
                            public_key=public_key,
                            did=str(identity.get("did") or "").strip() or None,
                            allow_endpoints=[
                                "/v1/tasks",
                                "/v1/tasks/dispatch",
                                "/v1/tasks/dispatch/evaluate",
                                "/v1/discovery/local-agents",
                                "/v1/discovery/local-agents/managed",
                                "/v1/discovery/local-agents/register",
                                "/v1/discovery/local-agents/start",
                                "/v1/discovery/local-agents/stop",
                                "/v1/discovery/local-agents/acp-sessions",
                                "/v1/discovery/local-agents/acp-session/open",
                                "/v1/discovery/local-agents/acp-session/close",
                                "/v1/discovery/local-agents/acp-session/initialize",
                                "/v1/workflow/execute",
                                "/v1/payments/ops/summary",
                                "/v1/payments/receipts/introspect",
                                "/v1/payments/receipts/onchain-proof",
                                "/v1/payments/receipts/onchain-rpc-plan",
                                "/v1/payments/receipts/onchain-raw-bundle",
                                "/v1/payments/receipts/onchain-relay",
                                "/v1/payments/receipts/onchain-relays",
                                "/v1/payments/receipts/onchain-relays/latest",
                                "/v1/payments/receipts/onchain-relays/latest-failed",
                                "/v1/payments/receipts/onchain-relay-queue",
                                "/v1/payments/receipts/onchain-relay-queue/summary",
                                "/v1/payments/receipts/onchain-relay-queue/pause",
                                "/v1/payments/receipts/onchain-relay-queue/resume",
                                "/v1/payments/receipts/onchain-relay-queue/auto-requeue/disable",
                                "/v1/payments/receipts/onchain-relay-queue/auto-requeue/enable",
                                "/v1/payments/receipts/onchain-relay-queue/requeue",
                                "/v1/payments/receipts/onchain-relay-queue/cancel",
                                "/v1/payments/receipts/onchain-relay-queue/delete",
                                "/v1/payments/receipts/onchain-relay/replay-helper",
                                "/v1/runtimes/bind",
                                "/v1/integrations/openclaw/bind",
                            ],
                        )
                        receipt = node._sign_document(
                            {
                                "kind": "agentcoin-identity-auth-receipt",
                                "verified": True,
                                "identity": identity,
                                "challenge": {
                                    "challenge_id": challenge.get("challenge_id"),
                                    "issued_at": challenge.get("issued_at"),
                                    "expires_at": challenge.get("expires_at"),
                                    "consumed": True,
                                },
                                "verification": verification,
                                "session": {
                                    "scheme": session.get("scheme"),
                                    "session_token": session.get("session_token"),
                                    "expires_at": session.get("expires_at"),
                                    "allow_endpoints": list(session.get("allow_endpoints") or []),
                                },
                                "generated_at": utc_now(),
                            },
                            hmac_scope="identity-auth-receipt",
                            identity_namespace="agentcoin-identity-auth",
                        )
                        self._json_response(
                            HTTPStatus.OK,
                            {
                                "ok": True,
                                "identity": identity,
                                "challenge": {
                                    "challenge_id": challenge.get("challenge_id"),
                                    "issued_at": challenge.get("issued_at"),
                                    "expires_at": challenge.get("expires_at"),
                                    "consumed": True,
                                },
                                "receipt": receipt,
                                "session": session,
                            },
                        )
                        return
                    if self.path == "/v1/payments/receipts/issue":
                        auth_context = self._require_auth(
                            policy_tier="local-admin",
                            policy_level=1,
                            required_scopes=["local-admin"],
                        )
                        if not auth_context:
                            return
                        payload = self._read_json()
                        challenge_id = str(payload.get("challenge_id") or "").strip()
                        payer = str(payload.get("payer") or "").strip()
                        tx_hash = str(payload.get("tx_hash") or "").strip()
                        if not challenge_id or not payer or not tx_hash:
                            raise ValueError("challenge_id, payer, and tx_hash are required")
                        signed_receipt, created = node.issue_payment_receipt(
                            challenge_id=challenge_id,
                            payer=payer,
                            tx_hash=tx_hash,
                        )
                        challenge = node.get_payment_challenge(challenge_id)
                        receipt_status = node.get_payment_receipt(str(signed_receipt.get("receipt_id") or ""))
                        attestation = node.build_payment_attestation(
                            challenge=challenge,
                            receipt=signed_receipt,
                            receipt_status=receipt_status,
                            active=True,
                            reason="",
                        )
                        self._json_response(
                            HTTPStatus.CREATED if created else HTTPStatus.OK,
                            {"receipt": signed_receipt, "attestation": attestation, "created": created},
                        )
                        return
                    if self.path == "/v1/payments/receipts/introspect":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/introspect"},
                        ):
                            return
                        payload = self._read_json()
                        payment_receipt = dict(payload.get("payment_receipt") or {})
                        if not payment_receipt:
                            raise ValueError("payment_receipt is required")
                        workflow_name = str(payload.get("workflow_name") or payload.get("workflow") or "").strip() or None
                        introspection = node.introspect_payment_receipt(
                            payment_receipt,
                            workflow_name=workflow_name,
                        )
                        self._json_response(
                            HTTPStatus.OK,
                            {
                                "receipt": payment_receipt,
                                "introspection": introspection,
                            },
                        )
                        return
                    if self.path == "/v1/payments/receipts/onchain-proof":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/onchain-proof"},
                        ):
                            return
                        payload = self._read_json()
                        payment_receipt = dict(payload.get("payment_receipt") or {})
                        if not payment_receipt:
                            raise ValueError("payment_receipt is required")
                        workflow_name = str(payload.get("workflow_name") or payload.get("workflow") or "").strip() or None
                        proof = node.build_payment_onchain_proof(
                            payment_receipt,
                            workflow_name=workflow_name,
                        )
                        self._json_response(
                            HTTPStatus.OK,
                            {
                                "proof": proof,
                            },
                        )
                        return
                    if self.path == "/v1/payments/receipts/onchain-rpc-plan":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/onchain-rpc-plan"},
                        ):
                            return
                        payload = self._read_json()
                        payment_receipt = dict(payload.get("payment_receipt") or {})
                        if not payment_receipt:
                            raise ValueError("payment_receipt is required")
                        workflow_name = str(payload.get("workflow_name") or payload.get("workflow") or "").strip() or None
                        rpc_options = dict(payload.get("rpc") or {})
                        plan = node.build_payment_onchain_rpc_plan(
                            payment_receipt,
                            workflow_name=workflow_name,
                            rpc=rpc_options,
                        )
                        self._json_response(
                            HTTPStatus.OK,
                            {
                                "plan": plan,
                            },
                        )
                        return
                    if self.path == "/v1/payments/receipts/onchain-raw-bundle":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/onchain-raw-bundle"},
                        ):
                            return
                        payload = self._read_json()
                        payment_receipt = dict(payload.get("payment_receipt") or {})
                        if not payment_receipt:
                            raise ValueError("payment_receipt is required")
                        workflow_name = str(payload.get("workflow_name") or payload.get("workflow") or "").strip() or None
                        bundle = node.build_payment_onchain_raw_bundle(
                            payment_receipt,
                            workflow_name=workflow_name,
                            raw_transactions=list(payload.get("raw_transactions") or []),
                            rpc=dict(payload.get("rpc") or {}),
                            rpc_url=str(payload.get("rpc_url") or "").strip() or None,
                        )
                        self._json_response(HTTPStatus.OK, {"bundle": bundle})
                        return
                    if self.path == "/v1/payments/receipts/onchain-relay":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/onchain-relay"},
                        ):
                            return
                        payload = self._read_json()
                        payment_receipt = dict(payload.get("payment_receipt") or {})
                        if not payment_receipt:
                            raise ValueError("payment_receipt is required")
                        workflow_name = str(payload.get("workflow_name") or payload.get("workflow") or "").strip() or None
                        relay = node.execute_payment_onchain_relay(
                            payment_receipt,
                            workflow_name=workflow_name,
                            raw_transactions=list(payload.get("raw_transactions") or []),
                            rpc=dict(payload.get("rpc") or {}),
                            rpc_url=str(payload.get("rpc_url") or "").strip() or None,
                            timeout=float(payload.get("timeout_seconds") or 10),
                            continue_on_error=bool(payload.get("continue_on_error")),
                        )
                        self._json_response(HTTPStatus.OK, {"relay": relay})
                        return
                    if self.path == "/v1/payments/receipts/onchain-relay-queue":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/onchain-relay-queue"},
                        ):
                            return
                        payload = self._read_json()
                        payment_receipt = dict(payload.get("payment_receipt") or {})
                        if not payment_receipt:
                            raise ValueError("payment_receipt is required")
                        workflow_name = str(
                            payload.get("workflow_name")
                            or payment_receipt.get("workflow_name")
                            or payload.get("workflow")
                            or ""
                        ).strip()
                        if not workflow_name:
                            raise ValueError("workflow_name is required")
                        receipt_id = str(payment_receipt.get("receipt_id") or "").strip()
                        if not receipt_id:
                            raise ValueError("payment_receipt.receipt_id is required")
                        queue_payload = {
                            "payment_receipt": payment_receipt,
                            "workflow_name": workflow_name,
                            "raw_transactions": list(payload.get("raw_transactions") or []),
                            "rpc": dict(payload.get("rpc") or {}),
                            "rpc_url": str(payload.get("rpc_url") or "").strip() or None,
                            "timeout_seconds": float(payload.get("timeout_seconds") or 10),
                            "continue_on_error": bool(payload.get("continue_on_error")),
                        }
                        item = node.store.enqueue_payment_relay(
                            receipt_id=receipt_id,
                            workflow_name=workflow_name,
                            payload=queue_payload,
                            max_attempts=int(payload.get("max_attempts") or 3),
                            delay_seconds=int(payload.get("delay_seconds") or 0),
                        )
                        self._json_response(HTTPStatus.CREATED, {"item": item})
                        return
                    if self.path == "/v1/discovery/local-agents/register":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/discovery/local-agents/register"},
                        ):
                            return
                        payload = self._read_json()
                        item = node.register_local_discovered_agent(str(payload.get("discovered_id") or "").strip())
                        self._json_response(HTTPStatus.CREATED, {"item": item})
                        return
                    if self.path == "/v1/discovery/local-agents/start":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/discovery/local-agents/start"},
                        ):
                            return
                        payload = self._read_json()
                        registration_id = str(payload.get("registration_id") or "").strip()
                        if not registration_id:
                            raise ValueError("registration_id is required")
                        item = node.local_agents.start_registration(registration_id)
                        self._json_response(HTTPStatus.OK, {"item": item})
                        return
                    if self.path == "/v1/discovery/local-agents/stop":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/discovery/local-agents/stop"},
                        ):
                            return
                        payload = self._read_json()
                        registration_id = str(payload.get("registration_id") or "").strip()
                        if not registration_id:
                            raise ValueError("registration_id is required")
                        item = node.local_agents.stop_registration(registration_id)
                        self._json_response(HTTPStatus.OK, {"item": item})
                        return
                    if self.path == "/v1/discovery/local-agents/acp-session/open":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/discovery/local-agents/acp-session/open"},
                        ):
                            return
                        payload = self._read_json()
                        registration_id = str(payload.get("registration_id") or "").strip()
                        if not registration_id:
                            raise ValueError("registration_id is required")
                        session = node.local_agents.open_acp_session(registration_id)
                        self._json_response(
                            HTTPStatus.OK,
                            {
                                "ok": True,
                                "session": session,
                                "protocol_boundary": {
                                    "transport_ready": True,
                                    "protocol_messages_implemented": False,
                                },
                            },
                        )
                        return
                    if self.path == "/v1/discovery/local-agents/acp-session/close":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/discovery/local-agents/acp-session/close"},
                        ):
                            return
                        payload = self._read_json()
                        session_id = str(payload.get("session_id") or "").strip()
                        if not session_id:
                            raise ValueError("session_id is required")
                        session = node.local_agents.close_acp_session(session_id)
                        self._json_response(HTTPStatus.OK, {"ok": True, "session": session})
                        return
                    if self.path == "/v1/discovery/local-agents/acp-session/initialize":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/discovery/local-agents/acp-session/initialize"},
                        ):
                            return
                        payload = self._read_json()
                        session_id = str(payload.get("session_id") or "").strip()
                        if not session_id:
                            raise ValueError("session_id is required")
                        prepared = node.local_agents.prepare_acp_initialize(
                            session_id,
                            protocol_version=str(payload.get("protocol_version") or "0.1-preview").strip() or "0.1-preview",
                            client_capabilities=dict(payload.get("client_capabilities") or {}),
                            client_info=dict(payload.get("client_info") or {}),
                            dispatch=bool(payload.get("dispatch")),
                        )
                        self._json_response(
                            HTTPStatus.OK,
                            {
                                "ok": True,
                                **prepared,
                                "protocol_boundary": {
                                    "transport_ready": True,
                                    "protocol_messages_implemented": False,
                                    "server_response_parsing_implemented": False,
                                },
                            },
                        )
                        return
                    if self.path == "/v1/payments/receipts/onchain-relay-queue/requeue":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/onchain-relay-queue/requeue"},
                        ):
                            return
                        payload = self._read_json()
                        queue_id = str(payload.get("queue_id") or "").strip()
                        if not queue_id:
                            raise ValueError("queue_id is required")
                        existing = node.store.get_payment_relay_queue_item(queue_id)
                        if not existing:
                            raise ValueError("payment relay queue item not found")
                        receipt = dict(payload.get("payment_receipt") or existing.get("payload", {}).get("payment_receipt") or {})
                        receipt_id = str(receipt.get("receipt_id") or existing.get("receipt_id") or "").strip()
                        if not receipt_id:
                            raise ValueError("payment_receipt.receipt_id is required")
                        workflow_name = str(
                            payload.get("workflow_name")
                            or existing.get("workflow_name")
                            or receipt.get("workflow_name")
                            or ""
                        ).strip()
                        if not workflow_name:
                            raise ValueError("workflow_name is required")
                        queue_payload = node._merge_payment_relay_queue_payload(
                            dict(existing.get("payload") or {}),
                            payload,
                            receipt=receipt,
                            workflow_name=workflow_name,
                        )
                        item = node.store.requeue_payment_relay_queue_item(
                            queue_id,
                            delay_seconds=int(payload.get("delay_seconds") or 0),
                            payload=queue_payload,
                            max_attempts=int(payload.get("max_attempts")) if payload.get("max_attempts") is not None else None,
                        )
                        if not item or item.get("status") != "queued":
                            raise ValueError("queue item cannot be requeued")
                        self._json_response(HTTPStatus.OK, {"item": item})
                        return
                    if self.path == "/v1/payments/receipts/onchain-relay-queue/pause":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/onchain-relay-queue/pause"},
                        ):
                            return
                        payload = self._read_json()
                        queue_id = str(payload.get("queue_id") or "").strip()
                        if not queue_id:
                            raise ValueError("queue_id is required")
                        existing = node.store.get_payment_relay_queue_item(queue_id)
                        if not existing:
                            raise ValueError("payment relay queue item not found")
                        item = node.store.pause_payment_relay_queue_item(queue_id)
                        if not item or item.get("status") != "paused":
                            raise ValueError("queue item cannot be paused")
                        self._json_response(HTTPStatus.OK, {"item": item})
                        return
                    if self.path == "/v1/payments/receipts/onchain-relay-queue/resume":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/onchain-relay-queue/resume"},
                        ):
                            return
                        payload = self._read_json()
                        queue_id = str(payload.get("queue_id") or "").strip()
                        if not queue_id:
                            raise ValueError("queue_id is required")
                        existing = node.store.get_payment_relay_queue_item(queue_id)
                        if not existing:
                            raise ValueError("payment relay queue item not found")
                        item = node.store.resume_payment_relay_queue_item(
                            queue_id,
                            delay_seconds=int(payload.get("delay_seconds") or 0),
                        )
                        if not item or item.get("status") != "queued":
                            raise ValueError("queue item cannot be resumed")
                        self._json_response(HTTPStatus.OK, {"item": item})
                        return
                    if self.path == "/v1/payments/receipts/onchain-relay-queue/auto-requeue/disable":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/onchain-relay-queue/auto-requeue/disable"},
                        ):
                            return
                        payload = self._read_json()
                        queue_id = str(payload.get("queue_id") or "").strip()
                        if not queue_id:
                            raise ValueError("queue_id is required")
                        item = node.set_payment_relay_auto_requeue_disabled(
                            queue_id,
                            disabled=True,
                            reason=str(payload.get("reason") or "").strip() or None,
                        )
                        self._json_response(HTTPStatus.OK, {"item": item})
                        return
                    if self.path == "/v1/payments/receipts/onchain-relay-queue/auto-requeue/enable":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/onchain-relay-queue/auto-requeue/enable"},
                        ):
                            return
                        payload = self._read_json()
                        queue_id = str(payload.get("queue_id") or "").strip()
                        if not queue_id:
                            raise ValueError("queue_id is required")
                        item = node.set_payment_relay_auto_requeue_disabled(queue_id, disabled=False)
                        self._json_response(HTTPStatus.OK, {"item": item})
                        return
                    if self.path == "/v1/payments/receipts/onchain-relay-queue/cancel":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/onchain-relay-queue/cancel"},
                        ):
                            return
                        payload = self._read_json()
                        queue_id = str(payload.get("queue_id") or "").strip()
                        if not queue_id:
                            raise ValueError("queue_id is required")
                        existing = node.store.get_payment_relay_queue_item(queue_id)
                        if not existing:
                            raise ValueError("payment relay queue item not found")
                        item = node.store.cancel_payment_relay_queue_item(queue_id)
                        if not item or item.get("status") != "dead-letter":
                            raise ValueError("queue item cannot be cancelled")
                        self._json_response(HTTPStatus.OK, {"item": item})
                        return
                    if self.path == "/v1/payments/receipts/onchain-relay-queue/delete":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/onchain-relay-queue/delete"},
                        ):
                            return
                        payload = self._read_json()
                        queue_id = str(payload.get("queue_id") or "").strip()
                        if not queue_id:
                            raise ValueError("queue_id is required")
                        existing = node.store.get_payment_relay_queue_item(queue_id)
                        if not existing:
                            raise ValueError("payment relay queue item not found")
                        ok = node.store.delete_payment_relay_queue_item(queue_id)
                        self._json_response(HTTPStatus.OK, {"ok": ok})
                        return
                    if self.path == "/v1/payments/receipts/onchain-relay/replay-helper":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/payments/receipts/onchain-relay/replay-helper"},
                        ):
                            return
                        payload = self._read_json()
                        helper = node.build_payment_relay_replay_helper(
                            receipt_id=str(payload.get("receipt_id") or "").strip() or None,
                            relay_id=str(payload.get("relay_id") or "").strip() or None,
                            queue_id=str(payload.get("queue_id") or "").strip() or None,
                        )
                        self._json_response(HTTPStatus.OK, {"helper": helper})
                        return
                    if self.path == "/v1/workflow/execute":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/workflow/execute"},
                        ):
                            return
                        payload = self._read_json()
                        workflow_name = str(payload.get("workflow_name") or payload.get("workflow") or "").strip()
                        if not workflow_name:
                            raise ValueError("workflow_name is required")
                        payment_required = workflow_name in set(node.config.payment_required_workflows or [])
                        payment_receipt = dict(payload.get("payment_receipt") or {})
                        payment_verification = None
                        task_id = str(payload.get("task_id") or uuid4())
                        if payment_required:
                            if not payment_receipt:
                                challenge = node.issue_payment_challenge(
                                    workflow_name=workflow_name,
                                    payer_hint=str(payload.get("payer") or "").strip() or None,
                                )
                                self._json_response(
                                    HTTPStatus.PAYMENT_REQUIRED,
                                    {
                                        "error": "payment required",
                                        "payment": {
                                            "required": True,
                                            "receipt_kind": "agentcoin-payment-receipt",
                                            "proof_type": "local-operator-attestation",
                                            "challenge": challenge,
                                            "quote": dict(challenge.get("quote") or {}),
                                        },
                                    },
                                    extra_headers={
                                        "X-Agentcoin-Payment-Required": "true",
                                        "X-Agentcoin-Payment-Challenge-Id": str(challenge["challenge_id"]),
                                        "X-Agentcoin-Payment-Amount-Wei": str(challenge["amount_wei"]),
                                        "X-Agentcoin-Payment-Asset": str(challenge["asset"]),
                                        "X-Agentcoin-Payment-Recipient": str(challenge.get("recipient") or ""),
                                        "X-Agentcoin-Payment-Bounty-Escrow": str(challenge.get("bounty_escrow_address") or ""),
                                    },
                                )
                                return
                            payment_verification = node.verify_payment_receipt(payment_receipt, workflow_name=workflow_name)
                            consumed_receipt = node.consume_payment_receipt(
                                str(payment_receipt.get("receipt_id") or ""),
                                workflow_name=workflow_name,
                                task_id=task_id,
                            )
                            payment_verification["receipt_status"] = consumed_receipt

                        task_payload = {
                            "workflow_name": workflow_name,
                            "input": payload.get("input"),
                        }
                        if payment_verification:
                            task_payload["_payment_receipt"] = payment_receipt
                            task_payload["_payment_verification"] = payment_verification
                        task = node._normalize_task(
                            TaskEnvelope.from_dict(
                                {
                                    "id": task_id,
                                    "kind": "workflow-execute",
                                    "role": "worker",
                                    "required_capabilities": list(payload.get("required_capabilities") or ["worker"]),
                                    "payload": task_payload,
                                }
                            ),
                            node.config,
                        )
                        if task.sender == "local":
                            task.sender = node.config.node_id
                        node._persist_task_delivery(task)
                        self._json_response(
                            HTTPStatus.ACCEPTED,
                            {
                                "ok": True,
                                "task": task.to_dict(),
                                "payment_required": payment_required,
                                "payment_verified": bool(payment_verification),
                            },
                        )
                        return
                    if self.path == "/v1/tasks":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/tasks"},
                        ):
                            return
                        payload = self._read_json()
                        task = node._normalize_task(TaskEnvelope.from_dict(payload), node.config)
                        if task.sender == "local":
                            task.sender = node.config.node_id
                        if bool(payload.get("attach_git_context")):
                            base_ref = str(payload.get("git_base_ref") or "HEAD")
                            target_ref = payload.get("git_target_ref")
                            task.payload["_git"] = node._require_git().task_context(base_ref=base_ref, target_ref=target_ref)
                        if bool(payload.get("attach_onchain_context")):
                            task = node._bind_onchain_context(task, job_id=payload.get("onchain_job_id"))
                        node._persist_task_delivery(task)
                        self._json_response(HTTPStatus.CREATED, {"task": task.to_dict()})
                        return
                    if self.path == "/v1/onchain/task-bind":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        task_id = str(payload.get("task_id") or "").strip()
                        if not task_id:
                            raise ValueError("task_id is required")
                        task = node.store.get_task(task_id)
                        if not task:
                            raise ValueError("task not found")
                        merged_payload = dict(task["payload"])
                        merged_payload["_onchain"] = node.onchain.task_context(task, job_id=payload.get("job_id"))
                        updated = node.store.update_task_payload(task_id, merged_payload)
                        self._json_response(
                            HTTPStatus.OK,
                            {"ok": updated, "task_id": task_id, "onchain": merged_payload.get("_onchain")},
                        )
                        return
                    if self.path == "/v1/runtimes/bind":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/runtimes/bind"},
                        ):
                            return
                        payload = self._read_json()
                        task_id = str(payload.get("task_id") or "").strip()
                        runtime_name = str(payload.get("runtime") or "").strip()
                        if not task_id:
                            raise ValueError("task_id is required")
                        if not runtime_name:
                            raise ValueError("runtime is required")
                        task = node.store.get_task(task_id)
                        if not task:
                            raise ValueError("task not found")
                        merged_payload = dict(task["payload"])
                        merged_payload["_runtime"] = node.runtimes.normalize_binding(runtime_name, dict(payload.get("options") or {}))
                        updated = node.store.update_task_payload(task_id, merged_payload)
                        self._json_response(
                            HTTPStatus.OK,
                            {"ok": updated, "task_id": task_id, "runtime": merged_payload.get("_runtime")},
                        )
                        return
                    if self.path == "/v1/integrations/openclaw/bind":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/integrations/openclaw/bind"},
                        ):
                            return
                        payload = self._read_json()
                        task_id = str(payload.get("task_id") or "").strip()
                        if not task_id:
                            raise ValueError("task_id is required")
                        task = node.store.get_task(task_id)
                        if not task:
                            raise ValueError("task not found")
                        endpoint = str(payload.get("endpoint") or "").strip()
                        model = str(payload.get("model") or "").strip()
                        if not endpoint:
                            raise ValueError("endpoint is required")
                        if not model:
                            raise ValueError("model is required")
                        runtime_options = {
                            "endpoint": endpoint,
                            "model": model,
                            "auth_token": str(payload.get("auth_token") or "").strip() or None,
                            "prompt": payload.get("prompt"),
                            "messages": payload.get("messages"),
                            "temperature": payload.get("temperature"),
                            "max_tokens": payload.get("max_tokens"),
                            "timeout_seconds": int(payload.get("timeout_seconds") or 60),
                            "provider": "openclaw-gateway",
                        }
                        merged_payload = dict(task["payload"])
                        merged_payload["_runtime"] = node.runtimes.normalize_binding(
                            "openai-chat",
                            {key: value for key, value in runtime_options.items() if value is not None},
                        )
                        updated = node.store.update_task_payload(task_id, merged_payload)
                        self._json_response(
                            HTTPStatus.OK,
                            {
                                "ok": updated,
                                "task_id": task_id,
                                "runtime": merged_payload.get("_runtime"),
                                "provider": "openclaw-gateway",
                            },
                        )
                        return
                    if self.path == "/v1/onchain/intents/build":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        action = str(payload.get("action") or "").strip()
                        task_id = str(payload.get("task_id") or "").strip()
                        if not action:
                            raise ValueError("action is required")
                        if not task_id:
                            raise ValueError("task_id is required")
                        task = node.store.get_task(task_id)
                        if not task:
                            raise ValueError("task not found")
                        intent = node.onchain.transaction_intent(task, action=action, params=dict(payload.get("params") or {}))
                        signed_intent = node._sign_document(
                            intent,
                            hmac_scope="onchain-intent",
                            identity_namespace="agentcoin-onchain-intent",
                        )
                        self._json_response(HTTPStatus.OK, {"intent": signed_intent})
                        return
                    if self.path == "/v1/onchain/rpc-payload":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        action = str(payload.get("action") or "").strip()
                        task_id = str(payload.get("task_id") or "").strip()
                        if not action:
                            raise ValueError("action is required")
                        if not task_id:
                            raise ValueError("task_id is required")
                        task = node.store.get_task(task_id)
                        if not task:
                            raise ValueError("task not found")
                        rpc_payload = node.onchain.rpc_payload(
                            task,
                            action=action,
                            params=dict(payload.get("params") or {}),
                            rpc=dict(payload.get("rpc") or {}),
                        )
                        signed_rpc_payload = node._sign_document(
                            rpc_payload,
                            hmac_scope="onchain-rpc-payload",
                            identity_namespace="agentcoin-onchain-rpc",
                        )
                        self._json_response(HTTPStatus.OK, {"rpc_payload": signed_rpc_payload})
                        return
                    if self.path == "/v1/onchain/rpc-plan":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        action = str(payload.get("action") or "").strip()
                        task_id = str(payload.get("task_id") or "").strip()
                        if not action:
                            raise ValueError("action is required")
                        if not task_id:
                            raise ValueError("task_id is required")
                        task = node.store.get_task(task_id)
                        if not task:
                            raise ValueError("task not found")
                        intent = node.onchain.transaction_intent(task, action=action, params=dict(payload.get("params") or {}))
                        rpc_options = dict(payload.get("rpc") or {})
                        rpc_payload = node.onchain.rpc_payload_for_intent(intent, rpc=rpc_options)
                        probes = node.onchain.rpc_probe_payloads(rpc_payload, rpc=rpc_options)
                        live_results: dict[str, Any] = {}
                        timeout = float(payload.get("timeout_seconds") or 10)
                        resolve_live = bool(payload.get("resolve_live", True))
                        rpc_url = str(rpc_payload.get("rpc_url") or "").strip()
                        if resolve_live and not rpc_url:
                            raise ValueError("rpc_url is required for resolve_live plan")
                        for probe in probes:
                            if not resolve_live:
                                break
                            response = node._chain_rpc_call(rpc_url, probe["request"], timeout=timeout)
                            probe["response"] = response
                            if "result" in response:
                                live_results[probe["name"]] = response["result"]
                        planned_rpc_payload = node.onchain.apply_rpc_probe_results(rpc_payload, live_results)
                        plan = {
                            "kind": "evm-json-rpc-plan",
                            "intent": intent,
                            "rpc_payload": planned_rpc_payload,
                            "probes": probes,
                            "live_results": live_results,
                            "transport": node.config.network.transport_profile(),
                            "resolved_live": resolve_live,
                            "generated_at": utc_now(),
                        }
                        signed_plan = node._sign_document(
                            plan,
                            hmac_scope="onchain-rpc-plan",
                            identity_namespace="agentcoin-onchain-rpc-plan",
                        )
                        self._json_response(HTTPStatus.OK, {"plan": signed_plan})
                        return
                    if self.path == "/v1/onchain/rpc/send-raw":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        raw_transaction = str(payload.get("raw_transaction") or "").strip()
                        if not raw_transaction:
                            raise ValueError("raw_transaction is required")
                        timeout = float(payload.get("timeout_seconds") or 10)
                        rpc_payload = node.onchain.raw_transaction_payload(
                            raw_transaction,
                            rpc_url=str(payload.get("rpc_url") or "").strip() or None,
                            request_id=str(payload.get("request_id") or "").strip() or None,
                        )
                        rpc_url = str(rpc_payload.get("rpc_url") or "").strip()
                        if not rpc_url:
                            raise ValueError("rpc_url is required")
                        response = node._chain_rpc_call(rpc_url, rpc_payload["request"], timeout=timeout)
                        relay = {
                            "kind": "evm-json-rpc-relay",
                            "rpc_payload": rpc_payload,
                            "response": response,
                            "tx_hash": response.get("result"),
                            "transport": node.config.network.transport_profile(),
                            "generated_at": rpc_payload.get("generated_at"),
                        }
                        signed_relay = node._sign_document(
                            relay,
                            hmac_scope="onchain-rpc-relay",
                            identity_namespace="agentcoin-onchain-rpc-relay",
                        )
                        self._json_response(HTTPStatus.OK, {"relay": signed_relay})
                        return
                    if self.path == "/v1/onchain/settlement-rpc-plan":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        task_id = str(payload.get("task_id") or "").strip()
                        if not task_id:
                            raise ValueError("task_id is required")
                        task = node.store.get_task(task_id)
                        if not task:
                            raise ValueError("task not found")
                        settlement = node._task_settlement_preview(task)
                        if not settlement:
                            raise ValueError("task is not bound to onchain settlement")
                        settlement_ledger = node._task_settlement_ledger(task)
                        rpc_options = dict(payload.get("rpc") or {})
                        plan = node.onchain.settlement_rpc_plan(
                            task,
                            settlement_preview=settlement,
                            settlement_ledger=settlement_ledger,
                            rpc=rpc_options,
                        )
                        resolve_live = bool(payload.get("resolve_live"))
                        if resolve_live:
                            steps: list[dict[str, Any]] = []
                            for step in plan["steps"]:
                                live_results: dict[str, Any] = {}
                                for probe in step["probes"]:
                                    rpc_url = str(step["rpc_payload"].get("rpc_url") or "").strip()
                                    if not rpc_url:
                                        raise ValueError("rpc_url is required for resolve_live")
                                    live_results[probe["name"]] = node._chain_rpc_call(
                                        rpc_url,
                                        probe["request"],
                                        timeout=float(payload.get("timeout_seconds") or 10),
                                    )
                                planned_rpc_payload = node.onchain.apply_rpc_probe_results(step["rpc_payload"], live_results)
                                steps.append(
                                    {
                                        **step,
                                        "rpc_payload": planned_rpc_payload,
                                        "live_results": live_results,
                                    }
                                )
                            plan["steps"] = steps
                            plan["resolved_live"] = True
                        else:
                            plan["resolved_live"] = False
                        signed_plan = node._sign_document(
                            plan,
                            hmac_scope="onchain-settlement-rpc-plan",
                            identity_namespace="agentcoin-onchain-settlement-rpc-plan",
                        )
                        self._json_response(HTTPStatus.OK, {"plan": signed_plan})
                        return
                    if self.path == "/v1/onchain/settlement-raw-bundle":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        task_id = str(payload.get("task_id") or "").strip()
                        if not task_id:
                            raise ValueError("task_id is required")
                        task = node.store.get_task(task_id)
                        if not task:
                            raise ValueError("task not found")
                        settlement = node._task_settlement_preview(task)
                        if not settlement:
                            raise ValueError("task is not bound to onchain settlement")
                        settlement_ledger = node._task_settlement_ledger(task)
                        rpc_options = dict(payload.get("rpc") or {})
                        plan = node.onchain.settlement_rpc_plan(
                            task,
                            settlement_preview=settlement,
                            settlement_ledger=settlement_ledger,
                            rpc=rpc_options,
                        )
                        bundle = node.onchain.settlement_raw_bundle(
                            plan,
                            raw_transactions=list(payload.get("raw_transactions") or []),
                            rpc_url=str(payload.get("rpc_url") or "").strip() or None,
                        )
                        signed_bundle = node._sign_document(
                            bundle,
                            hmac_scope="onchain-settlement-raw-bundle",
                            identity_namespace="agentcoin-onchain-settlement-raw-bundle",
                        )
                        self._json_response(HTTPStatus.OK, {"bundle": signed_bundle})
                        return
                    if self.path == "/v1/onchain/settlement-relay":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        task_id = str(payload.get("task_id") or "").strip()
                        if not task_id:
                            raise ValueError("task_id is required")
                        relay = node._execute_settlement_relay(
                            task_id=task_id,
                            raw_transactions=list(payload.get("raw_transactions") or []),
                            rpc_options=dict(payload.get("rpc") or {}),
                            rpc_url=str(payload.get("rpc_url") or "").strip() or None,
                            timeout=float(payload.get("timeout_seconds") or 10),
                            continue_on_error=bool(payload.get("continue_on_error")),
                            resume_from_index=int(payload.get("resume_from_index") or 0),
                        )
                        relay = build_settlement_relay_receipt(
                            relay,
                            node_id=node.config.node_id,
                            operator_id=self._effective_operator_id(None, auth_context),
                            auth_context=auth_context,
                        )
                        signed_relay = node._sign_document(
                            relay,
                            hmac_scope="onchain-settlement-relay",
                            identity_namespace="agentcoin-onchain-settlement-relay",
                        )
                        self._json_response(HTTPStatus.OK, {"relay": signed_relay})
                        return
                    if self.path == "/v1/onchain/settlement-relay-queue":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        task_id = str(payload.get("task_id") or "").strip()
                        if not task_id:
                            raise ValueError("task_id is required")
                        task = node.store.get_task(task_id)
                        if not task:
                            raise ValueError("task not found")
                        if not task.get("payload", {}).get("_onchain"):
                            raise ValueError("task is not bound to onchain settlement")
                        settlement = node._task_settlement_preview(task)
                        if not settlement:
                            raise ValueError("task is not ready for onchain settlement")
                        queue_payload = {
                            "task_id": task_id,
                            "raw_transactions": list(payload.get("raw_transactions") or []),
                            "rpc": dict(payload.get("rpc") or {}),
                            "rpc_url": str(payload.get("rpc_url") or "").strip() or None,
                            "timeout_seconds": float(payload.get("timeout_seconds") or 10),
                            "continue_on_error": bool(payload.get("continue_on_error")),
                            "resume_from_index": int(payload.get("resume_from_index") or 0),
                        }
                        item = node.store.enqueue_settlement_relay(
                            task_id=task_id,
                            payload=queue_payload,
                            max_attempts=int(payload.get("max_attempts") or 3),
                            delay_seconds=int(payload.get("delay_seconds") or 0),
                        )
                        self._json_response(HTTPStatus.CREATED, {"item": item})
                        return
                    if self.path == "/v1/onchain/settlement-relay-queue/pause":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        queue_id = str(payload.get("queue_id") or "").strip()
                        if not queue_id:
                            raise ValueError("queue_id is required")
                        existing = node.store.get_settlement_relay_queue_item(queue_id)
                        if not existing:
                            raise ValueError("settlement relay queue item not found")
                        item = node.store.pause_settlement_relay_queue_item(queue_id)
                        if not item or item.get("status") != "paused":
                            raise ValueError("queue item cannot be paused")
                        self._json_response(HTTPStatus.OK, {"item": item})
                        return
                    if self.path == "/v1/onchain/settlement-relay-queue/resume":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        queue_id = str(payload.get("queue_id") or "").strip()
                        if not queue_id:
                            raise ValueError("queue_id is required")
                        existing = node.store.get_settlement_relay_queue_item(queue_id)
                        if not existing:
                            raise ValueError("settlement relay queue item not found")
                        task = node.store.get_task(str(existing.get("task_id") or ""))
                        if not task:
                            raise ValueError("task not found")
                        settlement = node._task_settlement_preview(task)
                        if not settlement:
                            raise ValueError("task is not ready for onchain settlement")
                        item = node.store.resume_settlement_relay_queue_item(
                            queue_id,
                            delay_seconds=int(payload.get("delay_seconds") or 0),
                        )
                        if not item or item.get("status") != "queued":
                            raise ValueError("queue item cannot be resumed")
                        self._json_response(HTTPStatus.OK, {"item": item})
                        return
                    if self.path == "/v1/onchain/settlement-relay-queue/requeue":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        queue_id = str(payload.get("queue_id") or "").strip()
                        if not queue_id:
                            raise ValueError("queue_id is required")
                        existing = node.store.get_settlement_relay_queue_item(queue_id)
                        if not existing:
                            raise ValueError("settlement relay queue item not found")
                        task_id = str(existing.get("task_id") or "").strip()
                        task = node.store.get_task(task_id)
                        if not task:
                            raise ValueError("task not found")
                        settlement = node._task_settlement_preview(task)
                        if not settlement:
                            raise ValueError("task is not ready for onchain settlement")
                        queue_payload = node._merge_settlement_relay_queue_payload(
                            dict(existing.get("payload") or {}),
                            payload,
                            task_id=task_id,
                        )
                        item = node.store.requeue_settlement_relay_queue_item(
                            queue_id,
                            delay_seconds=int(payload.get("delay_seconds") or 0),
                            payload=queue_payload,
                            max_attempts=int(payload.get("max_attempts")) if payload.get("max_attempts") is not None else None,
                        )
                        if not item or item.get("status") != "queued":
                            raise ValueError("queue item cannot be requeued")
                        self._json_response(HTTPStatus.OK, {"item": item})
                        return
                    if self.path == "/v1/onchain/settlement-relay-queue/cancel":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        queue_id = str(payload.get("queue_id") or "").strip()
                        if not queue_id:
                            raise ValueError("queue_id is required")
                        existing = node.store.get_settlement_relay_queue_item(queue_id)
                        if not existing:
                            raise ValueError("settlement relay queue item not found")
                        item = node.store.cancel_settlement_relay_queue_item(queue_id)
                        if not item or item.get("status") != "dead-letter":
                            raise ValueError("queue item cannot be cancelled")
                        self._json_response(HTTPStatus.OK, {"item": item})
                        return
                    if self.path == "/v1/onchain/settlement-relay-queue/delete":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        queue_id = str(payload.get("queue_id") or "").strip()
                        if not queue_id:
                            raise ValueError("queue_id is required")
                        existing = node.store.get_settlement_relay_queue_item(queue_id)
                        if not existing:
                            raise ValueError("settlement relay queue item not found")
                        ok = node.store.delete_settlement_relay_queue_item(queue_id)
                        self._json_response(HTTPStatus.OK, {"ok": ok})
                        return
                    if self.path == "/v1/onchain/settlement-relays/reconcile":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        relay_id = str(payload.get("relay_id") or "").strip()
                        task_id = str(payload.get("task_id") or "").strip()
                        relay_record = None
                        if relay_id:
                            relay_record = node.store.get_settlement_relay(relay_id)
                        elif task_id:
                            relay_record = node.store.get_latest_settlement_relay(task_id)
                        else:
                            raise ValueError("relay_id or task_id is required")
                        if not relay_record:
                            raise ValueError("settlement relay not found")
                        item = node.reconcile_settlement_relay(
                            str(relay_record.get("id") or relay_id),
                            rpc_url=str(payload.get("rpc_url") or "").strip() or None,
                            timeout=float(payload.get("timeout_seconds") or 10),
                        )
                        self._json_response(HTTPStatus.OK, {"item": item})
                        return
                    if self.path == "/v1/onchain/settlement-relays/replay":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        relay_id = str(payload.get("relay_id") or "").strip()
                        task_id = str(payload.get("task_id") or "").strip()
                        relay_record = None
                        if relay_id:
                            relay_record = node.store.get_settlement_relay(relay_id)
                        elif task_id:
                            relay_record = node.store.get_latest_settlement_relay(task_id)
                        else:
                            raise ValueError("relay_id or task_id is required")
                        if not relay_record:
                            raise ValueError("settlement relay not found")
                        raw_transactions = list(payload.get("raw_transactions") or [])
                        if not raw_transactions:
                            raw_transactions = node._rebuild_raw_transactions_from_relay_record(relay_record)
                        relay = node._execute_settlement_relay(
                            task_id=str(relay_record.get("task_id") or task_id),
                            raw_transactions=raw_transactions,
                            rpc_options=dict(payload.get("rpc") or {}),
                            rpc_url=str(payload.get("rpc_url") or "").strip() or None,
                            timeout=float(payload.get("timeout_seconds") or 10),
                            continue_on_error=bool(payload.get("continue_on_error")),
                            resume_from_index=int(payload.get("resume_from_index") or relay_record.get("next_index") or 0),
                            retry_count=int(relay_record.get("retry_count") or 0) + 1,
                            resumed_from_relay_id=str(relay_record.get("id") or ""),
                        )
                        relay = build_settlement_relay_receipt(
                            relay,
                            node_id=node.config.node_id,
                            operator_id=self._effective_operator_id(None, auth_context),
                            auth_context=auth_context,
                        )
                        signed_relay = node._sign_document(
                            relay,
                            hmac_scope="onchain-settlement-relay",
                            identity_namespace="agentcoin-onchain-settlement-relay",
                        )
                        self._json_response(HTTPStatus.OK, {"relay": signed_relay})
                        return
                    if self.path == "/v1/workflows/fanout":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        parent_task_id = str(payload.get("parent_task_id") or "")
                        if not parent_task_id:
                            raise ValueError("parent_task_id is required")
                        parent_task = node.store.get_task(parent_task_id)
                        if not parent_task:
                            raise ValueError("parent task not found")
                        workflow_id = str(parent_task.get("workflow_id") or parent_task.get("id") or parent_task_id)
                        operator_id = self._effective_operator_id(
                            str(payload.get("operator_id") or "").strip() or None,
                            auth_context,
                        )
                        reason = str(payload.get("reason") or "workflow fanout")
                        operator_payload = dict(payload.get("payload") or {})
                        before_summary = node.store.summarize_workflow(workflow_id)
                        subtasks = [TaskEnvelope.from_dict(item) for item in list(payload.get("subtasks") or [])]
                        created = node.store.create_subtasks(parent_task_id, subtasks)
                        after_summary = node.store.summarize_workflow(workflow_id)
                        action = node._record_workflow_governance_action(
                            workflow_id=workflow_id,
                            action_type="workflow-fanout",
                            operator_id=operator_id,
                            reason=reason,
                            payload={
                                "parent_task_id": parent_task_id,
                                "spawned_task_ids": [item["id"] for item in created],
                                "subtasks": [
                                    {"id": item["id"], "branch": item["branch"], "role": item["role"]}
                                    for item in created
                                ],
                                "context": operator_payload,
                            },
                            reason_codes=node._ordered_unique_strings("workflow-fanout", f"subtasks-{len(created)}"),
                            target={
                                "kind": "workflow-fanout",
                                "workflow_id": workflow_id,
                                "parent_task_id": parent_task_id,
                            },
                            mutation={
                                "subtask_count": len(created),
                                "spawned_task_ids": [item["id"] for item in created],
                                "parent_completed": bool(parent_task.get("status") in {"queued", "leased"}),
                            },
                            auth_context=auth_context,
                            before_state=before_summary,
                            after_state=after_summary,
                            task_id=parent_task_id,
                        )
                        self._json_response(HTTPStatus.CREATED, {"items": created, "action": action})
                        return
                    if self.path == "/v1/workflows/review-gate":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        workflow_id = str(payload.get("workflow_id") or "")
                        if not workflow_id:
                            raise ValueError("workflow_id is required")
                        operator_id = self._effective_operator_id(
                            str(payload.get("operator_id") or "").strip() or None,
                            auth_context,
                        )
                        reason = str(payload.get("reason") or "workflow review gate update")
                        operator_payload = dict(payload.get("payload") or {})
                        before_summary = node.store.summarize_workflow(workflow_id)
                        reviews: list[TaskEnvelope] = []
                        attach_git_context = bool(payload.get("attach_git_context"))
                        git_base_ref = str(payload.get("git_base_ref") or "HEAD")
                        git_target_ref = payload.get("git_target_ref")
                        for item in list(payload.get("reviews") or []):
                            review = node._normalize_task(TaskEnvelope.from_dict(item), node.config)
                            if attach_git_context:
                                review.payload["_git"] = node._require_git().task_context(base_ref=git_base_ref, target_ref=git_target_ref)
                                review.payload.setdefault("_review", {})
                                review.payload["_review"].setdefault("base_ref", git_base_ref)
                                review.payload["_review"].setdefault("head_ref", git_target_ref or review.payload["_git"].get("head_ref"))
                                review.payload["_review"].setdefault("base_sha", review.payload["_git"].get("base_sha"))
                                review.payload["_review"].setdefault("head_sha", review.payload["_git"].get("target_sha"))
                            reviews.append(review)
                        created = node.store.create_review_tasks(workflow_id, reviews)
                        after_summary = node.store.summarize_workflow(workflow_id)
                        action = node._record_workflow_governance_action(
                            workflow_id=workflow_id,
                            action_type="workflow-review-gate",
                            operator_id=operator_id,
                            reason=reason,
                            payload={
                                "review_task_ids": [item["id"] for item in created],
                                "target_task_ids": [
                                    str(item.get("payload", {}).get("_review", {}).get("target_task_id") or "")
                                    for item in created
                                ],
                                "context": operator_payload,
                            },
                            reason_codes=node._ordered_unique_strings("workflow-review-gate", f"reviews-{len(created)}"),
                            target={"kind": "workflow-review-gate", "workflow_id": workflow_id},
                            mutation={
                                "review_count": len(created),
                                "review_task_ids": [item["id"] for item in created],
                            },
                            auth_context=auth_context,
                            before_state=before_summary,
                            after_state=after_summary,
                        )
                        self._json_response(HTTPStatus.CREATED, {"items": created, "action": action})
                        return
                    if self.path == "/v1/workflows/merge":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        workflow_id = str(payload.get("workflow_id") or "")
                        if not workflow_id:
                            raise ValueError("workflow_id is required")
                        operator_id = self._effective_operator_id(
                            str(payload.get("operator_id") or "").strip() or None,
                            auth_context,
                        )
                        reason = str(payload.get("reason") or "workflow merge task created")
                        operator_payload = dict(payload.get("payload") or {})
                        before_summary = node.store.summarize_workflow(workflow_id)
                        parent_task_ids = list(payload.get("parent_task_ids") or [])
                        raw_task = dict(payload.get("task") or {})
                        if "kind" not in raw_task:
                            raw_task["kind"] = "merge"
                        task = node._normalize_task(TaskEnvelope.from_dict(raw_task), node.config)
                        task.workflow_id = workflow_id
                        protected_branches = [str(item) for item in list(payload.get("protected_branches") or []) if str(item).strip()]
                        if protected_branches:
                            merge_policy = dict(task.payload.get("_merge_policy") or {})
                            merge_policy["protected_branches"] = protected_branches
                            merge_policy["required_approvals_per_branch"] = int(payload.get("required_approvals_per_branch") or 0)
                            merge_policy["required_human_approvals_per_branch"] = int(
                                payload.get("required_human_approvals_per_branch") or 0
                            )
                            merge_policy["required_ai_approvals_per_branch"] = int(
                                payload.get("required_ai_approvals_per_branch") or 0
                            )
                            task.payload["_merge_policy"] = merge_policy
                        if node.git and (bool(payload.get("attach_git_context")) or any(node.store.get_task(parent_id) for parent_id in parent_task_ids)):
                            parent_contexts: list[dict[str, Any]] = []
                            for parent_id in parent_task_ids:
                                parent = node.store.get_task(parent_id)
                                if parent and parent.get("payload", {}).get("_git"):
                                    parent_contexts.append(dict(parent["payload"]["_git"]))
                            git_base_ref = str(payload.get("git_base_ref") or (parent_contexts[0].get("base_ref") if parent_contexts else "HEAD"))
                            git_target_ref = str(
                                payload.get("git_target_ref")
                                or task.payload.get("_git", {}).get("target_ref")
                                or task.branch
                                or (parent_contexts[-1].get("target_ref") if parent_contexts else "HEAD")
                            )
                            task.payload["_git"] = node._require_git().merge_proof_context(
                                base_ref=git_base_ref,
                                target_ref=git_target_ref,
                                parent_contexts=parent_contexts,
                                parent_task_ids=parent_task_ids,
                            )
                        created = node.store.create_merge_task(workflow_id, parent_task_ids, task)
                        after_summary = node.store.summarize_workflow(workflow_id)
                        action = node._record_workflow_governance_action(
                            workflow_id=workflow_id,
                            action_type="workflow-merge",
                            operator_id=operator_id,
                            reason=reason,
                            payload={
                                "merge_task_id": created["id"],
                                "parent_task_ids": list(parent_task_ids),
                                "protected_branches": list(protected_branches),
                                "context": operator_payload,
                            },
                            reason_codes=node._ordered_unique_strings(
                                "workflow-merge",
                                f"parents-{len(parent_task_ids)}",
                                "merge-policy-protected" if protected_branches else None,
                            ),
                            target={
                                "kind": "workflow-merge-task",
                                "workflow_id": workflow_id,
                                "merge_task_id": created["id"],
                            },
                            mutation={
                                "parent_count": len(parent_task_ids),
                                "merge_task_id": created["id"],
                                "protected_branches": list(protected_branches),
                            },
                            auth_context=auth_context,
                            before_state=before_summary,
                            after_state=after_summary,
                            task_id=created["id"],
                        )
                        self._json_response(HTTPStatus.CREATED, {"task": created, "action": action})
                        return
                    if self.path == "/v1/workflows/finalize":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        workflow_id = str(payload.get("workflow_id") or "")
                        if not workflow_id:
                            raise ValueError("workflow_id is required")
                        operator_id = self._effective_operator_id(
                            str(payload.get("operator_id") or "").strip() or None,
                            auth_context,
                        )
                        reason = str(payload.get("reason") or "workflow finalized")
                        operator_payload = dict(payload.get("payload") or {})
                        before_summary = node.store.summarize_workflow(workflow_id)
                        finalized = node.store.finalize_workflow(workflow_id)
                        status = HTTPStatus.OK if finalized.get("ok") else HTTPStatus.CONFLICT
                        if finalized.get("ok"):
                            action = node._record_workflow_governance_action(
                                workflow_id=workflow_id,
                                action_type="workflow-finalize",
                                operator_id=operator_id,
                                reason=reason,
                                payload={
                                    "final_status": finalized.get("status"),
                                    "finalized_at": finalized.get("finalized_at"),
                                    "context": operator_payload,
                                },
                                reason_codes=node._ordered_unique_strings(
                                    "workflow-finalize",
                                    f"status-{finalized.get('status')}",
                                ),
                                target={"kind": "workflow-state", "workflow_id": workflow_id},
                                mutation={
                                    "finalized": True,
                                    "status": finalized.get("status"),
                                    "finalizable_before": bool(before_summary.get("finalizable")),
                                },
                                auth_context=auth_context,
                                before_state=before_summary,
                                after_state=finalized.get("summary"),
                            )
                            self._json_response(status, {**finalized, "action": action})
                            return
                        self._json_response(status, finalized)
                        return
                    if self.path == "/v1/tasks/dispatch":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/tasks/dispatch"},
                        ):
                            return
                        payload = self._read_json()
                        task = node._normalize_task(TaskEnvelope.from_dict(payload), node.config)
                        if task.sender == "local":
                            task.sender = node.config.node_id
                        if bool(payload.get("attach_onchain_context")):
                            task = node._bind_onchain_context(task, job_id=payload.get("onchain_job_id"))
                        prefer_local = bool(payload.get("prefer_local"))
                        target = None
                        if task.deliver_to:
                            target = {"target_type": "explicit", "target_ref": task.deliver_to}
                        else:
                            target = node.select_dispatch_target_for_task(task, prefer_local=prefer_local)
                            if not target:
                                self._json_response(
                                    HTTPStatus.CONFLICT,
                                    {"error": "no dispatch target found", "required_capabilities": task.required_capabilities},
                                )
                                return
                            if target["target_type"] == "peer":
                                task.deliver_to = target["target_ref"]
                                task.delivery_status = "remote-pending"
                        node._persist_task_delivery(task, dispatch_mode="planner" if task.deliver_to else None)
                        self._json_response(HTTPStatus.CREATED, {"task": task.to_dict(), "target": target})
                        return
                    if self.path == "/v1/bridges/import":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        protocol = str(payload.get("protocol") or "").strip()
                        operator_id = self._effective_operator_id(
                            str(payload.get("operator_id") or "").strip() or None,
                            auth_context,
                        )
                        message = dict(payload.get("message") or {})
                        task_overrides = dict(payload.get("task_overrides") or {})
                        dispatch = bool(payload.get("dispatch"))
                        prefer_local = bool(payload.get("prefer_local"))
                        task = node._normalize_task(node.bridges.import_task(protocol, message, task_overrides), node.config)
                        if bool(payload.get("attach_onchain_context")):
                            task = node._bind_onchain_context(task, job_id=payload.get("onchain_job_id"))
                        dispatch_target = None
                        if dispatch:
                            if task.deliver_to:
                                dispatch_target = {"target_type": "explicit", "target_ref": task.deliver_to}
                            else:
                                dispatch_target = node.select_dispatch_target_for_task(task, prefer_local=prefer_local)
                                if not dispatch_target:
                                    self._json_response(
                                        HTTPStatus.CONFLICT,
                                        {"error": "no dispatch target found", "required_capabilities": task.required_capabilities},
                                    )
                                    return
                                if dispatch_target["target_type"] == "peer":
                                    task.deliver_to = dispatch_target["target_ref"]
                                    task.delivery_status = "remote-pending"
                        node._persist_task_delivery(task, dispatch_mode="bridge" if task.deliver_to else None)
                        task_dict = task.to_dict()
                        action = node._record_bridge_governance_action(
                            task=task_dict,
                            protocol=protocol,
                            action_type="bridge-import",
                            operator_id=operator_id,
                            reason=str(payload.get("reason") or f"bridge import {protocol or 'message'}"),
                            payload={
                                **dict(payload.get("payload") or {}),
                                "dispatch": dispatch,
                                "prefer_local": prefer_local,
                                "target": dispatch_target,
                                "attach_onchain_context": bool(payload.get("attach_onchain_context")),
                            },
                            reason_codes=node._ordered_unique_strings(
                                f"protocol-{protocol.lower()}" if protocol else None,
                                "dispatch-requested" if dispatch else "dispatch-skipped",
                                "target-explicit" if dispatch_target and dispatch_target.get("target_type") == "explicit" else None,
                                "target-peer" if dispatch_target and dispatch_target.get("target_type") == "peer" else None,
                                "target-local" if dispatch_target and dispatch_target.get("target_type") == "local" else None,
                                "onchain-context-attached" if bool(payload.get("attach_onchain_context")) else None,
                            ),
                            target={
                                "kind": "bridge-task",
                                "protocol": protocol,
                                "task_id": task_dict.get("id"),
                                "workflow_id": task_dict.get("workflow_id"),
                            },
                            mutation={
                                "dispatch": dispatch,
                                "delivery_status": task_dict.get("delivery_status"),
                                "deliver_to": task_dict.get("deliver_to"),
                            },
                            auth_context=auth_context,
                            evidence={
                                "required_capabilities": list(task_dict.get("required_capabilities") or []),
                                "sender": task_dict.get("sender"),
                            },
                            after_state=task_dict,
                        )
                        self._json_response(
                            HTTPStatus.CREATED,
                            {
                                "task": task_dict,
                                "target": dispatch_target,
                                "protocol": protocol,
                                "dispatch": dispatch,
                                "action": action,
                            },
                        )
                        return
                    if self.path == "/v1/tasks/dispatch/evaluate":
                        if not self._require_local_client_or_auth(
                            allow_endpoints={"/v1/tasks/dispatch/evaluate"},
                        ):
                            return
                        payload = self._read_json()
                        task = node._normalize_task(TaskEnvelope.from_dict(payload), node.config)
                        if task.sender == "local":
                            task.sender = node.config.node_id
                        prefer_local = bool(payload.get("prefer_local"))
                        self._json_response(
                            HTTPStatus.OK,
                            {
                                "task": task.to_dict(),
                                "prefer_local": prefer_local,
                                "requirements": node._task_dispatch_requirements(task),
                                "candidates": node.dispatch_candidates_for_task(
                                    task,
                                    prefer_local=prefer_local,
                                    include_blocked=True,
                                ),
                            },
                        )
                        return
                    if self.path == "/v1/peer-health/cooldown":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        peer_id = str(payload.get("peer_id") or "").strip()
                        if not peer_id:
                            raise ValueError("peer_id is required")
                        seconds = int(payload.get("cooldown_seconds") or node.config.dispatch_peer_cooldown_seconds)
                        state = node.store.set_peer_dispatch_state(
                            peer_id,
                            cooldown_seconds=seconds,
                            reason=str(payload.get("reason") or "manual cooldown"),
                            metadata=dict(payload.get("payload") or {}),
                        )
                        self._json_response(HTTPStatus.OK, state)
                        return
                    if self.path == "/v1/peer-health/blacklist":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        peer_id = str(payload.get("peer_id") or "").strip()
                        if not peer_id:
                            raise ValueError("peer_id is required")
                        seconds = int(payload.get("blacklist_seconds") or node.config.dispatch_peer_blacklist_seconds)
                        state = node.store.set_peer_dispatch_state(
                            peer_id,
                            blacklist_seconds=seconds,
                            reason=str(payload.get("reason") or "manual blacklist"),
                            metadata=dict(payload.get("payload") or {}),
                        )
                        self._json_response(HTTPStatus.OK, state)
                        return
                    if self.path == "/v1/peer-health/clear":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        peer_id = str(payload.get("peer_id") or "").strip()
                        if not peer_id:
                            raise ValueError("peer_id is required")
                        state = node.store.set_peer_dispatch_state(
                            peer_id,
                            clear=True,
                            reason=str(payload.get("reason") or "manual clear"),
                            metadata=dict(payload.get("payload") or {}),
                        )
                        self._json_response(HTTPStatus.OK, state)
                        return
                    if self.path == "/v1/peers/identity-trust/apply":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        peer_id = str(payload.get("peer_id") or "").strip()
                        if not peer_id:
                            raise ValueError("peer_id is required")
                        operator_id = self._effective_operator_id(
                            str(payload.get("operator_id") or "").strip() or None,
                            auth_context,
                        )
                        result = node.apply_peer_identity_trust_update(
                            peer_id=peer_id,
                            actions=list(payload.get("actions") or []),
                            operator_id=operator_id,
                            reason=str(payload.get("reason") or "manual peer identity trust update"),
                            persist_to_config=bool(payload.get("persist_to_config")),
                            preview_only=bool(payload.get("preview_only")),
                            context=dict(payload.get("payload") or {}),
                            auth_context=auth_context,
                        )
                        self._json_response(HTTPStatus.OK, result)
                        return
                    if self.path == "/v1/peers/identity-trust/export":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        peer_id = str(payload.get("peer_id") or "").strip() or None
                        result = node.export_peer_identity_trust_reconciliation(
                            peer_id=peer_id,
                            actions=list(payload.get("actions") or []),
                            include_preview=bool(payload.get("include_preview", True)),
                        )
                        self._json_response(HTTPStatus.OK, result)
                        return
                    if self.path == "/v1/bridges/export":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        protocol = str(payload.get("protocol") or "").strip()
                        task_id = str(payload.get("task_id") or "").strip()
                        if not task_id:
                            raise ValueError("task_id is required")
                        task = node.store.get_task(task_id)
                        if not task:
                            raise ValueError("task not found")
                        operator_id = self._effective_operator_id(
                            str(payload.get("operator_id") or "").strip() or None,
                            auth_context,
                        )
                        exported = node.bridges.export_message(protocol, task, dict(payload.get("result") or {}) or task.get("result"))
                        action = node._record_bridge_governance_action(
                            task=task,
                            protocol=protocol,
                            action_type="bridge-export",
                            operator_id=operator_id,
                            reason=str(payload.get("reason") or f"bridge export {protocol or 'message'}"),
                            payload={
                                **dict(payload.get("payload") or {}),
                                "has_result_override": bool(payload.get("result")),
                            },
                            reason_codes=node._ordered_unique_strings(
                                f"protocol-{protocol.lower()}" if protocol else None,
                                "result-override" if bool(payload.get("result")) else "task-result-export",
                            ),
                            target={
                                "kind": "bridge-task",
                                "protocol": protocol,
                                "task_id": task.get("id"),
                                "workflow_id": task.get("workflow_id"),
                            },
                            mutation={
                                "status": task.get("status"),
                                "deliver_to": task.get("deliver_to"),
                            },
                            auth_context=auth_context,
                            evidence={
                                "required_capabilities": list(task.get("required_capabilities") or []),
                                "sender": task.get("sender"),
                            },
                            before_state=task,
                            after_state=exported,
                        )
                        self._json_response(HTTPStatus.OK, {**exported, "action": action})
                        return
                    if self.path == "/v1/tasks/claim":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        worker_id = str(payload.get("worker_id") or "").strip()
                        if not worker_id:
                            raise ValueError("worker_id is required")
                        lease_seconds = int(payload.get("lease_seconds") or 60)
                        worker_capabilities = list(payload.get("worker_capabilities") or [])
                        task = node.store.claim_task(
                            worker_id=worker_id,
                            worker_capabilities=worker_capabilities,
                            lease_seconds=lease_seconds,
                        )
                        self._json_response(HTTPStatus.OK, {"task": task})
                        return
                    if self.path == "/v1/tasks/lease/renew":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        ok = node.store.renew_task_lease(
                            task_id=str(payload.get("task_id") or ""),
                            worker_id=str(payload.get("worker_id") or ""),
                            lease_token=str(payload.get("lease_token") or ""),
                            lease_seconds=int(payload.get("lease_seconds") or 60),
                        )
                        self._json_response(HTTPStatus.OK, {"ok": ok})
                        return
                    if self.path == "/v1/tasks/ack":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        task_id = str(payload.get("task_id") or "")
                        task = node.store.get_task(task_id)
                        result_payload = dict(payload.get("result") or {})
                        if task:
                            result_payload = node._attach_result_receipts(task, result_payload)
                            onchain_receipt = node._task_onchain_receipt(task, result=result_payload)
                            if onchain_receipt:
                                result_payload["_onchain_receipt"] = onchain_receipt
                        ok = node.store.ack_task(
                            task_id=task_id,
                            worker_id=str(payload.get("worker_id") or ""),
                            lease_token=str(payload.get("lease_token") or ""),
                            success=bool(payload.get("success")),
                            result=result_payload,
                            error_message=payload.get("error_message"),
                            requeue=bool(payload.get("requeue")),
                        )
                        self._json_response(HTTPStatus.OK, {"ok": ok})
                        return
                    if self.path == "/v1/tasks/requeue":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        ok = node.store.requeue_dead_letter_task(
                            task_id=str(payload.get("task_id") or ""),
                            delay_seconds=int(payload.get("delay_seconds") or 0),
                        )
                        self._json_response(HTTPStatus.OK, {"ok": ok})
                        return
                    if self.path == "/v1/quarantines":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        actor_id = str(payload.get("actor_id") or "").strip()
                        if not actor_id:
                            raise ValueError("actor_id is required")
                        actor_type = str(payload.get("actor_type") or "worker")
                        scope = str(payload.get("scope") or "task-claim")
                        reason = str(payload.get("reason") or "manual quarantine")
                        operator_id = self._effective_operator_id(
                            str(payload.get("operator_id") or "").strip() or None,
                            auth_context,
                        )
                        context = dict(payload.get("payload") or {})
                        current_reputation = node.store.get_actor_reputation(actor_id, actor_type=actor_type)
                        result = node.store.set_actor_quarantine(
                            actor_id=actor_id,
                            actor_type=actor_type,
                            scope=scope,
                            reason=reason,
                            payload=context,
                            operator_id=operator_id,
                            receipt=node._governance_receipt(
                                action_type="quarantine-set",
                                actor_id=actor_id,
                                actor_type=actor_type,
                                operator_id=operator_id,
                                reason=reason,
                                payload={"scope": scope, "context": context},
                                reason_codes=node._ordered_unique_strings("manual-quarantine", f"scope-{scope}"),
                                target={"kind": "actor-quarantine", "actor_id": actor_id, "actor_type": actor_type},
                                mutation={
                                    "scope": scope,
                                    "quarantined": True,
                                    "previously_quarantined": bool(current_reputation.get("quarantined")),
                                },
                                auth_context=auth_context,
                                before_state=current_reputation,
                            ),
                        )
                        self._json_response(HTTPStatus.OK, result)
                        return
                    if self.path == "/v1/quarantines/release":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        actor_id = str(payload.get("actor_id") or "").strip()
                        if not actor_id:
                            raise ValueError("actor_id is required")
                        actor_type = str(payload.get("actor_type") or "worker")
                        reason = str(payload.get("reason") or "manual release")
                        operator_id = self._effective_operator_id(
                            str(payload.get("operator_id") or "").strip() or None,
                            auth_context,
                        )
                        context = dict(payload.get("payload") or {})
                        current_reputation = node.store.get_actor_reputation(actor_id, actor_type=actor_type)
                        result = node.store.release_actor_quarantine(
                            actor_id=actor_id,
                            actor_type=actor_type,
                            reason=reason,
                            payload=context,
                            operator_id=operator_id,
                            receipt=node._governance_receipt(
                                action_type="quarantine-release",
                                actor_id=actor_id,
                                actor_type=actor_type,
                                operator_id=operator_id,
                                reason=reason,
                                payload={"context": context},
                                reason_codes=node._ordered_unique_strings("manual-release"),
                                target={"kind": "actor-quarantine", "actor_id": actor_id, "actor_type": actor_type},
                                mutation={
                                    "quarantined": False,
                                    "previously_quarantined": bool(current_reputation.get("quarantined")),
                                },
                                auth_context=auth_context,
                                before_state=current_reputation,
                            ),
                        )
                        self._json_response(HTTPStatus.OK, result)
                        return
                    if self.path == "/v1/disputes":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        task_id = str(payload.get("task_id") or "").strip()
                        challenger_id = str(payload.get("challenger_id") or "").strip()
                        reason = str(payload.get("reason") or "").strip()
                        if not task_id or not challenger_id or not reason:
                            raise ValueError("task_id, challenger_id, and reason are required")
                        dispute_payload = dict(payload.get("payload") or {})
                        operator_id = self._effective_operator_id(
                            str(payload.get("operator_id") or "").strip() or None,
                            auth_context,
                        )
                        dispute_id = str(uuid4())
                        task = node.store.get_task(task_id)
                        if task and task.get("payload", {}).get("_git"):
                            dispute_payload.setdefault("_git", dict(task["payload"]["_git"]))
                        bond_amount_wei = (
                            str(payload.get("bond_amount_wei") or "").strip()
                            or str(node.config.challenge_bond_required_wei)
                        )
                        committee_quorum = int(payload.get("committee_quorum") or 0)
                        committee_deadline = str(payload.get("committee_deadline") or "").strip() or None
                        actor_id = str(payload.get("actor_id") or "").strip() or None
                        actor_type = str(payload.get("actor_type") or "worker").strip() or "worker"
                        severity = str(payload.get("severity") or "medium").strip() or "medium"
                        result = node.store.open_dispute(
                            dispute_id=dispute_id,
                            task_id=task_id,
                            challenger_id=challenger_id,
                            actor_id=actor_id,
                            actor_type=actor_type,
                            reason=reason,
                            evidence_hash=str(payload.get("evidence_hash") or "").strip() or None,
                            severity=severity,
                            bond_amount_wei=bond_amount_wei,
                            committee_quorum=committee_quorum,
                            committee_deadline=committee_deadline,
                            payload=dispute_payload,
                            operator_id=operator_id,
                            receipt=node._governance_receipt(
                                action_type="dispute-opened",
                                actor_id=actor_id or challenger_id,
                                actor_type=actor_type,
                                operator_id=operator_id,
                                reason=reason,
                                payload={
                                    "task_id": task_id,
                                    "challenger_id": challenger_id,
                                    "evidence_hash": str(payload.get("evidence_hash") or "").strip() or None,
                                    "bond_amount_wei": bond_amount_wei,
                                    "committee_quorum": committee_quorum,
                                    "committee_deadline": committee_deadline,
                                    "context": dispute_payload,
                                },
                                reason_codes=node._ordered_unique_strings(
                                    "dispute-opened",
                                    f"severity-{severity}",
                                    "bond-required" if bond_amount_wei != "0" else "bond-not-required",
                                    "committee-review" if committee_quorum > 0 else None,
                                ),
                                task_id=task_id,
                                target={
                                    "kind": "dispute",
                                    "dispute_id": dispute_id,
                                    "task_id": task_id,
                                    "challenger_id": challenger_id,
                                    "subject_actor_id": actor_id,
                                    "subject_actor_type": actor_type,
                                },
                                mutation={
                                    "status": "open",
                                    "severity": severity,
                                    "bond_amount_wei": bond_amount_wei,
                                    "committee_quorum": committee_quorum,
                                    "committee_deadline": committee_deadline,
                                },
                                auth_context=auth_context,
                                evidence={"evidence_hash": str(payload.get("evidence_hash") or "").strip() or None},
                            ),
                        )
                        task = task or node.store.get_task(task_id)
                        response_payload = dict(result)
                        response_payload["dispute"] = node._decorate_dispute(result["dispute"], task=task)
                        self._json_response(HTTPStatus.CREATED, response_payload)
                        return
                    if self.path == "/v1/disputes/vote":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        dispute_id = str(payload.get("dispute_id") or "").strip()
                        voter_id = str(payload.get("voter_id") or "").strip()
                        decision = str(payload.get("decision") or "").strip()
                        if not dispute_id or not voter_id or not decision:
                            raise ValueError("dispute_id, voter_id, and decision are required")
                        operator_id = self._effective_operator_id(None, auth_context)
                        result = node.store.vote_dispute(
                            dispute_id=dispute_id,
                            voter_id=voter_id,
                            decision=decision,
                            note=str(payload.get("note") or "").strip() or None,
                            payload=dict(payload.get("payload") or {}),
                            operator_id=operator_id,
                            resolution_receipt_factory=lambda details: node._governance_receipt(
                                action_type="dispute-resolved",
                                actor_id=str(details.get("actor_id") or details.get("challenger_id") or voter_id),
                                actor_type=str(details.get("actor_type") or "worker"),
                                operator_id=operator_id or str(details.get("operator_id") or "").strip() or None,
                                reason=str(details.get("resolution_reason") or "committee resolution"),
                                payload={
                                    "dispute_id": dispute_id,
                                    "task_id": details.get("task_id"),
                                    "resolution_status": details.get("resolution_status"),
                                    "committee_votes": list(details.get("committee_votes") or []),
                                    "committee_tally": dict(details.get("committee_tally") or {}),
                                    "committee_quorum": details.get("committee_quorum"),
                                },
                                reason_codes=node._ordered_unique_strings(
                                    "dispute-resolved",
                                    f"resolution-{details.get('resolution_status')}",
                                    "committee-resolution",
                                ),
                                task_id=str(details.get("task_id") or "") or None,
                                target={
                                    "kind": "dispute",
                                    "dispute_id": dispute_id,
                                    "task_id": details.get("task_id"),
                                    "challenger_id": details.get("challenger_id"),
                                    "subject_actor_id": details.get("actor_id"),
                                    "subject_actor_type": details.get("actor_type"),
                                },
                                mutation={
                                    "status": details.get("resolution_status"),
                                    "committee_quorum": details.get("committee_quorum"),
                                    "committee_votes_recorded": len(list(details.get("committee_votes") or [])),
                                },
                                auth_context=auth_context,
                                evidence={"evidence_hash": details.get("evidence_hash")},
                                before_state={
                                    "status": "open",
                                    "committee_quorum": details.get("committee_quorum"),
                                    "committee_tally": details.get("committee_tally"),
                                },
                            ),
                        )
                        if not result:
                            self._json_response(HTTPStatus.NOT_FOUND, {"error": "dispute not found"})
                            return
                        self._json_response(HTTPStatus.OK, {"ok": True, "dispute": node._decorate_dispute(result)})
                        return
                    if self.path == "/v1/disputes/resolve":
                        auth_context = self._require_auth()
                        if not auth_context:
                            return
                        payload = self._read_json()
                        dispute_id = str(payload.get("dispute_id") or "").strip()
                        resolution_status = str(payload.get("resolution_status") or "").strip()
                        reason = str(payload.get("reason") or "").strip()
                        if not dispute_id or not resolution_status or not reason:
                            raise ValueError("dispute_id, resolution_status, and reason are required")
                        current_dispute = node.store.get_dispute(dispute_id)
                        if not current_dispute:
                            self._json_response(HTTPStatus.NOT_FOUND, {"error": "dispute not found"})
                            return
                        operator_id = self._effective_operator_id(
                            str(payload.get("operator_id") or "").strip() or None,
                            auth_context,
                        )
                        result = node.store.resolve_dispute(
                            dispute_id=dispute_id,
                            resolution_status=resolution_status,
                            reason=reason,
                            operator_id=operator_id,
                            payload=dict(payload.get("payload") or {}),
                            receipt=node._governance_receipt(
                                action_type="dispute-resolved",
                                actor_id=str(current_dispute.get("actor_id") or current_dispute.get("challenger_id") or ""),
                                actor_type=str(current_dispute.get("actor_type") or "worker"),
                                operator_id=operator_id,
                                reason=reason,
                                payload={
                                    "dispute_id": dispute_id,
                                    "task_id": current_dispute.get("task_id"),
                                    "resolution_status": resolution_status,
                                    "context": dict(payload.get("payload") or {}),
                                },
                                reason_codes=node._ordered_unique_strings(
                                    "dispute-resolved",
                                    f"resolution-{resolution_status.strip().lower()}",
                                    "committee-resolution" if operator_id and operator_id.startswith("committee:") else "operator-resolution",
                                ),
                                task_id=str(current_dispute.get("task_id") or "") or None,
                                target={
                                    "kind": "dispute",
                                    "dispute_id": dispute_id,
                                    "task_id": current_dispute.get("task_id"),
                                    "challenger_id": current_dispute.get("challenger_id"),
                                    "subject_actor_id": current_dispute.get("actor_id"),
                                    "subject_actor_type": current_dispute.get("actor_type"),
                                },
                                mutation={
                                    "status": resolution_status.strip().lower(),
                                    "committee_quorum": current_dispute.get("committee_quorum"),
                                    "bond_amount_wei": current_dispute.get("bond_amount_wei"),
                                },
                                auth_context=auth_context,
                                evidence={"evidence_hash": current_dispute.get("evidence_hash")},
                                before_state=current_dispute,
                            ),
                        )
                        if not result:
                            self._json_response(HTTPStatus.NOT_FOUND, {"error": "dispute not found"})
                            return
                        self._json_response(HTTPStatus.OK, {"ok": True, "dispute": node._decorate_dispute(result)})
                        return
                    if self.path == "/v1/git/branch":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        created = node._require_git().create_branch(
                            name=str(payload.get("name") or ""),
                            from_ref=str(payload.get("from_ref") or "HEAD"),
                            checkout=bool(payload.get("checkout")),
                        )
                        self._json_response(HTTPStatus.CREATED, created)
                        return
                    if self.path == "/v1/git/task-context":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        task_id = str(payload.get("task_id") or "").strip()
                        context = node._require_git().task_context(
                            base_ref=str(payload.get("base_ref") or "HEAD"),
                            target_ref=payload.get("target_ref"),
                        )
                        updated = False
                        if task_id:
                            task = node.store.get_task(task_id)
                            if not task:
                                raise ValueError("task not found")
                            merged_payload = dict(task["payload"])
                            merged_payload["_git"] = context
                            updated = node.store.update_task_payload(task_id, merged_payload)
                        self._json_response(HTTPStatus.OK, {"git": context, "task_id": task_id or None, "updated": updated})
                        return
                    if self.path == "/v1/inbox":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        sender = str(payload.get("sender") or "peer")
                        verification = node._verify_inbox_document(payload)
                        message_id, duplicate = node.store.receive_inbox(sender, payload)
                        if not duplicate:
                            local_payload = dict(payload)
                            local_payload["deliver_to"] = None
                            local_payload["delivery_status"] = "local"
                            local_payload["last_error"] = None
                            if verification:
                                local_payload.setdefault("payload", {})
                                local_payload["payload"]["_verification"] = verification
                            node.store.add_task(node._normalize_task(TaskEnvelope.from_dict(local_payload), node.config))
                        ack_id = str(uuid4())
                        node.store.save_delivery_receipt(ack_id, message_id, sender)
                        self._json_response(
                            HTTPStatus.CREATED,
                            node._sign_document(
                                {
                                "message_id": message_id,
                                "duplicate": duplicate,
                                "ack": {
                                    "ack_id": ack_id,
                                    "message_id": message_id,
                                },
                                "verified": bool(verification),
                                },
                                hmac_scope="delivery-receipt",
                                identity_namespace="agentcoin-receipt",
                            ),
                        )
                        return
                    if self.path == "/v1/outbox/flush":
                        if not self._require_auth():
                            return
                        flushed = node.flush_outbox()
                        self._json_response(HTTPStatus.OK, {"flushed": flushed, "stats": node.store.stats()})
                        return
                    if self.path == "/v1/outbox/requeue":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        ok = node.store.requeue_outbox(
                            message_id=str(payload.get("message_id") or ""),
                            delay_seconds=int(payload.get("delay_seconds") or 0),
                        )
                        self._json_response(HTTPStatus.OK, {"ok": ok})
                        return
                    if self.path == "/v1/peers/sync":
                        if not self._require_auth():
                            return
                        synced = node.sync_peer_cards()
                        self._json_response(HTTPStatus.OK, {"items": synced, "stats": node.store.stats()})
                        return
                    self._json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})
                except ValueError as exc:
                    self._json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except SignatureError as exc:
                    self._json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except json.JSONDecodeError:
                    self._json_response(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})

            def log_message(self, format: str, *args: object) -> None:
                LOG.info("%s - %s", self.address_string(), format % args)

        return Handler

    def flush_outbox(self) -> int:
        delivered = 0
        for item in self.store.get_pending_outbox():
            started_at = time.monotonic()
            try:
                parsed = urlparse(item["target_url"])
                if parsed.scheme not in {"http", "https"}:
                    raise ValueError("unsupported target_url scheme")
                headers = {"Content-Type": "application/json"}
                if item["auth_token"]:
                    headers["Authorization"] = f"Bearer {item['auth_token']}"
                response_payload = self.transport.request_json(
                    item["target_url"],
                    method="POST",
                    payload=json.loads(item["payload_json"]),
                    headers=headers,
                    timeout=5,
                )
                if response_payload.get("ack", {}).get("message_id") != item["id"]:
                    raise ValueError("missing or invalid message ack")
                receipt_peer = self._resolve_outbox_peer(item)
                self._verify_receipt_payload(receipt_peer, response_payload)
                self.store.mark_outbox_delivered(item["id"])
                if receipt_peer:
                    self.store.record_peer_health(
                        receipt_peer.peer_id,
                        source="delivery",
                        success=True,
                        metadata={
                            "latency_ms": int((time.monotonic() - started_at) * 1000),
                            "target_url": item["target_url"],
                        },
                    )
                delivered += 1
            except (error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                receipt_peer = self._resolve_outbox_peer(item)
                if receipt_peer:
                    self.store.record_peer_health(
                        receipt_peer.peer_id,
                        source="delivery",
                        success=False,
                        error_message=str(exc),
                        cooldown_seconds=self.config.dispatch_peer_cooldown_seconds,
                        blacklist_after_failures=self.config.dispatch_peer_blacklist_after_failures,
                        blacklist_seconds=self.config.dispatch_peer_blacklist_seconds,
                        metadata={
                            "latency_ms": int((time.monotonic() - started_at) * 1000),
                            "target_url": item["target_url"],
                        },
                    )
                permanent = self.store.mark_outbox_failed(
                    item["id"],
                    int(item["attempts"]) + 1,
                    str(exc),
                    self.config.outbox_max_attempts,
                )
                task_id = item.get("task_id")
                if permanent and task_id:
                    task = self.store.get_task(task_id)
                    if task and self.config.local_dispatch_fallback and self._supports_capabilities(task["required_capabilities"]):
                        self.store.activate_local_fallback(task_id, str(exc))
                    else:
                        self.store.mark_task_delivery_dead_letter(task_id, str(exc))
        return delivered

    def _sync_loop(self) -> None:
        while not self._sync_stop.wait(self.config.sync_interval_seconds):
            self.sync_peer_cards()
            self.flush_outbox()

    def _settlement_relay_loop(self) -> None:
        poll_seconds = float(self.config.settlement_relay_poll_seconds or 0)
        if poll_seconds <= 0:
            return
        while not self._sync_stop.is_set():
            try:
                self.process_settlement_relay_queue()
            except Exception:
                LOG.exception("settlement relay queue loop failed")
            if self._sync_stop.wait(poll_seconds):
                break

    def _payment_relay_loop(self) -> None:
        poll_seconds = float(self.config.settlement_relay_poll_seconds or 0)
        if poll_seconds <= 0:
            return
        while not self._sync_stop.is_set():
            try:
                self.auto_requeue_dead_letter_payment_relays()
                self.process_payment_relay_queue()
            except Exception:
                LOG.exception("payment relay queue loop failed")
            if self._sync_stop.wait(poll_seconds):
                break

    def serve_forever(self) -> None:
        LOG.info("starting AgentCoin node on %s:%s", self.config.host, self.config.port)
        recovered = self.store.recover_running_settlement_relay_queue_items()
        if recovered:
            LOG.info("recovered %s running settlement relay queue item(s)", recovered)
        recovered_payment = self.store.recover_running_payment_relay_queue_items()
        if recovered_payment:
            LOG.info("recovered %s running payment relay queue item(s)", recovered_payment)
        self._sync_thread.start()
        if float(self.config.settlement_relay_poll_seconds or 0) > 0:
            self._settlement_relay_thread.start()
            self._payment_relay_thread.start()
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            LOG.info("received shutdown signal")
        finally:
            self._sync_stop.set()
            self._server.server_close()
            self.local_agents.shutdown()
            if self._sync_thread.is_alive():
                self._sync_thread.join(timeout=2)
            if self._settlement_relay_thread.is_alive():
                self._settlement_relay_thread.join(timeout=2)
            if self._payment_relay_thread.is_alive():
                self._payment_relay_thread.join(timeout=2)

    def shutdown(self) -> None:
        self._sync_stop.set()
        self.local_agents.shutdown()
        self._server.shutdown()
        self._server.server_close()
