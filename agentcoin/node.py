from __future__ import annotations

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from agentcoin.bridges import BridgeRegistry
from agentcoin.config import NodeConfig, PeerConfig
from agentcoin.gitops import GitWorkspace
from agentcoin.models import TaskEnvelope
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
        self.store = NodeStore(config.database_path)
        self.git = GitWorkspace(config.git_root) if config.git_root else None
        self.bridges = BridgeRegistry(config.bridges)
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
            try:
                req = request.Request(source_url, headers={"Accept": "application/json"}, method="GET")
                with request.urlopen(req, timeout=5) as resp:
                    if resp.status >= 300:
                        raise ValueError(f"peer returned status {resp.status}")
                    card = json.loads(resp.read().decode("utf-8"))
                verification = self._verify_peer_card(peer, card)
                self.store.save_peer_card(peer.peer_id, source_url, card)
                synced.append(
                    {
                        "peer_id": peer.peer_id,
                        "status": "ok",
                        "signed": bool(verification),
                        "hmac_signed": isinstance(verification, dict) and ("scope" in verification or "hmac" in verification),
                        "identity_signed": isinstance(verification, dict) and ("namespace" in verification or "identity" in verification),
                    }
                )
            except (error.URLError, TimeoutError, ValueError, json.JSONDecodeError, SignatureError) as exc:
                synced.append({"peer_id": peer.peer_id, "status": "error", "error": str(exc)})
        return synced

    def _supports_capabilities(self, capabilities: list[str]) -> bool:
        if not capabilities:
            return True
        return set(capabilities).issubset(set(self.config.capabilities))

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

    def select_dispatch_target(self, required_capabilities: list[str], prefer_local: bool = False) -> dict[str, str] | None:
        if prefer_local and self._supports_capabilities(required_capabilities):
            return {"target_type": "local", "target_ref": self.config.node_id}

        peer_cards = self.store.list_peer_cards()
        candidates: list[tuple[int, str]] = []
        for peer_card in peer_cards:
            peer_id = peer_card["peer_id"]
            card = peer_card["card"]
            capabilities = set(card.get("capabilities", []))
            if set(required_capabilities).issubset(capabilities):
                candidates.append((len(capabilities), peer_id))

        if candidates:
            _, peer_id = sorted(candidates, key=lambda item: (item[0], item[1]))[0]
            return {"target_type": "peer", "target_ref": peer_id}

        if self._supports_capabilities(required_capabilities):
            return {"target_type": "local", "target_ref": self.config.node_id}

        return None

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
                if path == "/v1/tasks":
                    self._json_response(HTTPStatus.OK, {"items": node.store.list_tasks()})
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
                if path == "/v1/bridges":
                    self._json_response(HTTPStatus.OK, {"items": node.bridges.list_bridges()})
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
                    self._json_response(HTTPStatus.OK, {"items": node.store.list_dead_letter_tasks()})
                    return
                if path == "/v1/workflows":
                    workflow_id = (query.get("workflow_id") or [""])[0]
                    if not workflow_id:
                        self._json_response(HTTPStatus.BAD_REQUEST, {"error": "workflow_id is required"})
                        return
                    self._json_response(HTTPStatus.OK, {"items": node.store.list_workflow_tasks(workflow_id)})
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
                    self._json_response(
                        HTTPStatus.OK,
                        {
                            "task": task,
                            "audits": node.store.list_execution_audits(task_id=task_id, limit=200),
                            "bridge_export_preview": export_preview,
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
                        node._persist_task_delivery(task)
                        self._json_response(HTTPStatus.CREATED, {"task": task.to_dict()})
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
                        prefer_local = bool(payload.get("prefer_local"))
                        target = None
                        if task.deliver_to:
                            target = {"target_type": "explicit", "target_ref": task.deliver_to}
                        else:
                            target = node.select_dispatch_target(task.required_capabilities, prefer_local=prefer_local)
                            if not target:
                                self._json_response(
                                    HTTPStatus.CONFLICT,
                                    {"error": "no dispatch target found", "required_capabilities": task.required_capabilities},
                                )
                                return
                            if target["target_type"] == "peer":
                                task.deliver_to = target["target_ref"]
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
                        target = None
                        if dispatch:
                            if task.deliver_to:
                                target = {"target_type": "explicit", "target_ref": task.deliver_to}
                            else:
                                target = node.select_dispatch_target(task.required_capabilities, prefer_local=prefer_local)
                                if not target:
                                    self._json_response(
                                        HTTPStatus.CONFLICT,
                                        {"error": "no dispatch target found", "required_capabilities": task.required_capabilities},
                                    )
                                    return
                                if target["target_type"] == "peer":
                                    task.deliver_to = target["target_ref"]
                        node._persist_task_delivery(task, dispatch_mode="bridge" if task.deliver_to else None)
                        self._json_response(
                            HTTPStatus.CREATED,
                            {"task": task.to_dict(), "target": target, "protocol": protocol, "dispatch": dispatch},
                        )
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
                        ok = node.store.ack_task(
                            task_id=str(payload.get("task_id") or ""),
                            worker_id=str(payload.get("worker_id") or ""),
                            lease_token=str(payload.get("lease_token") or ""),
                            success=bool(payload.get("success")),
                            result=dict(payload.get("result") or {}),
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
            try:
                parsed = urlparse(item["target_url"])
                if parsed.scheme not in {"http", "https"}:
                    raise ValueError("unsupported target_url scheme")
                body = item["payload_json"].encode("utf-8")
                headers = {"Content-Type": "application/json"}
                if item["auth_token"]:
                    headers["Authorization"] = f"Bearer {item['auth_token']}"
                req = request.Request(
                    item["target_url"],
                    data=body,
                    headers=headers,
                    method="POST",
                )
                with request.urlopen(req, timeout=5) as resp:
                    if resp.status >= 300:
                        raise ValueError(f"peer returned status {resp.status}")
                    response_payload = json.loads(resp.read().decode("utf-8"))
                if response_payload.get("ack", {}).get("message_id") != item["id"]:
                    raise ValueError("missing or invalid message ack")
                receipt_peer = self._resolve_outbox_peer(item)
                self._verify_receipt_payload(receipt_peer, response_payload)
                self.store.mark_outbox_delivered(item["id"])
                delivered += 1
            except (error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
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
