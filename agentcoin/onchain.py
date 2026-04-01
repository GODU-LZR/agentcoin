from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from agentcoin.models import utc_now


def _canonical_json(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(document: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(document).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class OnchainBindings:
    enabled: bool = False
    chain_id: int = 56
    rpc_url: str | None = None
    explorer_base_url: str | None = None
    did_registry_address: str | None = None
    staking_pool_address: str | None = None
    bounty_escrow_address: str | None = None
    local_did: str | None = None
    local_controller_address: str | None = None
    receipt_base_uri: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OnchainRuntime:
    def __init__(self, bindings: OnchainBindings) -> None:
        self.bindings = bindings

    @property
    def enabled(self) -> bool:
        return self.bindings.enabled and bool(self.bindings.bounty_escrow_address)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "chain_id": self.bindings.chain_id,
            "rpc_url": self.bindings.rpc_url,
            "explorer_base_url": self.bindings.explorer_base_url,
            "contracts": {
                "did_registry": self.bindings.did_registry_address,
                "staking_pool": self.bindings.staking_pool_address,
                "bounty_escrow": self.bindings.bounty_escrow_address,
            },
            "local_identity": {
                "did": self.bindings.local_did,
                "controller_address": self.bindings.local_controller_address,
            },
        }

    def task_context(self, task: dict[str, Any], *, job_id: int | None = None) -> dict[str, Any]:
        payload = dict(task.get("payload") or {})
        payload_for_hash = dict(payload)
        payload_for_hash.pop("_onchain", None)
        payload_for_hash.pop("_onchain_receipt", None)
        task_shape = {
            "id": task.get("id"),
            "kind": task.get("kind"),
            "sender": task.get("sender"),
            "required_capabilities": list(task.get("required_capabilities") or []),
            "role": task.get("role"),
            "branch": task.get("branch"),
            "revision": task.get("revision"),
            "workflow_id": task.get("workflow_id"),
            "payload": payload_for_hash,
        }
        spec_hash = sha256_hex(task_shape)
        context = {
            "chain_id": self.bindings.chain_id,
            "did_registry_address": self.bindings.did_registry_address,
            "staking_pool_address": self.bindings.staking_pool_address,
            "bounty_escrow_address": self.bindings.bounty_escrow_address,
            "local_did": self.bindings.local_did,
            "local_controller_address": self.bindings.local_controller_address,
            "spec_hash": spec_hash,
            "submission_hash": None,
            "result_hash": None,
            "receipt_uri": None,
            "job_id": job_id,
            "job_ref": self.job_ref(job_id) if job_id is not None else None,
            "status": "bound",
        }
        return context

    def job_ref(self, job_id: int | None) -> str | None:
        if job_id is None:
            return None
        if self.bindings.explorer_base_url and self.bindings.bounty_escrow_address:
            return (
                f"{self.bindings.explorer_base_url.rstrip('/')}/address/"
                f"{self.bindings.bounty_escrow_address}?jobId={job_id}"
            )
        return f"bnb:{self.bindings.chain_id}:{self.bindings.bounty_escrow_address}:{job_id}"

    def result_receipt(
        self,
        task: dict[str, Any],
        *,
        result: dict[str, Any],
        action: str,
    ) -> dict[str, Any]:
        onchain = dict(task.get("payload", {}).get("_onchain") or {})
        result_hash = sha256_hex(result or {})
        submission_hash = sha256_hex(
            {
                "task_id": task.get("id"),
                "workflow_id": task.get("workflow_id"),
                "worker_id": result.get("worker_id"),
                "result_hash": result_hash,
                "action": action,
            }
        )
        receipt_uri = self._receipt_uri(task.get("id"), submission_hash)
        return {
            "chain_id": self.bindings.chain_id,
            "job_id": onchain.get("job_id"),
            "job_ref": onchain.get("job_ref"),
            "worker_did": onchain.get("local_did") or self.bindings.local_did,
            "submission_hash": submission_hash,
            "result_hash": result_hash,
            "receipt_uri": receipt_uri,
            "intended_contract_action": action,
            "generated_at": utc_now(),
        }

    def _receipt_uri(self, task_id: str | None, submission_hash: str) -> str:
        if self.bindings.receipt_base_uri:
            return f"{self.bindings.receipt_base_uri.rstrip('/')}/{task_id or 'task'}/{submission_hash}.json"
        return f"agentcoin://receipts/{task_id or 'task'}/{submission_hash}.json"
