from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from agentcoin.models import TaskEnvelope
from agentcoin.store import NodeStore


class NodeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = NodeStore(str(Path(self.tempdir.name) / "agentcoin.db"))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_requeue_exhaustion_moves_task_to_dead_letter(self) -> None:
        self.store.add_task(
            TaskEnvelope(
                id="retry-task",
                kind="exec",
                payload={},
                role="worker",
                max_attempts=2,
                retry_backoff_seconds=2,
            )
        )

        first = self.store.claim_task(worker_id="worker-1", worker_capabilities=["worker"], lease_seconds=30)
        self.assertIsNotNone(first)
        self.assertTrue(
            self.store.ack_task(
                task_id="retry-task",
                worker_id="worker-1",
                lease_token=first["lease_token"],
                success=False,
                requeue=True,
                error_message="temporary failure",
            )
        )

        self.assertIsNone(self.store.claim_task(worker_id="worker-1", worker_capabilities=["worker"], lease_seconds=30))
        time.sleep(2.1)

        second = self.store.claim_task(worker_id="worker-1", worker_capabilities=["worker"], lease_seconds=30)
        self.assertIsNotNone(second)
        self.assertTrue(
            self.store.ack_task(
                task_id="retry-task",
                worker_id="worker-1",
                lease_token=second["lease_token"],
                success=False,
                requeue=True,
                error_message="retry budget exhausted",
            )
        )

        task = self.store.get_task("retry-task")
        assert task is not None
        self.assertEqual(task["status"], "dead-letter")
        self.assertEqual(task["last_error"], "retry budget exhausted")

    def test_semantic_capability_aliases_match_worker_claims(self) -> None:
        self.store.add_task(
            TaskEnvelope(
                id="semantic-cap-task",
                kind="exec",
                payload={},
                role="worker",
                required_capabilities=["reviewer"],
            )
        )

        claimed = self.store.claim_task(
            worker_id="worker-ai-review",
            worker_capabilities=["ai-reviewer", "worker"],
            lease_seconds=30,
        )
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed["id"], "semantic-cap-task")

    def test_workflow_summary_reports_merge_and_finalization(self) -> None:
        self.store.add_task(TaskEnvelope(id="root", kind="plan", payload={}, role="planner"))
        self.store.create_subtasks(
            "root",
            [
                TaskEnvelope(id="branch-a", kind="code", payload={}, role="worker", branch="feature/a"),
                TaskEnvelope(id="branch-b", kind="code", payload={}, role="worker", branch="feature/b"),
            ],
        )
        merge_task = self.store.create_merge_task(
            "root",
            ["branch-a", "branch-b"],
            TaskEnvelope(id="merge-1", kind="merge", payload={}, role="reviewer", branch="main"),
        )

        summary_before = self.store.summarize_workflow("root")
        self.assertIn("merge-1", summary_before["blocked_task_ids"])
        self.assertFalse(summary_before["finalizable"])

        for task_id in ["branch-a", "branch-b"]:
            claimed = self.store.claim_task(worker_id=f"{task_id}-worker", worker_capabilities=["worker"], lease_seconds=30)
            assert claimed is not None
            self.assertTrue(
                self.store.ack_task(
                    task_id=task_id,
                    worker_id=claimed["locked_by"],
                    lease_token=claimed["lease_token"],
                    success=True,
                    result={"done": task_id},
                )
            )

        reviewer_claim = self.store.claim_task(worker_id="reviewer-1", worker_capabilities=["reviewer"], lease_seconds=30)
        self.assertIsNotNone(reviewer_claim)
        self.assertEqual(reviewer_claim["id"], merge_task["id"])
        self.assertTrue(
            self.store.ack_task(
                task_id="merge-1",
                worker_id="reviewer-1",
                lease_token=reviewer_claim["lease_token"],
                success=True,
                result={"merged": ["branch-a", "branch-b"]},
            )
        )

        finalized = self.store.finalize_workflow("root")
        self.assertTrue(finalized["ok"])
        self.assertEqual(finalized["status"], "completed")
        self.assertEqual(finalized["summary"]["persisted_state"]["status"], "completed")

    def test_protected_merge_requires_review_gate(self) -> None:
        self.store.add_task(TaskEnvelope(id="root-protected", kind="plan", payload={}, role="planner"))
        self.store.create_subtasks(
            "root-protected",
            [
                TaskEnvelope(id="branch-a", kind="code", payload={}, role="worker", branch="feature/a"),
                TaskEnvelope(id="branch-b", kind="code", payload={}, role="worker", branch="feature/b"),
            ],
        )
        self.store.create_review_tasks(
            "root-protected",
            [
                TaskEnvelope(id="review-a", kind="review", payload={"_review": {"target_task_id": "branch-a"}}, role="reviewer"),
                TaskEnvelope(id="review-b", kind="review", payload={"_review": {"target_task_id": "branch-b"}}, role="reviewer"),
            ],
        )
        self.store.create_merge_task(
            "root-protected",
            ["branch-a", "branch-b"],
            TaskEnvelope(
                id="merge-protected",
                kind="merge",
                payload={"_merge_policy": {"protected_branches": ["feature/a", "feature/b"], "required_approvals_per_branch": 1}},
                role="reviewer",
                branch="main",
            ),
        )

        for task_id in ["branch-a", "branch-b"]:
            claimed = self.store.claim_task(worker_id=f"{task_id}-worker", worker_capabilities=["worker"], lease_seconds=30)
            assert claimed is not None
            self.store.ack_task(
                task_id=task_id,
                worker_id=claimed["locked_by"],
                lease_token=claimed["lease_token"],
                success=True,
                result={"done": task_id},
            )

        blocked_merge = self.store.claim_task(worker_id="merge-reviewer", worker_capabilities=["reviewer"], lease_seconds=30)
        self.assertIsNotNone(blocked_merge)
        self.assertIn(blocked_merge["id"], {"review-a", "review-b"})

        for review_id in ["review-a", "review-b"]:
            claimed_review = blocked_merge if blocked_merge["id"] == review_id else self.store.claim_task(
                worker_id=f"{review_id}-reviewer",
                worker_capabilities=["reviewer"],
                lease_seconds=30,
            )
            assert claimed_review is not None
            self.store.ack_task(
                task_id=review_id,
                worker_id=claimed_review["locked_by"],
                lease_token=claimed_review["lease_token"],
                success=True,
                result={"approved": True, "notes": review_id},
            )

        merge_claim = self.store.claim_task(worker_id="merge-reviewer", worker_capabilities=["reviewer"], lease_seconds=30)
        self.assertIsNotNone(merge_claim)
        self.assertEqual(merge_claim["id"], "merge-protected")

        summary = self.store.summarize_workflow("root-protected")
        self.assertIn("review-a", summary["review_task_ids"])
        self.assertTrue(summary["merge_gate_status"]["merge-protected"]["satisfied"])

    def test_hybrid_merge_requires_human_and_ai_approvals(self) -> None:
        self.store.add_task(TaskEnvelope(id="root-hybrid", kind="plan", payload={}, role="planner"))
        self.store.create_subtasks(
            "root-hybrid",
            [
                TaskEnvelope(
                    id="branch-task",
                    kind="code",
                    payload={"_git": {"repo_root": "repo", "changed_files": ["app.py"]}},
                    role="worker",
                    branch="feature/hybrid",
                ),
                TaskEnvelope(
                    id="branch-helper",
                    kind="code",
                    payload={},
                    role="worker",
                    branch="feature/helper",
                ),
            ],
        )
        self.store.create_review_tasks(
            "root-hybrid",
            [
                TaskEnvelope(
                    id="review-human",
                    kind="review",
                    payload={"_review": {"target_task_id": "branch-task", "reviewer_type": "human"}},
                    role="reviewer",
                ),
                TaskEnvelope(
                    id="review-ai",
                    kind="review",
                    payload={"_review": {"target_task_id": "branch-task", "reviewer_type": "ai"}},
                    role="reviewer",
                ),
            ],
        )
        merge = self.store.create_merge_task(
            "root-hybrid",
            ["branch-task", "branch-helper"],
            TaskEnvelope(
                id="merge-hybrid",
                kind="merge",
                payload={
                    "_merge_policy": {
                        "protected_branches": ["feature/hybrid"],
                        "required_human_approvals_per_branch": 1,
                        "required_ai_approvals_per_branch": 1,
                    }
                },
                role="reviewer",
                branch="main",
            ),
        )
        self.assertEqual(merge["payload"]["_merge_policy"]["required_human_approvals_per_branch"], 1)

        branch_claim = self.store.claim_task(worker_id="worker-hybrid", worker_capabilities=["worker"], lease_seconds=30)
        assert branch_claim is not None
        self.store.ack_task(
            task_id="branch-task",
            worker_id=branch_claim["locked_by"],
            lease_token=branch_claim["lease_token"],
            success=True,
            result={"done": True},
        )

        human_review = self.store.claim_task(worker_id="review-human-worker", worker_capabilities=["reviewer"], lease_seconds=30)
        assert human_review is not None
        self.assertEqual(human_review["payload"]["_review"]["reviewer_type"], "human")
        self.assertIn("_git", human_review["payload"])
        self.store.ack_task(
            task_id="review-human",
            worker_id=human_review["locked_by"],
            lease_token=human_review["lease_token"],
            success=True,
            result={"approved": True},
        )

        summary_mid = self.store.summarize_workflow("root-hybrid")
        self.assertFalse(summary_mid["merge_gate_status"]["merge-hybrid"]["satisfied"])

        ai_review = self.store.claim_task(worker_id="review-ai-worker", worker_capabilities=["reviewer"], lease_seconds=30)
        assert ai_review is not None
        self.assertEqual(ai_review["payload"]["_review"]["reviewer_type"], "ai")
        self.store.ack_task(
            task_id="review-ai",
            worker_id=ai_review["locked_by"],
            lease_token=ai_review["lease_token"],
            success=True,
            result={"approved": True},
        )

        summary_done = self.store.summarize_workflow("root-hybrid")
        self.assertTrue(summary_done["merge_gate_status"]["merge-hybrid"]["satisfied"])

    def test_ack_persists_execution_audit(self) -> None:
        self.store.add_task(TaskEnvelope(id="audit-task", kind="exec", payload={}, role="worker"))
        claimed = self.store.claim_task(worker_id="worker-audit", worker_capabilities=["worker"], lease_seconds=30)
        assert claimed is not None
        self.assertTrue(
            self.store.ack_task(
                task_id="audit-task",
                worker_id="worker-audit",
                lease_token=claimed["lease_token"],
                success=True,
                result={"policy_receipt": {"decision": "allowed"}, "execution_receipt": {"status": "completed"}},
            )
        )

        audits = self.store.list_execution_audits(task_id="audit-task")
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["status"], "completed")
        self.assertEqual(audits[0]["payload"]["result"]["policy_receipt"]["decision"], "allowed")

        score_events = self.store.list_score_events(actor_id="worker-audit")
        self.assertEqual(len(score_events), 1)
        self.assertEqual(score_events[0]["event_type"], "deterministic-pass")
        self.assertEqual(score_events[0]["points"], 12)
        self.assertEqual(score_events[0]["payload"]["poaw_policy_version"], "0.2")

    def test_poaw_summary_aggregates_completion_and_violation_events(self) -> None:
        self.store.add_task(
            TaskEnvelope(
                id="poaw-review-task",
                kind="review",
                payload={},
                role="reviewer",
                workflow_id="wf-poaw",
                required_capabilities=["reviewer"],
            )
        )
        claimed = self.store.claim_task(
            worker_id="reviewer-poaw",
            worker_capabilities=["reviewer"],
            lease_seconds=30,
        )
        assert claimed is not None
        self.assertTrue(
            self.store.ack_task(
                task_id="poaw-review-task",
                worker_id="reviewer-poaw",
                lease_token=claimed["lease_token"],
                success=True,
                result={"approved": True},
            )
        )

        violation = self.store.record_policy_violation(
            actor_id="reviewer-poaw",
            actor_type="worker",
            task_id="poaw-review-task",
            source="review-policy",
            reason="approval policy mismatch",
            severity="medium",
        )
        self.assertEqual(violation["severity"], "medium")

        events = self.store.list_score_events(actor_id="reviewer-poaw")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event_type"], "policy-violation")
        self.assertEqual(events[0]["points"], -15)
        self.assertEqual(events[1]["event_type"], "subjective-approve")

        summary = self.store.summarize_score_events(actor_id="reviewer-poaw", actor_type="worker")
        self.assertEqual(summary["event_count"], 2)
        self.assertEqual(summary["total_points"], -1)
        self.assertEqual(summary["positive_points"], 14)
        self.assertEqual(summary["negative_points"], -15)
        self.assertEqual(summary["poaw_policy_version"], "0.2")
        self.assertIn("worker_base", summary["score_weights"])
        self.assertEqual(summary["reputation"]["violations"], 1)

    def test_policy_violations_update_reputation_and_block_claim(self) -> None:
        self.store.add_task(TaskEnvelope(id="queued-task", kind="exec", payload={}, role="worker"))

        for _ in range(3):
            violation = self.store.record_policy_violation(
                actor_id="worker-risky",
                actor_type="worker",
                task_id="queued-task",
                source="mcp",
                reason="tool is not allowlisted",
                severity="medium",
                payload={"tool_name": "forbidden-tool"},
            )
            self.assertEqual(violation["source"], "mcp")

        reputation = self.store.get_actor_reputation("worker-risky")
        self.assertEqual(reputation["violations"], 3)
        self.assertEqual(reputation["score"], 55)
        self.assertTrue(reputation["quarantined"])

        violations = self.store.list_policy_violations(actor_id="worker-risky")
        self.assertEqual(len(violations), 3)
        self.assertEqual(violations[0]["reason"], "tool is not allowlisted")

        quarantines = self.store.list_quarantines(actor_id="worker-risky")
        self.assertEqual(len(quarantines), 1)
        self.assertTrue(quarantines[0]["active"])

        self.assertIsNone(self.store.claim_task(worker_id="worker-risky", worker_capabilities=["worker"], lease_seconds=30))

    def test_manual_quarantine_release_restores_claims(self) -> None:
        self.store.add_task(TaskEnvelope(id="queued-manual", kind="exec", payload={}, role="worker"))

        applied = self.store.set_actor_quarantine(
            actor_id="worker-manual",
            reason="operator quarantine for investigation",
            payload={"operator": "admin"},
        )
        self.assertTrue(applied["quarantined"])
        self.assertTrue(applied["reputation"]["quarantined"])
        self.assertIsNone(self.store.claim_task(worker_id="worker-manual", worker_capabilities=["worker"], lease_seconds=30))

        released = self.store.release_actor_quarantine(
            actor_id="worker-manual",
            reason="operator release after review",
            payload={"operator": "admin"},
        )
        self.assertFalse(released["quarantined"])
        self.assertFalse(released["reputation"]["quarantined"])

        actions = self.store.list_governance_actions(actor_id="worker-manual")
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0]["action_type"], "quarantine-release")

        claim = self.store.claim_task(worker_id="worker-manual", worker_capabilities=["worker"], lease_seconds=30)
        self.assertIsNotNone(claim)
        self.assertEqual(claim["id"], "queued-manual")

    def test_open_and_resolve_dispute_records_governance_history(self) -> None:
        self.store.add_task(TaskEnvelope(id="dispute-task", kind="exec", payload={}, role="worker"))
        opened = self.store.open_dispute(
            task_id="dispute-task",
            challenger_id="reviewer-1",
            actor_id="worker-disputed",
            actor_type="worker",
            reason="output quality challenge",
            evidence_hash="evidence-123",
            severity="high",
            bond_amount_wei="25000000000000000",
            payload={"notes": "needs recheck"},
        )
        self.assertTrue(opened["ok"])
        self.assertEqual(opened["dispute"]["status"], "open")
        self.assertEqual(opened["dispute"]["evidence_hash"], "evidence-123")
        self.assertEqual(opened["dispute"]["bond_status"], "locked")

        disputes = self.store.list_disputes(task_id="dispute-task", status="open")
        self.assertEqual(len(disputes), 1)
        self.assertEqual(disputes[0]["challenger_id"], "reviewer-1")
        self.assertEqual(disputes[0]["bond_amount_wei"], "25000000000000000")

        resolved = self.store.resolve_dispute(
            dispute_id=disputes[0]["id"],
            resolution_status="upheld",
            reason="manual review confirmed issue",
            operator_id="operator-1",
            payload={"score_delta": -10},
        )
        assert resolved is not None
        self.assertEqual(resolved["status"], "upheld")
        self.assertEqual(resolved["resolution"]["operator_id"], "operator-1")
        self.assertEqual(resolved["bond_status"], "awarded")
        self.assertEqual(resolved["resolution"]["bond_outcome"]["status"], "awarded")

        worker_reputation = self.store.get_actor_reputation("worker-disputed")
        self.assertEqual(worker_reputation["score"], 70)
        self.assertEqual(worker_reputation["violations"], 1)

        reviewer_reputation = self.store.get_actor_reputation("reviewer-1", actor_type="reviewer")
        self.assertEqual(reviewer_reputation["score"], 105)
        self.assertEqual(reviewer_reputation["metadata"]["last_dispute_bond_outcome"], "awarded")

        dispute_events = self.store.list_score_events(task_id="dispute-task")
        event_types = {item["event_type"] for item in dispute_events}
        self.assertIn("policy-violation", event_types)
        self.assertIn("challenge-open", event_types)
        self.assertIn("challenge-upheld", event_types)
        self.assertIn("dispute-bond-awarded", event_types)

        actions = self.store.list_governance_actions(actor_id="worker-disputed")
        action_types = {item["action_type"] for item in actions}
        self.assertIn("dispute-opened", action_types)
        self.assertIn("dispute-resolved", action_types)

    def test_dismissed_dispute_rewards_actor_and_penalizes_challenger(self) -> None:
        self.store.add_task(TaskEnvelope(id="dismiss-task", kind="exec", payload={}, role="worker"))
        opened = self.store.open_dispute(
            task_id="dismiss-task",
            challenger_id="reviewer-dismiss",
            actor_id="worker-dismissed",
            actor_type="worker",
            reason="false alarm",
            evidence_hash="evidence-dismiss",
            severity="medium",
            bond_amount_wei="9000000000000000",
        )
        dispute_id = opened["dispute"]["id"]
        resolved = self.store.resolve_dispute(
            dispute_id=dispute_id,
            resolution_status="dismissed",
            reason="challenge rejected",
            operator_id="operator-dismiss",
        )
        assert resolved is not None
        self.assertEqual(resolved["status"], "dismissed")
        self.assertEqual(resolved["bond_status"], "slashed")

        worker_reputation = self.store.get_actor_reputation("worker-dismissed")
        self.assertEqual(worker_reputation["score"], 103)
        self.assertEqual(worker_reputation["metadata"]["last_dispute_bond_outcome"], "cleared")
        reviewer_reputation = self.store.get_actor_reputation("reviewer-dismiss", actor_type="reviewer")
        self.assertEqual(reviewer_reputation["score"], 95)
        self.assertEqual(reviewer_reputation["metadata"]["last_dispute_bond_outcome"], "slashed")

        dispute_events = self.store.list_score_events(task_id="dismiss-task")
        event_types = {item["event_type"] for item in dispute_events}
        self.assertIn("dispute-cleared", event_types)
        self.assertIn("challenge-open", event_types)
        self.assertIn("challenge-dismissed", event_types)
        self.assertIn("dispute-bond-slashed", event_types)

    def test_terminal_failure_generates_deterministic_fail_event(self) -> None:
        self.store.add_task(TaskEnvelope(id="fail-task", kind="exec", payload={}, role="worker"))
        claimed = self.store.claim_task(worker_id="worker-fail", worker_capabilities=["worker"], lease_seconds=30)
        assert claimed is not None
        self.assertTrue(
            self.store.ack_task(
                task_id="fail-task",
                worker_id="worker-fail",
                lease_token=claimed["lease_token"],
                success=False,
                requeue=False,
                error_message="deterministic mismatch",
            )
        )
        events = self.store.list_score_events(actor_id="worker-fail")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "deterministic-fail")
        self.assertEqual(events[0]["points"], -12)

    def test_terminal_review_failure_generates_subjective_reject_event(self) -> None:
        self.store.add_task(TaskEnvelope(id="reject-task", kind="review", payload={}, role="reviewer"))
        claimed = self.store.claim_task(worker_id="reviewer-fail", worker_capabilities=["reviewer"], lease_seconds=30)
        assert claimed is not None
        self.assertTrue(
            self.store.ack_task(
                task_id="reject-task",
                worker_id="reviewer-fail",
                lease_token=claimed["lease_token"],
                success=False,
                requeue=False,
                error_message="review rejected",
            )
        )
        events = self.store.list_score_events(actor_id="reviewer-fail")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "subjective-reject")
        self.assertEqual(events[0]["points"], -8)

    def test_committee_votes_can_auto_resolve_or_escalate_dispute(self) -> None:
        self.store.add_task(TaskEnvelope(id="committee-task", kind="exec", payload={}, role="worker"))
        opened = self.store.open_dispute(
            task_id="committee-task",
            challenger_id="reviewer-committee",
            actor_id="worker-committee",
            actor_type="worker",
            reason="committee challenge",
            evidence_hash="committee-evidence",
            severity="medium",
            committee_quorum=2,
            committee_deadline="2030-01-01T00:00:00Z",
        )
        dispute_id = opened["dispute"]["id"]
        self.assertEqual(opened["dispute"]["committee_quorum"], 2)
        self.assertEqual(opened["dispute"]["committee_tally"]["approve"], 0)

        first_vote = self.store.vote_dispute(
            dispute_id=dispute_id,
            voter_id="committee-a",
            decision="approve",
            note="looks valid",
        )
        assert first_vote is not None
        self.assertEqual(first_vote["status"], "open")
        self.assertEqual(first_vote["committee_tally"]["approve"], 1)
        self.assertEqual(len(first_vote["committee_votes"]), 1)

        second_vote = self.store.vote_dispute(
            dispute_id=dispute_id,
            voter_id="committee-b",
            decision="approve",
            note="confirmed",
        )
        assert second_vote is not None
        self.assertEqual(second_vote["status"], "upheld")
        self.assertEqual(second_vote["resolution"]["operator_id"], "committee:committee-b")

        committee_actions = self.store.list_governance_actions(actor_id="committee-b")
        self.assertEqual(committee_actions[0]["action_type"], "dispute-voted")

        opened_escalated = self.store.open_dispute(
            task_id="committee-task",
            challenger_id="reviewer-committee-2",
            actor_id="worker-committee",
            actor_type="worker",
            reason="split committee",
            evidence_hash="committee-evidence-2",
            severity="medium",
            committee_quorum=2,
        )
        escalated_id = opened_escalated["dispute"]["id"]
        self.store.vote_dispute(dispute_id=escalated_id, voter_id="committee-c", decision="approve")
        escalated = self.store.vote_dispute(dispute_id=escalated_id, voter_id="committee-d", decision="abstain")
        assert escalated is not None
        self.assertEqual(escalated["status"], "escalated")
        self.assertEqual(escalated["resolution"]["payload"]["committee_tally"]["abstain"], 1)
