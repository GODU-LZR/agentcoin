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
        if normalized == "challengeJob":
            return self._challenge_job_intent(task, params=params)
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

    def rpc_request(self, method: str, params: list[Any] | None = None, *, request_id: str | None = None) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id or f"agentcoin-rpc-{method}",
            "method": method,
            "params": list(params or []),
        }

    def rpc_probe_payloads(self, payload: dict[str, Any], *, rpc: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rpc = rpc or {}
        tx = dict(payload.get("transaction") or {})
        task_id = str(payload.get("intent", {}).get("task_id") or "task")
        block = str(rpc.get("block") or "pending")
        probes: list[dict[str, Any]] = []

        if tx.get("from") and bool(rpc.get("include_nonce", True)):
            probes.append(
                {
                    "name": "nonce",
                    "rpc_method": "eth_getTransactionCount",
                    "request": self.rpc_request(
                        "eth_getTransactionCount",
                        [tx["from"], block],
                        request_id=f"agentcoin-{task_id}-nonce",
                    ),
                }
            )
        if bool(rpc.get("include_gas_price", True)):
            probes.append(
                {
                    "name": "gasPrice",
                    "rpc_method": "eth_gasPrice",
                    "request": self.rpc_request(
                        "eth_gasPrice",
                        [],
                        request_id=f"agentcoin-{task_id}-gas-price",
                    ),
                }
            )
        should_estimate_gas = bool(rpc.get("include_estimate_gas", True))
        if payload.get("call", {}).get("abi_encoding_required") and not tx.get("data"):
            should_estimate_gas = bool(rpc.get("force_estimate_gas"))
        if should_estimate_gas:
            probes.append(
                {
                    "name": "gas",
                    "rpc_method": "eth_estimateGas",
                    "request": self.rpc_request(
                        "eth_estimateGas",
                        [tx],
                        request_id=f"agentcoin-{task_id}-estimate-gas",
                    ),
                }
            )
        return probes

    def apply_rpc_probe_results(
        self,
        payload: dict[str, Any],
        results: dict[str, Any],
    ) -> dict[str, Any]:
        planned = json.loads(_canonical_json(payload))
        tx = dict(planned.get("transaction") or {})
        request_params = list(planned.get("request", {}).get("params") or [])
        primary = dict(request_params[0] or {}) if request_params and isinstance(request_params[0], dict) else {}
        mappings = {
            "nonce": "nonce",
            "gas": "gas",
            "gasPrice": "gasPrice",
            "maxFeePerGas": "maxFeePerGas",
            "maxPriorityFeePerGas": "maxPriorityFeePerGas",
        }
        recommendations: dict[str, Any] = {}
        for result_name, tx_key in mappings.items():
            raw = results.get(result_name)
            encoded = self._rpc_result_quantity(raw)
            if encoded is None:
                continue
            tx[tx_key] = encoded
            primary[tx_key] = encoded
            recommendations[result_name] = encoded
        if primary:
            if request_params:
                request_params[0] = primary
            else:
                request_params = [primary]
        planned["transaction"] = tx
        planned["request"]["params"] = request_params
        planned["recommended"] = recommendations
        return planned

    def raw_transaction_payload(
        self,
        raw_transaction: str,
        *,
        rpc_url: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        raw = str(raw_transaction or "").strip()
        if not raw:
            raise ValueError("raw_transaction is required")
        return {
            "kind": "evm-json-rpc-payload",
            "rpc_url": rpc_url or self.bindings.rpc_url,
            "chain_id": self.bindings.chain_id,
            "rpc_method": "eth_sendRawTransaction",
            "request": self.rpc_request(
                "eth_sendRawTransaction",
                [raw],
                request_id=request_id or f"agentcoin-raw-tx-{sha256_hex({'raw_transaction': raw})[:12]}",
            ),
            "raw_transaction": raw,
            "generated_at": utc_now(),
        }

    @staticmethod
    def _rpc_result_quantity(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, dict) and "result" in value:
            return OnchainRuntime._rpc_result_quantity(value.get("result"))
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            if raw.lower().startswith("0x"):
                return raw.lower()
            return _hex_quantity(raw)
        if isinstance(value, int):
            return _hex_quantity(value)
        return None

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

    @staticmethod
    def settlement_score(poaw_summary: dict[str, Any]) -> int:
        positive_points = int(poaw_summary.get("positive_points") or 0)
        negative_points = int(poaw_summary.get("negative_points") or 0)
        total_points = int(poaw_summary.get("total_points") or 0)
        score = 70 + positive_points + negative_points
        if positive_points == 0 and total_points <= 0:
            score = 0
        return max(0, min(100, score))

    @staticmethod
    def slash_amount_wei(poaw_summary: dict[str, Any]) -> int:
        negative_points = abs(int(poaw_summary.get("negative_points") or 0))
        if negative_points <= 0:
            return 0
        return negative_points * 10**15

    def settlement_preview(
        self,
        task: dict[str, Any],
        *,
        poaw_summary: dict[str, Any],
        reputation: dict[str, Any] | None = None,
        violations: list[dict[str, Any]] | None = None,
        disputes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        reputation = reputation or {}
        violations = list(violations or [])
        disputes = list(disputes or [])
        result = dict(task.get("result") or {})
        adapter = dict(result.get("adapter") or {})
        adapter_rejected = str(adapter.get("status") or "").strip().lower() == "rejected"
        negative_points = int(poaw_summary.get("negative_points") or 0)
        score = self.settlement_score(poaw_summary)
        slash_amount = self.slash_amount_wei(poaw_summary)
        severe_violation = any(str(item.get("severity") or "").strip().lower() in {"high", "critical"} for item in violations)
        quarantined = bool(reputation.get("quarantined"))
        open_disputes = [item for item in disputes if str(item.get("status") or "").strip().lower() == "open"]

        recommended_resolution = "completeJob"
        resolution_params: dict[str, Any] = {"score": score}
        if adapter_rejected:
            recommended_resolution = "rejectJob"
            resolution_params = {}
        elif open_disputes:
            first = open_disputes[0]
            recommended_resolution = "challengeJob"
            resolution_params = {
                "evidence_hash": str(first.get("evidence_hash") or ""),
            }
        elif quarantined or severe_violation or negative_points <= -30:
            recommended_resolution = "slashJob"
            resolution_params = {
                "slash_amount_wei": str(slash_amount),
                "recipient": self.bindings.local_controller_address or "0x0000000000000000000000000000000000000000",
                "reason": "poaw policy violations",
            }

        sequence = ["submitWork", recommended_resolution]
        intents: list[dict[str, Any]] = []
        for action in sequence:
            params = resolution_params if action == recommended_resolution else {}
            intents.append(self.transaction_intent(task, action=action, params=params))

        return {
            "job_id": task.get("payload", {}).get("_onchain", {}).get("job_id"),
            "poaw_summary": poaw_summary,
            "reputation": reputation,
            "violation_count": len(violations),
            "open_dispute_count": len(open_disputes),
            "recommended_resolution": recommended_resolution,
            "recommended_sequence": sequence,
            "score": score,
            "slash_amount_wei": str(slash_amount),
            "resolution_params": resolution_params,
            "intents": intents,
            "generated_at": utc_now(),
        }

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

    def _challenge_job_intent(self, task: dict[str, Any], *, params: dict[str, Any]) -> dict[str, Any]:
        onchain = dict(task.get("payload", {}).get("_onchain") or {})
        job_id = onchain.get("job_id")
        if job_id is None:
            raise ValueError("task is not bound to an onchain job_id")
        evidence_hash = str(params.get("evidence_hash") or "").strip()
        if not evidence_hash:
            raise ValueError("evidence_hash is required")
        intent = self._intent_base(action="challengeJob", task=task, params=params)
        intent.update(
            {
                "value_wei": "0",
                "function": "challengeJob",
                "signature": "challengeJob(uint256,bytes32)",
                "args": {
                    "jobId": int(job_id),
                    "evidenceHash": as_bytes32_hex(evidence_hash),
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
