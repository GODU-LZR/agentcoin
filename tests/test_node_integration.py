from __future__ import annotations

import json
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib import error, request

from agentcoin.config import NodeConfig, PeerConfig
from agentcoin.node import AgentCoinNode


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class NodeHarness:
    def __init__(self, *, node_id: str, token: str, db_path: str, capabilities: list[str], peers: list[PeerConfig] | None = None,
                 local_dispatch_fallback: bool = True, outbox_max_attempts: int = 3, git_root: str | None = None,
                 signing_secret: str | None = None, require_signed_inbox: bool = False) -> None:
        self.port = _free_port()
        self.config = NodeConfig(
            node_id=node_id,
            auth_token=token,
            signing_secret=signing_secret,
            require_signed_inbox=require_signed_inbox,
            host="127.0.0.1",
            port=self.port,
            database_path=db_path,
            git_root=git_root,
            sync_interval_seconds=3600,
            capabilities=capabilities,
            peers=peers or [],
            local_dispatch_fallback=local_dispatch_fallback,
            outbox_max_attempts=outbox_max_attempts,
            task_retry_limit=2,
            task_retry_backoff_seconds=1,
        )
        self.node = AgentCoinNode(self.config)
        self.thread = threading.Thread(target=self.node.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self.thread.start()
        time.sleep(0.4)

    def stop(self) -> None:
        self.node.shutdown()
        self.thread.join(timeout=2)


class NodeIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _post(self, url: str, token: str, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _get(self, url: str) -> tuple[int, dict]:
        with request.urlopen(url, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _init_git_repo(self, repo_path: Path) -> None:
        repo_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "AgentCoin Test"], cwd=repo_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "agentcoin@example.com"], cwd=repo_path, check=True, capture_output=True, text=True)
        (repo_path / "README.txt").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.txt"], cwd=repo_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True, capture_output=True, text=True)

    def test_outbox_delivery_ack_and_inbox_dedupe(self) -> None:
        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "b.db"),
            capabilities=["worker"],
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "a.db"),
            capabilities=["planner"],
            peers=[PeerConfig(peer_id="node-b", name="Node B", url=node_b.base_url, auth_token="token-b")],
        )
        node_b.start()
        node_a.start()
        try:
            self._post(f"{node_a.base_url}/v1/tasks", "token-a", {"id": "deliver-1", "kind": "notify", "payload": {"x": 1}, "deliver_to": "node-b"})

            status, flushed = self._post(f"{node_a.base_url}/v1/outbox/flush", "token-a", {})
            self.assertEqual(status, 200)
            self.assertEqual(flushed["flushed"], 1)

            _, tasks = self._get(f"{node_b.base_url}/v1/tasks")
            received = [item for item in tasks["items"] if item["id"] == "deliver-1"]
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0]["delivery_status"], "local")

            self._post(f"{node_b.base_url}/v1/inbox", "token-b", {"id": "deliver-1", "kind": "notify", "payload": {"x": 1}, "sender": "node-a"})
            _, tasks_after = self._get(f"{node_b.base_url}/v1/tasks")
            received_after = [item for item in tasks_after["items"] if item["id"] == "deliver-1"]
            self.assertEqual(len(received_after), 1)
        finally:
            node_a.stop()
            node_b.stop()

    def test_signed_peer_sync_and_signed_inbox_verification(self) -> None:
        shared_a = "node-a-shared-secret"
        shared_b = "node-b-shared-secret"
        peer_for_a = PeerConfig(
            peer_id="node-b",
            name="Node B",
            url="http://127.0.0.1:1",
            auth_token="token-b",
            signing_secret=shared_b,
        )
        peer_for_b = PeerConfig(
            peer_id="node-a",
            name="Node A",
            url="http://127.0.0.1:1",
            auth_token="token-a",
            signing_secret=shared_a,
        )
        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "signed-b.db"),
            capabilities=["worker"],
            peers=[peer_for_b],
            signing_secret=shared_b,
            require_signed_inbox=True,
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "signed-a.db"),
            capabilities=["planner"],
            peers=[peer_for_a],
            signing_secret=shared_a,
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.config.peers[0].url = node_a.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["status"], "ok")
            self.assertTrue(sync_payload["items"][0]["signed"])

            self._post(
                f"{node_a.base_url}/v1/tasks",
                "token-a",
                {"id": "signed-deliver-1", "kind": "notify", "payload": {"x": 2}, "deliver_to": "node-b"},
            )
            _, flushed = self._post(f"{node_a.base_url}/v1/outbox/flush", "token-a", {})
            self.assertEqual(flushed["flushed"], 1)

            _, tasks = self._get(f"{node_b.base_url}/v1/tasks")
            received = [item for item in tasks["items"] if item["id"] == "signed-deliver-1"]
            self.assertEqual(len(received), 1)
            self.assertTrue(received[0]["payload"]["_verification"]["verified"])
            self.assertEqual(received[0]["payload"]["_verification"]["key_id"], "node-a")

            bad_status, bad_payload = self._post(
                f"{node_b.base_url}/v1/inbox",
                "token-b",
                {
                    "id": "unsigned-deliver-1",
                    "kind": "notify",
                    "payload": {"x": 3},
                    "sender": "node-a",
                    "_signature": {
                        "alg": "hmac-sha256",
                        "key_id": "node-a",
                        "scope": "task-envelope",
                        "signed_at": "2026-01-01T00:00:00Z",
                        "value": "deadbeef",
                    },
                },
            )
            self.assertEqual(bad_status, 400)
            self.assertIn("signature", bad_payload["error"])
        finally:
            node_a.stop()
            node_b.stop()

    def test_remote_dispatch_falls_back_or_dead_letters(self) -> None:
        bad_peer = PeerConfig(peer_id="peer-bad", name="Bad Peer", url="http://127.0.0.1:19999", auth_token="x")
        fallback_node = NodeHarness(
            node_id="fallback-node",
            token="token-f",
            db_path=str(Path(self.tempdir.name) / "fallback.db"),
            capabilities=["worker"],
            peers=[bad_peer],
            local_dispatch_fallback=True,
            outbox_max_attempts=1,
        )
        dead_node = NodeHarness(
            node_id="dead-node",
            token="token-d",
            db_path=str(Path(self.tempdir.name) / "dead.db"),
            capabilities=["planner"],
            peers=[bad_peer],
            local_dispatch_fallback=False,
            outbox_max_attempts=1,
        )
        fallback_node.start()
        dead_node.start()
        try:
            self._post(
                f"{fallback_node.base_url}/v1/tasks/dispatch",
                "token-f",
                {"id": "remote-fallback", "kind": "code", "deliver_to": "peer-bad", "required_capabilities": ["worker"]},
            )
            _, pre_claim = self._post(
                f"{fallback_node.base_url}/v1/tasks/claim",
                "token-f",
                {"worker_id": "worker-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self.assertIsNone(pre_claim["task"])
            self._post(f"{fallback_node.base_url}/v1/outbox/flush", "token-f", {})
            _, post_claim = self._post(
                f"{fallback_node.base_url}/v1/tasks/claim",
                "token-f",
                {"worker_id": "worker-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self.assertEqual(post_claim["task"]["id"], "remote-fallback")
            self.assertEqual(post_claim["task"]["delivery_status"], "fallback-local")

            self._post(
                f"{dead_node.base_url}/v1/tasks/dispatch",
                "token-d",
                {"id": "remote-dead", "kind": "code", "deliver_to": "peer-bad", "required_capabilities": ["worker"]},
            )
            self._post(f"{dead_node.base_url}/v1/outbox/flush", "token-d", {})
            _, dead_tasks = self._get(f"{dead_node.base_url}/v1/tasks/dead-letter")
            ids = {item["id"]: item for item in dead_tasks["items"]}
            self.assertIn("remote-dead", ids)
            self.assertEqual(ids["remote-dead"]["delivery_status"], "dead-letter")
        finally:
            fallback_node.stop()
            dead_node.stop()

    def test_workflow_merge_and_finalize_via_http(self) -> None:
        node = NodeHarness(
            node_id="workflow-node",
            token="token-w",
            db_path=str(Path(self.tempdir.name) / "workflow.db"),
            capabilities=["planner", "worker", "reviewer"],
        )
        node.start()
        try:
            self._post(f"{node.base_url}/v1/tasks", "token-w", {"id": "root", "kind": "plan", "role": "planner"})
            self._post(
                f"{node.base_url}/v1/workflows/fanout",
                "token-w",
                {
                    "parent_task_id": "root",
                    "subtasks": [
                        {"id": "branch-a", "kind": "code", "role": "worker", "branch": "feature/a"},
                        {"id": "branch-b", "kind": "code", "role": "worker", "branch": "feature/b"},
                    ],
                },
            )
            self._post(
                f"{node.base_url}/v1/workflows/merge",
                "token-w",
                {
                    "workflow_id": "root",
                    "parent_task_ids": ["branch-a", "branch-b"],
                    "task": {"id": "merge-1", "kind": "merge", "role": "reviewer", "branch": "main"},
                },
            )

            _, before = self._get(f"{node.base_url}/v1/workflows/summary?workflow_id=root")
            self.assertIn("merge-1", before["blocked_task_ids"])

            for worker_id in ["branch-a", "branch-b"]:
                _, claim = self._post(
                    f"{node.base_url}/v1/tasks/claim",
                    "token-w",
                    {"worker_id": f"{worker_id}-worker", "worker_capabilities": ["worker"], "lease_seconds": 30},
                )
                self.assertEqual(claim["task"]["id"], worker_id)
                self._post(
                    f"{node.base_url}/v1/tasks/ack",
                    "token-w",
                    {
                        "task_id": worker_id,
                        "worker_id": claim["task"]["locked_by"],
                        "lease_token": claim["task"]["lease_token"],
                        "success": True,
                        "result": {"done": worker_id},
                    },
                )

            _, reviewer_claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-w",
                {"worker_id": "reviewer-1", "worker_capabilities": ["reviewer"], "lease_seconds": 30},
            )
            self.assertEqual(reviewer_claim["task"]["id"], "merge-1")
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-w",
                {
                    "task_id": "merge-1",
                    "worker_id": reviewer_claim["task"]["locked_by"],
                    "lease_token": reviewer_claim["task"]["lease_token"],
                    "success": True,
                    "result": {"merged": ["branch-a", "branch-b"]},
                },
            )

            status, finalized = self._post(f"{node.base_url}/v1/workflows/finalize", "token-w", {"workflow_id": "root"})
            self.assertEqual(status, 200)
            self.assertTrue(finalized["ok"])
            self.assertEqual(finalized["status"], "completed")
        finally:
            node.stop()

    def test_protected_merge_requires_review_approval(self) -> None:
        node = NodeHarness(
            node_id="protected-workflow-node",
            token="token-p",
            db_path=str(Path(self.tempdir.name) / "protected.db"),
            capabilities=["planner", "worker", "reviewer"],
        )
        node.start()
        try:
            self._post(f"{node.base_url}/v1/tasks", "token-p", {"id": "root-protected", "kind": "plan", "role": "planner"})
            self._post(
                f"{node.base_url}/v1/workflows/fanout",
                "token-p",
                {
                    "parent_task_id": "root-protected",
                    "subtasks": [
                        {"id": "branch-a", "kind": "code", "role": "worker", "branch": "feature/a"},
                        {"id": "branch-b", "kind": "code", "role": "worker", "branch": "feature/b"},
                    ],
                },
            )
            self._post(
                f"{node.base_url}/v1/workflows/review-gate",
                "token-p",
                {
                    "workflow_id": "root-protected",
                    "reviews": [
                        {"id": "review-a", "kind": "review", "role": "reviewer", "payload": {"_review": {"target_task_id": "branch-a"}}},
                        {"id": "review-b", "kind": "review", "role": "reviewer", "payload": {"_review": {"target_task_id": "branch-b"}}},
                    ],
                },
            )
            self._post(
                f"{node.base_url}/v1/workflows/merge",
                "token-p",
                {
                    "workflow_id": "root-protected",
                    "parent_task_ids": ["branch-a", "branch-b"],
                    "protected_branches": ["feature/a", "feature/b"],
                    "required_approvals_per_branch": 1,
                    "task": {"id": "merge-protected", "kind": "merge", "role": "reviewer", "branch": "main"},
                },
            )

            for worker_id in ["branch-a", "branch-b"]:
                _, claim = self._post(
                    f"{node.base_url}/v1/tasks/claim",
                    "token-p",
                    {"worker_id": f"{worker_id}-worker", "worker_capabilities": ["worker"], "lease_seconds": 30},
                )
                self.assertEqual(claim["task"]["id"], worker_id)
                self._post(
                    f"{node.base_url}/v1/tasks/ack",
                    "token-p",
                    {
                        "task_id": worker_id,
                        "worker_id": claim["task"]["locked_by"],
                        "lease_token": claim["task"]["lease_token"],
                        "success": True,
                        "result": {"done": worker_id},
                    },
                )

            _, first_review_claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-p",
                {"worker_id": "reviewer-a", "worker_capabilities": ["reviewer"], "lease_seconds": 30},
            )
            self.assertIn(first_review_claim["task"]["id"], {"review-a", "review-b"})

            _, summary_before = self._get(f"{node.base_url}/v1/workflows/summary?workflow_id=root-protected")
            self.assertFalse(summary_before["merge_gate_status"]["merge-protected"]["satisfied"])

            pending_reviews = {"review-a", "review-b"}
            first_id = first_review_claim["task"]["id"]
            pending_reviews.remove(first_id)
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-p",
                {
                    "task_id": first_id,
                    "worker_id": first_review_claim["task"]["locked_by"],
                    "lease_token": first_review_claim["task"]["lease_token"],
                    "success": True,
                    "result": {"approved": True},
                },
            )

            _, second_review_claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-p",
                {"worker_id": "reviewer-b", "worker_capabilities": ["reviewer"], "lease_seconds": 30},
            )
            second_id = next(iter(pending_reviews))
            self.assertEqual(second_review_claim["task"]["id"], second_id)
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-p",
                {
                    "task_id": second_id,
                    "worker_id": second_review_claim["task"]["locked_by"],
                    "lease_token": second_review_claim["task"]["lease_token"],
                    "success": True,
                    "result": {"approved": True},
                },
            )

            _, merge_claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-p",
                {"worker_id": "merge-reviewer", "worker_capabilities": ["reviewer"], "lease_seconds": 30},
            )
            self.assertEqual(merge_claim["task"]["id"], "merge-protected")
        finally:
            node.stop()

    def test_git_status_branch_diff_and_task_context(self) -> None:
        repo_path = Path(self.tempdir.name) / "repo"
        self._init_git_repo(repo_path)
        (repo_path / "README.txt").write_text("hello\nchange\n", encoding="utf-8")

        node = NodeHarness(
            node_id="git-node",
            token="token-g",
            db_path=str(Path(self.tempdir.name) / "git.db"),
            capabilities=["planner", "worker"],
            git_root=str(repo_path),
        )
        node.start()
        try:
            _, status = self._get(f"{node.base_url}/v1/git/status")
            self.assertTrue(status["is_dirty"])
            tracked = set(status["staged_files"]) | set(status["unstaged_files"]) | set(status["untracked_files"])
            self.assertIn("README.txt", tracked)

            created_status, branch = self._post(
                f"{node.base_url}/v1/git/branch",
                "token-g",
                {"name": "agentcoin/test-branch", "from_ref": "HEAD", "checkout": False},
            )
            self.assertEqual(created_status, 201)
            self.assertEqual(branch["branch"], "agentcoin/test-branch")

            _, diff = self._get(f"{node.base_url}/v1/git/diff?base_ref=HEAD&name_only=1")
            self.assertIn("README.txt", diff["files"])

            self._post(
                f"{node.base_url}/v1/tasks",
                "token-g",
                {
                    "id": "git-task-1",
                    "kind": "code",
                    "payload": {"goal": "use git context"},
                    "attach_git_context": True,
                    "git_base_ref": "HEAD",
                },
            )
            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            git_task = [item for item in tasks["items"] if item["id"] == "git-task-1"][0]
            self.assertEqual(git_task["payload"]["_git"]["repo_root"], str(repo_path.resolve()))
            self.assertIn("README.txt", git_task["payload"]["_git"]["changed_files"])

            _, attached = self._post(
                f"{node.base_url}/v1/git/task-context",
                "token-g",
                {"task_id": "git-task-1", "base_ref": "HEAD"},
            )
            self.assertTrue(attached["updated"])
            self.assertEqual(attached["task_id"], "git-task-1")

            self._post(
                f"{node.base_url}/v1/workflows/review-gate",
                "token-g",
                {
                    "workflow_id": "git-task-1",
                    "reviews": [
                        {
                            "id": "git-review-human",
                            "kind": "review",
                            "role": "reviewer",
                            "payload": {"_review": {"target_task_id": "git-task-1", "reviewer_type": "human"}},
                        },
                        {
                            "id": "git-review-ai",
                            "kind": "review",
                            "role": "reviewer",
                            "payload": {"_review": {"target_task_id": "git-task-1", "reviewer_type": "ai"}},
                        },
                    ],
                },
            )
            _, tasks_after_reviews = self._get(f"{node.base_url}/v1/tasks")
            review_tasks = {item["id"]: item for item in tasks_after_reviews["items"] if item["id"].startswith("git-review-")}
            self.assertEqual(review_tasks["git-review-human"]["payload"]["_review"]["reviewer_type"], "human")
            self.assertEqual(review_tasks["git-review-ai"]["payload"]["_review"]["reviewer_type"], "ai")
            self.assertEqual(review_tasks["git-review-human"]["payload"]["_git"]["repo_root"], str(repo_path.resolve()))
        finally:
            node.stop()
