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
                retry_backoff_seconds=1,
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
        time.sleep(1.1)

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
