from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

AGENTCOIN_CONTEXT_URL = "https://agentcoin.ai/ns/context/v0.1"
RECEIPT_SCHEMA_VERSION = "0.1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _int_or(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _base_receipt(
    receipt_type: str,
    *,
    task_id: str | None = None,
    workflow_id: str | None = None,
    worker_id: str | None = None,
    branch: str | None = None,
    revision: int | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "@context": AGENTCOIN_CONTEXT_URL,
        "@type": receipt_type,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "task_id": task_id,
        "workflow_id": workflow_id,
        "worker_id": worker_id,
        "branch": branch,
        "revision": revision,
        "generated_at": generated_at or utc_now(),
    }


def build_policy_receipt(
    *,
    protocol: str,
    decision: str,
    reason: str,
    mode: str,
    **extra: Any,
) -> dict[str, Any]:
    receipt = _base_receipt("agentcoin:PolicyReceipt")
    receipt.update(
        {
            "protocol": protocol,
            "decision": decision,
            "reason": reason,
            "mode": mode,
        }
    )
    receipt.update(extra)
    return receipt


def build_deterministic_execution_receipt(
    task: dict[str, Any],
    *,
    worker_id: str,
    protocol: str,
    status: str,
    outcome: str | None = None,
    artifacts: dict[str, Any] | None = None,
    subprocess: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    receipt = _base_receipt(
        "agentcoin:DeterministicExecutionReceipt",
        task_id=str(task.get("id") or ""),
        workflow_id=str(task.get("workflow_id") or ""),
        worker_id=worker_id,
        branch=str(task.get("branch") or ""),
        revision=int(task.get("revision") or 0),
    )
    receipt.update(
        {
            "protocol": protocol,
            "status": status,
            "outcome": outcome or status,
            "artifacts": dict(artifacts or {}),
            "subprocess": subprocess,
        }
    )
    receipt.update(extra)
    return receipt


def build_subjective_review_receipt(
    task: dict[str, Any],
    *,
    worker_id: str,
    reviewer_type: str,
    approved: bool,
    score: int | None = None,
    notes: str | None = None,
    protocol: str = "agentcoin-review",
    target_task_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    receipt = _base_receipt(
        "agentcoin:SubjectiveReviewReceipt",
        task_id=str(task.get("id") or ""),
        workflow_id=str(task.get("workflow_id") or ""),
        worker_id=worker_id,
        branch=str(task.get("branch") or ""),
        revision=int(task.get("revision") or 0),
    )
    receipt.update(
        {
            "protocol": protocol,
            "reviewer_type": reviewer_type,
            "approved": bool(approved),
            "score": score,
            "notes": notes,
            "target_task_id": target_task_id,
        }
    )
    receipt.update(extra)
    return receipt


def build_challenge_evidence(
    *,
    task_id: str,
    evidence_hash: str,
    source: str,
    reason: str | None = None,
    severity: str | None = None,
    dispute_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = _base_receipt("agentcoin:ChallengeEvidence", task_id=task_id)
    evidence.update(
        {
            "evidence_hash": evidence_hash,
            "source": source,
            "reason": reason,
            "severity": severity,
            "dispute_id": dispute_id,
            "payload": dict(payload or {}),
        }
    )
    return evidence


def build_settlement_ledger_receipt(
    task: dict[str, Any],
    *,
    ledger_id: str,
    ledger_hash: str,
    chain_id: int,
    job_id: int | None,
    job_ref: str | None,
    worker_id: str | None,
    worker_did: str | None,
    poaw_summary: dict[str, Any],
    reputation: dict[str, Any],
    violation_summary: dict[str, Any],
    dispute_summary: dict[str, Any],
    settlement_summary: dict[str, Any],
    commit_projection: dict[str, Any],
) -> dict[str, Any]:
    receipt = _base_receipt(
        "agentcoin:SettlementLedgerReceipt",
        task_id=str(task.get("id") or ""),
        workflow_id=str(task.get("workflow_id") or ""),
        worker_id=worker_id,
        branch=str(task.get("branch") or ""),
        revision=int(task.get("revision") or 0),
    )
    receipt.update(
        {
            "ledger_id": ledger_id,
            "ledger_hash": ledger_hash,
            "chain_id": chain_id,
            "job_id": job_id,
            "job_ref": job_ref,
            "worker_did": worker_did,
            "poaw_summary": dict(poaw_summary or {}),
            "reputation": dict(reputation or {}),
            "violation_summary": dict(violation_summary or {}),
            "dispute_summary": dict(dispute_summary or {}),
            "settlement_summary": dict(settlement_summary or {}),
            "commit_projection": dict(commit_projection or {}),
        }
    )
    return receipt


def build_settlement_relay_receipt(
    relay: dict[str, Any],
    *,
    node_id: str,
) -> dict[str, Any]:
    receipt = _base_receipt(
        "agentcoin:SettlementRelayReceipt",
        task_id=str(relay.get("task_id") or ""),
        workflow_id=str(relay.get("workflow_id") or ""),
    )
    receipt.update(
        {
            "kind": "evm-settlement-relay",
            "node_id": node_id,
            "relay_record_id": relay.get("relay_record_id"),
            "recommended_resolution": relay.get("recommended_resolution"),
            "step_count": _int_or(relay.get("step_count"), 0),
            "completed_steps": _int_or(relay.get("completed_steps"), 0),
            "resume_from_index": _int_or(relay.get("resume_from_index"), 0),
            "last_successful_index": _int_or(relay.get("last_successful_index"), -1),
            "next_index": _int_or(relay.get("next_index"), 0),
            "retry_count": _int_or(relay.get("retry_count"), 0),
            "resumed": bool(relay.get("resumed")),
            "resumed_from_relay_id": relay.get("resumed_from_relay_id"),
            "stopped_on_error": bool(relay.get("stopped_on_error")),
            "failure_category": relay.get("failure_category"),
            "final_status": relay.get("final_status"),
            "submitted_steps": list(relay.get("submitted_steps") or []),
            "failures": list(relay.get("failures") or []),
            "settlement_ledger": dict(relay.get("settlement_ledger") or {}),
            "transport": dict(relay.get("transport") or {}),
        }
    )
    return receipt


def build_onchain_result_receipt(
    *,
    chain_id: int,
    job_id: int | None,
    job_ref: str | None,
    worker_did: str | None,
    submission_hash: str,
    result_hash: str,
    receipt_uri: str,
    intended_contract_action: str,
) -> dict[str, Any]:
    receipt = _base_receipt("agentcoin:OnchainResultReceipt")
    receipt.update(
        {
            "chain_id": chain_id,
            "job_id": job_id,
            "job_ref": job_ref,
            "worker_did": worker_did,
            "submission_hash": submission_hash,
            "result_hash": result_hash,
            "receipt_uri": receipt_uri,
            "intended_contract_action": intended_contract_action,
        }
    )
    return receipt


def receipt_examples() -> dict[str, Any]:
    return {
        "policy_receipt": build_policy_receipt(
            protocol="mcp",
            decision="allowed",
            reason="tool is allowlisted",
            mode="bridge-skeleton",
            tool_name="local-command",
        ),
        "deterministic_execution_receipt": {
            **build_deterministic_execution_receipt(
                {
                    "id": "task-code-1",
                    "workflow_id": "wf-1",
                    "branch": "main",
                    "revision": 1,
                },
                worker_id="worker-1",
                protocol="openai-chat",
                status="completed",
                outcome="generated-output",
                artifacts={"response_id": "resp-123"},
            )
        },
        "subjective_review_receipt": build_subjective_review_receipt(
            {
                "id": "review-task-1",
                "workflow_id": "wf-1",
                "branch": "review/main",
                "revision": 1,
            },
            worker_id="reviewer-1",
            reviewer_type="ai",
            approved=True,
            score=87,
            notes="Looks acceptable.",
            target_task_id="task-code-1",
        ),
        "challenge_evidence": build_challenge_evidence(
            task_id="task-code-1",
            evidence_hash="0xabc123",
            source="poaw-settlement-policy",
            reason="review score below threshold",
            severity="medium",
            dispute_id="dispute-1",
        ),
        "settlement_ledger_receipt": build_settlement_ledger_receipt(
            {
                "id": "task-code-1",
                "workflow_id": "wf-1",
                "branch": "main",
                "revision": 1,
            },
            ledger_id="settlement-ledger:task-code-1:abc123",
            ledger_hash="abc123",
            chain_id=97,
            job_id=42,
            job_ref="bnb:97:0xescrow:42",
            worker_id="worker-1",
            worker_did="did:agentcoin:worker-1",
            poaw_summary={"event_count": 2, "total_points": 14},
            reputation={"score": 100, "violations": 0},
            violation_summary={"count": 0, "severity_counts": {}, "sources": []},
            dispute_summary={"count": 0, "status_counts": {}, "items": []},
            settlement_summary={
                "recommended_resolution": "completeJob",
                "recommended_sequence": ["submitWork", "completeJob"],
                "score": 84,
            },
            commit_projection={
                "supported_now": True,
                "current_contract": "BountyEscrow",
                "current_actions": ["submitWork", "completeJob"],
                "future_contracts": ["PoAWScorebook", "ReputationEventLedger"],
                "gaps": [],
            },
        ),
        "settlement_relay_receipt": build_settlement_relay_receipt(
            {
                "task_id": "task-code-1",
                "workflow_id": "wf-1",
                "relay_record_id": "relay-1",
                "recommended_resolution": "completeJob",
                "step_count": 2,
                "completed_steps": 2,
                "last_successful_index": 1,
                "next_index": 2,
                "retry_count": 0,
                "resumed": False,
                "resumed_from_relay_id": None,
                "stopped_on_error": False,
                "failure_category": None,
                "final_status": "completed",
                "submitted_steps": [],
                "failures": [],
                "settlement_ledger": {"ledger_id": "settlement-ledger:task-code-1:abc123", "ledger_hash": "abc123"},
                "transport": {"profile": "direct"},
            },
            node_id="agentcoin-local",
        ),
        "onchain_result_receipt": build_onchain_result_receipt(
            chain_id=97,
            job_id=42,
            job_ref="bnb:97:0xescrow:42",
            worker_did="did:agentcoin:worker-1",
            submission_hash="0xsubhash",
            result_hash="0xresulthash",
            receipt_uri="ipfs://agentcoin-receipts/task-code-1/0xsubhash.json",
            intended_contract_action="completeJob",
        ),
    }
