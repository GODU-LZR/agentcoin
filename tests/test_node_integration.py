from __future__ import annotations

import json
import socket
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
                 local_dispatch_fallback: bool = True, outbox_max_attempts: int = 3) -> None:
        self.port = _free_port()
        self.config = NodeConfig(
            node_id=node_id,
            auth_token=token,
            host="127.0.0.1",
            port=self.port,
            database_path=db_path,
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
