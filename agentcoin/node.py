from __future__ import annotations

import json
import logging
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from agentcoin.bridges import BridgeRegistry
from agentcoin.config import NodeConfig, PeerConfig
from agentcoin.gitops import GitWorkspace
from agentcoin.models import TaskEnvelope, utc_now
from agentcoin.net import OutboundTransport
from agentcoin.onchain import OnchainRuntime
from agentcoin.receipts import (
    build_deterministic_execution_receipt,
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
    SignatureError,
    sign_document,
    sign_document_with_ssh,
    verify_document,
    verify_document_with_ssh,
)
from agentcoin.store import NodeStore

LOG = logging.getLogger("agentcoin.node")


class AgentCoinNode:
    def __init__(self, config: NodeConfig) -> None:
        self.config = config
        self.store = NodeStore(
            config.database_path,
            poaw_policy_version=config.poaw_policy_version,
            poaw_score_weights=config.poaw_score_weights,
        )
        self.git = GitWorkspace(config.git_root) if config.git_root else None
        self.transport = OutboundTransport(config.network)
        self.onchain = OnchainRuntime(config.onchain)
        self.bridges = BridgeRegistry(config.bridges)
        self.runtimes = RuntimeRegistry()
        self._server = ThreadingHTTPServer((config.host, config.port), self._build_handler())
        self._sync_stop = threading.Event()
        self._sync_thread = threading.Thread(target=self._sync_loop, name="agentcoin-outbox", daemon=True)

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
        return payload

    @staticmethod
    def _collapse_verification(results: dict[str, dict]) -> dict | None:
        if not results:
            return None
        if len(results) == 1:
            return next(iter(results.values()))
        return {"verified": True, **results}

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
        return bool(peer.signing_secret or (peer.identity_principal and peer.identity_public_key))

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
        if peer and peer.identity_principal and peer.identity_public_key:
            results["identity"] = verify_document_with_ssh(
                payload,
                public_key=peer.identity_public_key,
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
        payload: dict | None = None,
    ) -> dict:
        document = {
            "action_type": action_type,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "operator_id": operator_id,
            "reason": reason,
            "node_id": self.config.node_id,
            "payload": payload or {},
        }
        return self._sign_document(document, hmac_scope="governance-receipt", identity_namespace="agentcoin-governance")

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
        plan = self.onchain.settlement_rpc_plan(task, settlement_preview=settlement, rpc=rpc_options or {})
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

        class Handler(BaseHTTPRequestHandler):
            server_version = "AgentCoin/0.1"

            def _json_response(self, status: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    return {}
                if length > node.config.max_body_bytes:
                    raise ValueError("request body too large")
                raw = self.rfile.read(length)
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))

            def _require_auth(self) -> bool:
                configured = node.config.auth_token.strip()
                if not configured:
                    return True
                header = self.headers.get("Authorization", "")
                if header == f"Bearer {configured}":
                    return True
                self._json_response(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return False

            def do_GET(self) -> None:
                parsed_request = urlparse(self.path)
                path = parsed_request.path
                query = parse_qs(parsed_request.query)

                if path == "/healthz":
                    self._json_response(
                        HTTPStatus.OK,
                        {
                            "status": "ok",
                            "node_id": node.config.node_id,
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
                    self._json_response(
                        HTTPStatus.OK,
                        {
                            "items": node.store.list_disputes(
                                task_id=task_id,
                                challenger_id=challenger_id,
                                status=status_name,
                                limit=limit,
                            )
                        },
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
                            "disputes": node.store.list_disputes(task_id=task_id, limit=200),
                            "settlement_relays": node.store.list_settlement_relays(task_id=task_id, limit=200),
                            "settlement_relay_queue": node.store.list_settlement_relay_queue(task_id=task_id, limit=200),
                            "latest_settlement_relay": node.store.get_latest_settlement_relay(task_id),
                            "bridge_export_preview": export_preview,
                            "git_proof_bundle": git_proof_bundle,
                            "onchain_status": task.get("payload", {}).get("_onchain"),
                            "onchain_receipt": dict(task.get("result") or {}).get("_onchain_receipt"),
                            "onchain_intent_preview": onchain_preview,
                            "onchain_settlement_preview": node._task_settlement_preview(task),
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
                    self._json_response(HTTPStatus.OK, {"items": node.store.list_peer_cards()})
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
                    if self.path == "/v1/tasks":
                        if not self._require_auth():
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
                        if not self._require_auth():
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
                        if not self._require_auth():
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
                        rpc_options = dict(payload.get("rpc") or {})
                        plan = node.onchain.settlement_rpc_plan(task, settlement_preview=settlement, rpc=rpc_options)
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
                        rpc_options = dict(payload.get("rpc") or {})
                        plan = node.onchain.settlement_rpc_plan(task, settlement_preview=settlement, rpc=rpc_options)
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
                        if not self._require_auth():
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
                        relay = build_settlement_relay_receipt(relay, node_id=node.config.node_id)
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
                    if self.path == "/v1/onchain/settlement-relays/replay":
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
                        relay = build_settlement_relay_receipt(relay, node_id=node.config.node_id)
                        signed_relay = node._sign_document(
                            relay,
                            hmac_scope="onchain-settlement-relay",
                            identity_namespace="agentcoin-onchain-settlement-relay",
                        )
                        self._json_response(HTTPStatus.OK, {"relay": signed_relay})
                        return
                    if self.path == "/v1/workflows/fanout":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        parent_task_id = str(payload.get("parent_task_id") or "")
                        if not parent_task_id:
                            raise ValueError("parent_task_id is required")
                        subtasks = [TaskEnvelope.from_dict(item) for item in list(payload.get("subtasks") or [])]
                        created = node.store.create_subtasks(parent_task_id, subtasks)
                        self._json_response(HTTPStatus.CREATED, {"items": created})
                        return
                    if self.path == "/v1/workflows/review-gate":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        workflow_id = str(payload.get("workflow_id") or "")
                        if not workflow_id:
                            raise ValueError("workflow_id is required")
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
                        self._json_response(HTTPStatus.CREATED, {"items": created})
                        return
                    if self.path == "/v1/workflows/merge":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        workflow_id = str(payload.get("workflow_id") or "")
                        if not workflow_id:
                            raise ValueError("workflow_id is required")
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
                        self._json_response(HTTPStatus.CREATED, {"task": created})
                        return
                    if self.path == "/v1/workflows/finalize":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        workflow_id = str(payload.get("workflow_id") or "")
                        if not workflow_id:
                            raise ValueError("workflow_id is required")
                        finalized = node.store.finalize_workflow(workflow_id)
                        status = HTTPStatus.OK if finalized.get("ok") else HTTPStatus.CONFLICT
                        self._json_response(status, finalized)
                        return
                    if self.path == "/v1/tasks/dispatch":
                        if not self._require_auth():
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
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        protocol = str(payload.get("protocol") or "").strip()
                        message = dict(payload.get("message") or {})
                        task_overrides = dict(payload.get("task_overrides") or {})
                        dispatch = bool(payload.get("dispatch"))
                        prefer_local = bool(payload.get("prefer_local"))
                        task = node._normalize_task(node.bridges.import_task(protocol, message, task_overrides), node.config)
                        if bool(payload.get("attach_onchain_context")):
                            task = node._bind_onchain_context(task, job_id=payload.get("onchain_job_id"))
                        target = None
                        if dispatch:
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
                        node._persist_task_delivery(task, dispatch_mode="bridge" if task.deliver_to else None)
                        self._json_response(
                            HTTPStatus.CREATED,
                            {"task": task.to_dict(), "target": target, "protocol": protocol, "dispatch": dispatch},
                        )
                        return
                    if self.path == "/v1/tasks/dispatch/evaluate":
                        if not self._require_auth():
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
                    if self.path == "/v1/bridges/export":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        protocol = str(payload.get("protocol") or "").strip()
                        task_id = str(payload.get("task_id") or "").strip()
                        if not task_id:
                            raise ValueError("task_id is required")
                        task = node.store.get_task(task_id)
                        if not task:
                            raise ValueError("task not found")
                        exported = node.bridges.export_message(protocol, task, dict(payload.get("result") or {}) or task.get("result"))
                        self._json_response(HTTPStatus.OK, exported)
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
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        actor_id = str(payload.get("actor_id") or "").strip()
                        if not actor_id:
                            raise ValueError("actor_id is required")
                        actor_type = str(payload.get("actor_type") or "worker")
                        scope = str(payload.get("scope") or "task-claim")
                        reason = str(payload.get("reason") or "manual quarantine")
                        operator_id = str(payload.get("operator_id") or "").strip() or None
                        context = dict(payload.get("payload") or {})
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
                            ),
                        )
                        self._json_response(HTTPStatus.OK, result)
                        return
                    if self.path == "/v1/quarantines/release":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        actor_id = str(payload.get("actor_id") or "").strip()
                        if not actor_id:
                            raise ValueError("actor_id is required")
                        actor_type = str(payload.get("actor_type") or "worker")
                        reason = str(payload.get("reason") or "manual release")
                        operator_id = str(payload.get("operator_id") or "").strip() or None
                        context = dict(payload.get("payload") or {})
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
                            ),
                        )
                        self._json_response(HTTPStatus.OK, result)
                        return
                    if self.path == "/v1/disputes":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        task_id = str(payload.get("task_id") or "").strip()
                        challenger_id = str(payload.get("challenger_id") or "").strip()
                        reason = str(payload.get("reason") or "").strip()
                        if not task_id or not challenger_id or not reason:
                            raise ValueError("task_id, challenger_id, and reason are required")
                        dispute_payload = dict(payload.get("payload") or {})
                        task = node.store.get_task(task_id)
                        if task and task.get("payload", {}).get("_git"):
                            dispute_payload.setdefault("_git", dict(task["payload"]["_git"]))
                        result = node.store.open_dispute(
                            task_id=task_id,
                            challenger_id=challenger_id,
                            actor_id=str(payload.get("actor_id") or "").strip() or None,
                            actor_type=str(payload.get("actor_type") or "worker").strip() or "worker",
                            reason=reason,
                            evidence_hash=str(payload.get("evidence_hash") or "").strip() or None,
                            severity=str(payload.get("severity") or "medium").strip() or "medium",
                            bond_amount_wei=(
                                str(payload.get("bond_amount_wei") or "").strip()
                                or str(node.config.challenge_bond_required_wei)
                            ),
                            committee_quorum=int(payload.get("committee_quorum") or 0),
                            committee_deadline=str(payload.get("committee_deadline") or "").strip() or None,
                            payload=dispute_payload,
                        )
                        self._json_response(HTTPStatus.CREATED, result)
                        return
                    if self.path == "/v1/disputes/vote":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        dispute_id = str(payload.get("dispute_id") or "").strip()
                        voter_id = str(payload.get("voter_id") or "").strip()
                        decision = str(payload.get("decision") or "").strip()
                        if not dispute_id or not voter_id or not decision:
                            raise ValueError("dispute_id, voter_id, and decision are required")
                        result = node.store.vote_dispute(
                            dispute_id=dispute_id,
                            voter_id=voter_id,
                            decision=decision,
                            note=str(payload.get("note") or "").strip() or None,
                            payload=dict(payload.get("payload") or {}),
                        )
                        if not result:
                            self._json_response(HTTPStatus.NOT_FOUND, {"error": "dispute not found"})
                            return
                        self._json_response(HTTPStatus.OK, {"ok": True, "dispute": result})
                        return
                    if self.path == "/v1/disputes/resolve":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        dispute_id = str(payload.get("dispute_id") or "").strip()
                        resolution_status = str(payload.get("resolution_status") or "").strip()
                        reason = str(payload.get("reason") or "").strip()
                        if not dispute_id or not resolution_status or not reason:
                            raise ValueError("dispute_id, resolution_status, and reason are required")
                        result = node.store.resolve_dispute(
                            dispute_id=dispute_id,
                            resolution_status=resolution_status,
                            reason=reason,
                            operator_id=str(payload.get("operator_id") or "").strip() or None,
                            payload=dict(payload.get("payload") or {}),
                        )
                        if not result:
                            self._json_response(HTTPStatus.NOT_FOUND, {"error": "dispute not found"})
                            return
                        self._json_response(HTTPStatus.OK, {"ok": True, "dispute": result})
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

    def serve_forever(self) -> None:
        LOG.info("starting AgentCoin node on %s:%s", self.config.host, self.config.port)
        self._sync_thread.start()
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            LOG.info("received shutdown signal")
        finally:
            self._sync_stop.set()
            self._server.server_close()

    def shutdown(self) -> None:
        self._sync_stop.set()
        self._server.shutdown()
        self._server.server_close()
