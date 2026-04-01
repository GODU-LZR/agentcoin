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


def _hex_quantity(value: int | str | None) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.lower().startswith("0x"):
            return raw.lower()
        value = int(raw)
    return hex(int(value))


def as_bytes32_hex(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "0x" + ("0" * 64)
    lowered = raw.lower()
    if lowered.startswith("0x"):
        hex_body = lowered[2:]
        if len(hex_body) == 64 and all(ch in "0123456789abcdef" for ch in hex_body):
            return lowered
    if len(lowered) == 64 and all(ch in "0123456789abcdef" for ch in lowered):
        return f"0x{lowered}"
    return "0x" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


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

    def transaction_intent(
        self,
        task: dict[str, Any],
        *,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = params or {}
        normalized = action.strip()
        if normalized == "createJob":
            return self._create_job_intent(task, params=params)
        if normalized == "acceptJob":
            return self._accept_job_intent(task, params=params)
        if normalized == "submitWork":
            return self._submit_work_intent(task, params=params)
        if normalized == "completeJob":
            return self._complete_job_intent(task, params=params)
        if normalized == "rejectJob":
            return self._reject_job_intent(task, params=params)
        if normalized == "slashJob":
            return self._slash_job_intent(task, params=params)
        raise ValueError(f"unsupported onchain action: {action}")

    def rpc_payload(
        self,
        task: dict[str, Any],
        *,
        action: str,
        params: dict[str, Any] | None = None,
        rpc: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        intent = self.transaction_intent(task, action=action, params=params or {})
        return self.rpc_payload_for_intent(intent, rpc=rpc or {})

    def rpc_payload_for_intent(self, intent: dict[str, Any], *, rpc: dict[str, Any] | None = None) -> dict[str, Any]:
        rpc = rpc or {}
        rpc_method = str(rpc.get("method") or "eth_sendTransaction").strip()
        if rpc_method == "eth_sendRawTransaction":
            raise ValueError("eth_sendRawTransaction requires an externally signed raw transaction")
        tx_request = {
            "from": intent.get("from"),
            "to": intent.get("to"),
            "value": _hex_quantity(intent.get("value_wei")) or "0x0",
            "chainId": _hex_quantity(intent.get("chain_id")) or "0x0",
        }
        optional_fields = {
            "nonce": rpc.get("nonce"),
            "gas": rpc.get("gas"),
            "gasPrice": rpc.get("gas_price_wei"),
            "maxFeePerGas": rpc.get("max_fee_per_gas_wei"),
            "maxPriorityFeePerGas": rpc.get("max_priority_fee_per_gas_wei"),
        }
        for key, value in optional_fields.items():
            encoded = _hex_quantity(value)
            if encoded is not None:
                tx_request[key] = encoded
        data = rpc.get("data")
        if data:
            tx_request["data"] = str(data)
        request_params: list[Any]
        if rpc_method == "eth_call":
            request_params = [tx_request, str(rpc.get("block") or "latest")]
        else:
            request_params = [tx_request]
        rpc_id = str(rpc.get("id") or f"agentcoin-{intent.get('action')}-{intent.get('task_id')}")
        payload = {
            "kind": "evm-json-rpc-payload",
            "rpc_url": intent.get("rpc_url"),
            "chain_id": intent.get("chain_id"),
            "rpc_method": rpc_method,
            "request": {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "method": rpc_method,
                "params": request_params,
            },
            "transaction": tx_request,
            "call": {
                "contract": intent.get("contract"),
                "function": intent.get("function"),
                "signature": intent.get("signature"),
                "args": dict(intent.get("args") or {}),
                "abi_encoding_required": not bool(data),
                "data": str(data) if data else None,
            },
            "intent": {
                "action": intent.get("action"),
                "task_id": intent.get("task_id"),
                "workflow_id": intent.get("workflow_id"),
                "job_id": intent.get("job_id"),
                "job_ref": intent.get("job_ref"),
            },
            "generated_at": utc_now(),
        }
        return payload

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

    def _intent_base(self, *, action: str, task: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        onchain = dict(task.get("payload", {}).get("_onchain") or {})
        return {
            "kind": "evm-transaction-intent",
            "chain_id": self.bindings.chain_id,
            "rpc_url": self.bindings.rpc_url,
            "contract": "BountyEscrow",
            "to": self.bindings.bounty_escrow_address,
            "action": action,
            "task_id": task.get("id"),
            "workflow_id": task.get("workflow_id"),
            "job_id": onchain.get("job_id"),
            "job_ref": onchain.get("job_ref"),
            "from": params.get("from") or self.bindings.local_controller_address,
            "generated_at": utc_now(),
        }

    def _create_job_intent(self, task: dict[str, Any], *, params: dict[str, Any]) -> dict[str, Any]:
        onchain = dict(task.get("payload", {}).get("_onchain") or {})
        deadline = int(params.get("deadline") or 0)
        reward_amount_wei = int(params.get("reward_amount_wei") or 0)
        intent = self._intent_base(action="createJob", task=task, params=params)
        intent.update(
            {
                "value_wei": str(reward_amount_wei),
                "function": "createJob",
                "signature": "createJob(address,uint256,uint256,uint64,bytes32)",
                "args": {
                    "evaluator": params.get("evaluator_address") or "0x0000000000000000000000000000000000000000",
                    "stakeRequired": str(int(params.get("stake_required_wei") or 0)),
                    "minReputation": int(params.get("min_reputation") or 0),
                    "deadline": deadline,
                    "specHash": as_bytes32_hex(onchain.get("spec_hash")),
                },
            }
        )
        return intent

    def _accept_job_intent(self, task: dict[str, Any], *, params: dict[str, Any]) -> dict[str, Any]:
        onchain = dict(task.get("payload", {}).get("_onchain") or {})
        job_id = onchain.get("job_id")
        if job_id is None:
            raise ValueError("task is not bound to an onchain job_id")
        worker_did = params.get("worker_did") or onchain.get("local_did") or self.bindings.local_did
        intent = self._intent_base(action="acceptJob", task=task, params=params)
        intent.update(
            {
                "value_wei": "0",
                "function": "acceptJob",
                "signature": "acceptJob(uint256,bytes32)",
                "args": {
                    "jobId": int(job_id),
                    "workerDid": as_bytes32_hex(worker_did),
                },
            }
        )
        return intent

    def _submit_work_intent(self, task: dict[str, Any], *, params: dict[str, Any]) -> dict[str, Any]:
        onchain = dict(task.get("payload", {}).get("_onchain") or {})
        receipt = dict(params.get("receipt") or task.get("result", {}).get("_onchain_receipt") or {})
        job_id = onchain.get("job_id") or receipt.get("job_id")
        if job_id is None:
            raise ValueError("task is not bound to an onchain job_id")
        submission_hash = receipt.get("submission_hash") or onchain.get("submission_hash")
        receipt_uri = receipt.get("receipt_uri") or onchain.get("receipt_uri")
        if not submission_hash:
            raise ValueError("submission_hash is required")
        intent = self._intent_base(action="submitWork", task=task, params=params)
        intent.update(
            {
                "value_wei": "0",
                "function": "submitWork",
                "signature": "submitWork(uint256,bytes32,string)",
                "args": {
                    "jobId": int(job_id),
                    "submissionHash": as_bytes32_hex(submission_hash),
                    "resultURI": str(receipt_uri or ""),
                },
            }
        )
        return intent

    def _complete_job_intent(self, task: dict[str, Any], *, params: dict[str, Any]) -> dict[str, Any]:
        onchain = dict(task.get("payload", {}).get("_onchain") or {})
        receipt = dict(params.get("receipt") or task.get("result", {}).get("_onchain_receipt") or {})
        job_id = onchain.get("job_id") or receipt.get("job_id")
        if job_id is None:
            raise ValueError("task is not bound to an onchain job_id")
        intent = self._intent_base(action="completeJob", task=task, params=params)
        intent.update(
            {
                "value_wei": "0",
                "function": "completeJob",
                "signature": "completeJob(uint256,uint256,string)",
                "args": {
                    "jobId": int(job_id),
                    "score": int(params.get("score") or 100),
                    "receiptURI": str(receipt.get("receipt_uri") or ""),
                },
            }
        )
        return intent

    def _reject_job_intent(self, task: dict[str, Any], *, params: dict[str, Any]) -> dict[str, Any]:
        onchain = dict(task.get("payload", {}).get("_onchain") or {})
        receipt = dict(params.get("receipt") or task.get("result", {}).get("_onchain_receipt") or {})
        job_id = onchain.get("job_id") or receipt.get("job_id")
        if job_id is None:
            raise ValueError("task is not bound to an onchain job_id")
        intent = self._intent_base(action="rejectJob", task=task, params=params)
        intent.update(
            {
                "value_wei": "0",
                "function": "rejectJob",
                "signature": "rejectJob(uint256,string)",
                "args": {
                    "jobId": int(job_id),
                    "receiptURI": str(receipt.get("receipt_uri") or ""),
                },
            }
        )
        return intent

    def _slash_job_intent(self, task: dict[str, Any], *, params: dict[str, Any]) -> dict[str, Any]:
        onchain = dict(task.get("payload", {}).get("_onchain") or {})
        receipt = dict(params.get("receipt") or task.get("result", {}).get("_onchain_receipt") or {})
        job_id = onchain.get("job_id") or receipt.get("job_id")
        if job_id is None:
            raise ValueError("task is not bound to an onchain job_id")
        intent = self._intent_base(action="slashJob", task=task, params=params)
        intent.update(
            {
                "value_wei": "0",
                "function": "slashJob",
                "signature": "slashJob(uint256,uint256,address,string,string)",
                "args": {
                    "jobId": int(job_id),
                    "slashAmount": str(int(params.get("slash_amount_wei") or 0)),
                    "recipient": params.get("recipient") or "0x0000000000000000000000000000000000000000",
                    "reason": str(params.get("reason") or ""),
                    "receiptURI": str(receipt.get("receipt_uri") or ""),
                },
            }
        )
        return intent
