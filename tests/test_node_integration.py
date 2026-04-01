from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request

from agentcoin.adapters import AdapterPolicy
from agentcoin.config import NodeConfig, PeerConfig
from agentcoin.net import OutboundNetworkConfig
from agentcoin.node import AgentCoinNode
from agentcoin.onchain import OnchainBindings
from agentcoin.security import sign_document_with_ssh, verify_document
from agentcoin.worker import WorkerLoop


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class NodeHarness:
    def __init__(self, *, node_id: str, token: str, db_path: str, capabilities: list[str], peers: list[PeerConfig] | None = None,
                 local_dispatch_fallback: bool = True, outbox_max_attempts: int = 3, git_root: str | None = None,
                 signing_secret: str | None = None, require_signed_inbox: bool = False,
                 identity_principal: str | None = None, identity_private_key_path: str | None = None,
                 identity_public_key: str | None = None, onchain: OnchainBindings | None = None,
                 network: OutboundNetworkConfig | None = None, runtimes: list[str] | None = None,
                 bridges: list[str] | None = None) -> None:
        self.port = _free_port()
        self.config = NodeConfig(
            node_id=node_id,
            auth_token=token,
            signing_secret=signing_secret,
            require_signed_inbox=require_signed_inbox,
            identity_principal=identity_principal,
            identity_private_key_path=identity_private_key_path,
            identity_public_key=identity_public_key,
            host="127.0.0.1",
            port=self.port,
            database_path=db_path,
            git_root=git_root,
            sync_interval_seconds=3600,
            capabilities=capabilities,
            runtimes=runtimes or ["python"],
            bridges=bridges or ["mcp", "a2a"],
            peers=peers or [],
            local_dispatch_fallback=local_dispatch_fallback,
            outbox_max_attempts=outbox_max_attempts,
            task_retry_limit=2,
            task_retry_backoff_seconds=1,
            network=network or OutboundNetworkConfig(),
            onchain=onchain or OnchainBindings(),
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


class RpcHarness:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []
        self.port = _free_port()
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), self._build_handler())
        self.thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        harness = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
                payload = json.loads(raw.decode("utf-8"))
                harness.calls.append(payload)
                method = str(payload.get("method") or "")
                response = harness.responses.get(method)
                if callable(response):
                    response = response(payload)
                body = {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": response,
                }
                encoded = json.dumps(body).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler

    def start(self) -> None:
        self.thread.start()
        time.sleep(0.2)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self.thread.join(timeout=2)


class HttpAgentHarness:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.port = _free_port()
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), self._build_handler())
        self.thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/invoke"

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        harness = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
                payload = json.loads(raw.decode("utf-8"))
                harness.calls.append(payload)
                response = {
                    "runtime": "http-json",
                    "accepted": True,
                    "task_id": payload.get("task", {}).get("id"),
                    "worker_id": payload.get("worker_id"),
                    "echo": payload.get("task", {}).get("payload", {}).get("input"),
                }
                encoded = json.dumps(response).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler

    def start(self) -> None:
        self.thread.start()
        time.sleep(0.2)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self.thread.join(timeout=2)


class OllamaHarness:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.port = _free_port()
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), self._build_handler())
        self.thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/chat"

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        harness = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
                payload = json.loads(raw.decode("utf-8"))
                harness.calls.append(payload)
                response = {
                    "model": payload.get("model"),
                    "message": {
                        "role": "assistant",
                        "content": f"ollama:{payload.get('messages', [{}])[-1].get('content', '')}",
                    },
                    "done": True,
                    "done_reason": "stop",
                }
                encoded = json.dumps(response).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler

    def start(self) -> None:
        self.thread.start()
        time.sleep(0.2)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self.thread.join(timeout=2)


class OpenAICompatHarness:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.headers: list[dict[str, str]] = []
        self.port = _free_port()
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), self._build_handler())
        self.thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1/chat/completions"

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        harness = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
                payload = json.loads(raw.decode("utf-8"))
                harness.calls.append(payload)
                harness.headers.append({key: value for key, value in self.headers.items()})
                response = {
                    "id": "chatcmpl-openclaw-1",
                    "object": "chat.completion",
                    "model": payload.get("model"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": f"openai:{payload.get('messages', [{}])[-1].get('content', '')}",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
                encoded = json.dumps(response).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler

    def start(self) -> None:
        self.thread.start()
        time.sleep(0.2)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
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

    def _generate_identity(self, key_path: Path, principal: str) -> tuple[str, str]:
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", principal, "-f", str(key_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return str(key_path), Path(f"{key_path}.pub").read_text(encoding="utf-8").strip()

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

    def test_card_and_task_expose_semantic_shapes(self) -> None:
        node = NodeHarness(
            node_id="semantic-node",
            token="token-semantic",
            db_path=str(Path(self.tempdir.name) / "semantic.db"),
            capabilities=["worker", "reviewer"],
        )
        node.start()
        try:
            _, card = self._get(f"{node.base_url}/v1/card")
            self.assertEqual(card["semantics"]["@type"], "agentcoin:AgentCard")
            self.assertEqual(card["semantics"]["@context"], "https://agentcoin.ai/ns/context/v0.1")
            self.assertIn("worker", card["semantics"]["capabilities"])

            _, context_payload = self._get(f"{node.base_url}/v1/schema/context")
            self.assertIn("@context", context_payload)
            self.assertIn("agentcoin", context_payload["@context"])

            _, capability_schema = self._get(f"{node.base_url}/v1/schema/capabilities")
            capability_ids = {item["id"] for item in capability_schema["capabilities"]}
            self.assertIn("reviewer", capability_ids)
            self.assertIn("ai-reviewer", capability_ids)

            _, examples = self._get(f"{node.base_url}/v1/schema/examples")
            self.assertEqual(examples["task_envelope"]["@type"], "agentcoin:TaskEnvelope")

            self._post(
                f"{node.base_url}/v1/tasks",
                "token-semantic",
                {
                    "id": "semantic-task-1",
                    "kind": "generic",
                    "role": "worker",
                    "required_capabilities": ["worker"],
                    "payload": {"input": "semantic"},
                },
            )
            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "semantic-task-1"][0]
            self.assertEqual(task["semantics"]["@type"], "agentcoin:TaskEnvelope")
            self.assertEqual(task["semantics"]["role"], "worker")
            self.assertEqual(task["semantics"]["required_capabilities"], ["worker"])
        finally:
            node.stop()

    def test_semantic_capability_negotiation_selects_peer_and_local_worker(self) -> None:
        node_b = NodeHarness(
            node_id="semantic-peer-b",
            token="token-sem-b",
            db_path=str(Path(self.tempdir.name) / "semantic-peer-b.db"),
            capabilities=["ai-reviewer"],
        )
        node_c = NodeHarness(
            node_id="semantic-peer-c",
            token="token-sem-c",
            db_path=str(Path(self.tempdir.name) / "semantic-peer-c.db"),
            capabilities=["reviewer"],
        )
        node_a = NodeHarness(
            node_id="semantic-peer-a",
            token="token-sem-a",
            db_path=str(Path(self.tempdir.name) / "semantic-peer-a.db"),
            capabilities=["human-reviewer"],
            peers=[
                PeerConfig(peer_id="semantic-peer-b", name="Semantic Peer B", url="", auth_token="token-sem-b"),
                PeerConfig(peer_id="semantic-peer-c", name="Semantic Peer C", url="", auth_token="token-sem-c"),
            ],
        )
        node_b.start()
        node_c.start()
        node_a.config.peers[0].url = node_b.base_url
        node_a.config.peers[1].url = node_c.base_url
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-sem-a", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["status"], "ok")
            self.assertEqual(sync_payload["items"][1]["status"], "ok")

            _, preview = self._get(f"{node_a.base_url}/v1/tasks/dispatch/preview?required_capabilities=reviewer")
            self.assertEqual(preview["candidates"][0]["target_ref"], "semantic-peer-c")
            self.assertEqual(preview["candidates"][0]["match"]["exact_matches"], ["reviewer"])

            status, dispatch = self._post(
                f"{node_a.base_url}/v1/tasks/dispatch",
                "token-sem-a",
                {
                    "id": "semantic-dispatch-1",
                    "kind": "review",
                    "role": "reviewer",
                    "required_capabilities": ["reviewer"],
                    "payload": {"input": "review"},
                },
            )
            self.assertEqual(status, 201)
            self.assertEqual(dispatch["target"]["target_type"], "peer")
            self.assertEqual(dispatch["target"]["target_ref"], "semantic-peer-c")

            self._post(
                f"{node_a.base_url}/v1/tasks",
                "token-sem-a",
                {
                    "id": "semantic-local-1",
                    "kind": "review",
                    "role": "reviewer",
                    "required_capabilities": ["reviewer"],
                    "payload": {"input": "local review"},
                },
            )
            worker = WorkerLoop(
                node_url=node_a.base_url,
                token="token-sem-a",
                worker_id="worker-human-review",
                capabilities=["human-reviewer", "reviewer"],
                lease_seconds=30,
            )
            self.assertTrue(worker.run_once())

            _, tasks = self._get(f"{node_a.base_url}/v1/tasks")
            local_task = [item for item in tasks["items"] if item["id"] == "semantic-local-1"][0]
            self.assertEqual(local_task["status"], "completed")
        finally:
            node_a.stop()
            node_b.stop()
            node_c.stop()

    def test_dispatch_evaluate_prefers_peer_with_matching_runtime_support(self) -> None:
        node_b = NodeHarness(
            node_id="runtime-peer-b",
            token="token-runtime-b",
            db_path=str(Path(self.tempdir.name) / "runtime-peer-b.db"),
            capabilities=["reviewer"],
            runtimes=["openai-chat", "python"],
        )
        node_c = NodeHarness(
            node_id="runtime-peer-c",
            token="token-runtime-c",
            db_path=str(Path(self.tempdir.name) / "runtime-peer-c.db"),
            capabilities=["reviewer"],
            runtimes=["python"],
        )
        node_a = NodeHarness(
            node_id="runtime-peer-a",
            token="token-runtime-a",
            db_path=str(Path(self.tempdir.name) / "runtime-peer-a.db"),
            capabilities=["planner"],
            runtimes=["python"],
            peers=[
                PeerConfig(peer_id="runtime-peer-b", name="Runtime Peer B", url="", auth_token="token-runtime-b"),
                PeerConfig(peer_id="runtime-peer-c", name="Runtime Peer C", url="", auth_token="token-runtime-c"),
            ],
        )
        node_b.start()
        node_c.start()
        node_a.config.peers[0].url = node_b.base_url
        node_a.config.peers[1].url = node_c.base_url
        node_a.start()
        try:
            sync_status, _ = self._post(f"{node_a.base_url}/v1/peers/sync", "token-runtime-a", {})
            self.assertEqual(sync_status, 200)

            evaluate_status, evaluated = self._post(
                f"{node_a.base_url}/v1/tasks/dispatch/evaluate",
                "token-runtime-a",
                {
                    "id": "runtime-aware-task",
                    "kind": "review",
                    "role": "reviewer",
                    "required_capabilities": ["reviewer"],
                    "payload": {
                        "_runtime": {
                            "runtime": "openai-chat",
                            "endpoint": "http://127.0.0.1:9999/v1/chat/completions",
                        }
                    },
                },
            )
            self.assertEqual(evaluate_status, 200)
            self.assertEqual(len(evaluated["candidates"]), 1)
            self.assertEqual(evaluated["requirements"]["runtime"], "openai-chat")
            self.assertIsNone(evaluated["requirements"]["bridge_protocol"])
            self.assertEqual(evaluated["candidates"][0]["target_ref"], "runtime-peer-b")
            self.assertEqual(evaluated["candidates"][0]["runtime_match"]["required"], "openai-chat")
            self.assertTrue(evaluated["candidates"][0]["runtime_match"]["supported"])

            dispatch_status, dispatched = self._post(
                f"{node_a.base_url}/v1/tasks/dispatch",
                "token-runtime-a",
                {
                    "id": "runtime-aware-task-2",
                    "kind": "review",
                    "role": "reviewer",
                    "required_capabilities": ["reviewer"],
                    "payload": {
                        "_runtime": {
                            "runtime": "openai-chat",
                            "endpoint": "http://127.0.0.1:9999/v1/chat/completions",
                        }
                    },
                },
            )
            self.assertEqual(dispatch_status, 201)
            self.assertEqual(dispatched["target"]["target_ref"], "runtime-peer-b")
            self.assertEqual(dispatched["task"]["deliver_to"], "runtime-peer-b")
        finally:
            node_a.stop()
            node_b.stop()
            node_c.stop()

    def test_dispatch_evaluate_prefers_peer_with_matching_bridge_support(self) -> None:
        node_b = NodeHarness(
            node_id="bridge-peer-b",
            token="token-bridge-b",
            db_path=str(Path(self.tempdir.name) / "bridge-peer-b.db"),
            capabilities=["worker", "local-command"],
            bridges=["mcp"],
        )
        node_c = NodeHarness(
            node_id="bridge-peer-c",
            token="token-bridge-c",
            db_path=str(Path(self.tempdir.name) / "bridge-peer-c.db"),
            capabilities=["worker", "local-command"],
            bridges=["a2a"],
        )
        node_a = NodeHarness(
            node_id="bridge-peer-a",
            token="token-bridge-a",
            db_path=str(Path(self.tempdir.name) / "bridge-peer-a.db"),
            capabilities=["planner"],
            bridges=["a2a"],
            peers=[
                PeerConfig(peer_id="bridge-peer-b", name="Bridge Peer B", url="", auth_token="token-bridge-b"),
                PeerConfig(peer_id="bridge-peer-c", name="Bridge Peer C", url="", auth_token="token-bridge-c"),
            ],
        )
        node_b.start()
        node_c.start()
        node_a.config.peers[0].url = node_b.base_url
        node_a.config.peers[1].url = node_c.base_url
        node_a.start()
        try:
            sync_status, _ = self._post(f"{node_a.base_url}/v1/peers/sync", "token-bridge-a", {})
            self.assertEqual(sync_status, 200)

            evaluate_status, evaluated = self._post(
                f"{node_a.base_url}/v1/tasks/dispatch/evaluate",
                "token-bridge-a",
                {
                    "id": "bridge-aware-task",
                    "kind": "tool-call",
                    "role": "worker",
                    "required_capabilities": ["local-command"],
                    "payload": {
                        "_bridge": {
                            "protocol": "mcp",
                            "tool_name": "local-command",
                        }
                    },
                },
            )
            self.assertEqual(evaluate_status, 200)
            self.assertEqual(evaluated["requirements"]["bridge_protocol"], "mcp")
            self.assertEqual(len(evaluated["candidates"]), 1)
            self.assertEqual(evaluated["candidates"][0]["target_ref"], "bridge-peer-b")
            self.assertTrue(evaluated["candidates"][0]["bridge_match"]["supported"])
            self.assertEqual(evaluated["candidates"][0]["bridge_match"]["required"], "mcp")
        finally:
            node_a.stop()
            node_b.stop()
            node_c.stop()

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

    def test_ssh_identity_signed_delivery_and_receipt_verification(self) -> None:
        key_a, pub_a = self._generate_identity(Path(self.tempdir.name) / "id_a", "node-a")
        key_b, pub_b = self._generate_identity(Path(self.tempdir.name) / "id_b", "node-b")

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-b.db"),
            capabilities=["worker"],
            peers=[
                PeerConfig(
                    peer_id="node-a",
                    name="Node A",
                    url="http://127.0.0.1:1",
                    auth_token="token-a",
                    identity_principal="node-a",
                    identity_public_key=pub_a,
                )
            ],
            require_signed_inbox=True,
            identity_principal="node-b",
            identity_private_key_path=key_b,
            identity_public_key=pub_b,
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-a.db"),
            capabilities=["planner"],
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b,
                )
            ],
            identity_principal="node-a",
            identity_private_key_path=key_a,
            identity_public_key=pub_a,
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.config.peers[0].url = node_a.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["status"], "ok")
            self.assertTrue(sync_payload["items"][0]["identity_signed"])

            self._post(
                f"{node_a.base_url}/v1/tasks",
                "token-a",
                {"id": "ssh-deliver-1", "kind": "notify", "payload": {"x": 7}, "deliver_to": "node-b"},
            )
            flush_status, flushed = self._post(f"{node_a.base_url}/v1/outbox/flush", "token-a", {})
            self.assertEqual(flush_status, 200)
            self.assertEqual(flushed["flushed"], 1)

            _, tasks = self._get(f"{node_b.base_url}/v1/tasks")
            received = [item for item in tasks["items"] if item["id"] == "ssh-deliver-1"]
            self.assertEqual(len(received), 1)
            self.assertTrue(received[0]["payload"]["_verification"]["verified"])
            self.assertEqual(received[0]["payload"]["_verification"]["principal"], "node-a")

            tampered = sign_document_with_ssh(
                {"id": "ssh-bad-1", "kind": "notify", "payload": {"x": 8}, "sender": "node-a"},
                private_key_path=key_a,
                principal="node-a",
                namespace="agentcoin-task",
                public_key=pub_a,
            )
            tampered["_identity_signature"]["value"] = tampered["_identity_signature"]["value"].replace("A", "B", 1)
            bad_status, bad_payload = self._post(f"{node_b.base_url}/v1/inbox", "token-b", tampered)
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

    def test_bridge_registry_import_and_export(self) -> None:
        node = NodeHarness(
            node_id="bridge-node",
            token="token-bridge",
            db_path=str(Path(self.tempdir.name) / "bridge.db"),
            capabilities=["worker", "reviewer"],
        )
        node.start()
        try:
            _, card = self._get(f"{node.base_url}/v1/card")
            self.assertIn("mcp-bridge/0.1", card["protocols"])
            self.assertIn("a2a-bridge/0.1", card["protocols"])
            self.assertTrue(card["endpoints"]["bridge_import"].endswith("/v1/bridges/import"))

            _, bridges = self._get(f"{node.base_url}/v1/bridges")
            protocols = {item["protocol"] for item in bridges["items"]}
            self.assertEqual(protocols, {"mcp", "a2a"})

            import_status, imported = self._post(
                f"{node.base_url}/v1/bridges/import",
                "token-bridge",
                {
                    "protocol": "mcp",
                    "message": {
                        "id": "mcp-req-1",
                        "method": "tools/call",
                        "params": {"name": "reviewer", "arguments": {"path": "README.md"}},
                        "sender": "mcp-client",
                    },
                    "task_overrides": {"id": "bridge-task-1", "role": "worker"},
                },
            )
            self.assertEqual(import_status, 201)
            self.assertEqual(imported["task"]["id"], "bridge-task-1")
            self.assertEqual(imported["task"]["kind"], "tool-call")
            self.assertEqual(imported["task"]["payload"]["_bridge"]["protocol"], "mcp")
            self.assertEqual(imported["task"]["required_capabilities"], ["reviewer"])

            export_status, exported = self._post(
                f"{node.base_url}/v1/bridges/export",
                "token-bridge",
                {
                    "protocol": "mcp",
                    "task_id": "bridge-task-1",
                    "result": {"approved": True, "notes": "ok"},
                },
            )
            self.assertEqual(export_status, 200)
            self.assertEqual(exported["message"]["id"], "mcp-req-1")
            self.assertEqual(exported["message"]["result"]["result"]["approved"], True)

            a2a_status, a2a_imported = self._post(
                f"{node.base_url}/v1/bridges/import",
                "token-bridge",
                {
                    "protocol": "a2a",
                    "message": {
                        "message_id": "a2a-msg-1",
                        "conversation_id": "conv-1",
                        "sender": "agent-b",
                        "intent": "summarize",
                        "content": {"text": "hello world"},
                        "required_capabilities": ["worker"],
                    },
                    "task_overrides": {"id": "bridge-task-2", "role": "worker"},
                },
            )
            self.assertEqual(a2a_status, 201)
            self.assertEqual(a2a_imported["task"]["workflow_id"], "conv-1")
            self.assertEqual(a2a_imported["task"]["payload"]["_bridge"]["protocol"], "a2a")

            a2a_export_status, a2a_exported = self._post(
                f"{node.base_url}/v1/bridges/export",
                "token-bridge",
                {
                    "protocol": "a2a",
                    "task_id": "bridge-task-2",
                    "result": {"summary": "done"},
                },
            )
            self.assertEqual(a2a_export_status, 200)
            self.assertEqual(a2a_exported["message"]["conversation_id"], "conv-1")
            self.assertEqual(a2a_exported["message"]["task"]["result"]["summary"], "done")
        finally:
            node.stop()

    def test_bridge_worker_execution_adapter_skeleton(self) -> None:
        node = NodeHarness(
            node_id="bridge-worker-node",
            token="token-bridge-worker",
            db_path=str(Path(self.tempdir.name) / "bridge-worker.db"),
            capabilities=["worker", "tool-runner", "reviewer"],
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/bridges/import",
                "token-bridge-worker",
                {
                    "protocol": "mcp",
                    "message": {
                        "id": "mcp-exec-1",
                        "method": "tools/call",
                        "params": {"name": "tool-runner", "arguments": {"path": "README.md", "mode": "lint"}},
                        "sender": "mcp-client",
                    },
                    "task_overrides": {"id": "bridge-exec-mcp", "role": "worker"},
                },
            )
            self._post(
                f"{node.base_url}/v1/bridges/import",
                "token-bridge-worker",
                {
                    "protocol": "a2a",
                    "message": {
                        "message_id": "a2a-exec-1",
                        "conversation_id": "conv-exec-1",
                        "sender": "agent-z",
                        "intent": "summarize",
                        "content": {"text": "hello bridge"},
                        "metadata": {"priority": "normal"},
                        "required_capabilities": ["worker"],
                    },
                    "task_overrides": {"id": "bridge-exec-a2a", "role": "worker"},
                },
            )

            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-bridge-worker",
                worker_id="worker-bridge-1",
                capabilities=["worker", "tool-runner", "reviewer"],
                lease_seconds=30,
            )

            self.assertTrue(worker.run_once())
            self.assertTrue(worker.run_once())

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            by_id = {item["id"]: item for item in tasks["items"]}
            self.assertEqual(by_id["bridge-exec-mcp"]["status"], "completed")
            self.assertEqual(by_id["bridge-exec-a2a"]["status"], "completed")
            self.assertEqual(by_id["bridge-exec-mcp"]["result"]["adapter"]["protocol"], "mcp")
            self.assertEqual(by_id["bridge-exec-a2a"]["result"]["adapter"]["protocol"], "a2a")
            self.assertEqual(
                by_id["bridge-exec-mcp"]["result"]["bridge_execution"]["normalized_output"]["content"][0]["data"]["tool_name"],
                "tool-runner",
            )
            self.assertEqual(
                by_id["bridge-exec-a2a"]["result"]["bridge_execution"]["normalized_output"]["content"]["accepted_intent"],
                "summarize",
            )

            _, exported = self._post(
                f"{node.base_url}/v1/bridges/export",
                "token-bridge-worker",
                {"protocol": "mcp", "task_id": "bridge-exec-mcp"},
            )
            self.assertEqual(exported["message"]["result"]["result"]["adapter"]["protocol"], "mcp")

            _, exported_a2a = self._post(
                f"{node.base_url}/v1/bridges/export",
                "token-bridge-worker",
                {"protocol": "a2a", "task_id": "bridge-exec-a2a"},
            )
            self.assertEqual(exported_a2a["message"]["task"]["result"]["adapter"]["protocol"], "a2a")
        finally:
            node.stop()

    def test_adapter_policy_rejects_disallowed_tool(self) -> None:
        node = NodeHarness(
            node_id="policy-node",
            token="token-policy",
            db_path=str(Path(self.tempdir.name) / "policy.db"),
            capabilities=["worker", "reviewer", "forbidden-tool"],
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/bridges/import",
                "token-policy",
                {
                    "protocol": "mcp",
                    "message": {
                        "id": "mcp-policy-1",
                        "method": "tools/call",
                        "params": {"name": "forbidden-tool", "arguments": {"path": "README.md"}},
                        "sender": "mcp-client",
                    },
                    "task_overrides": {"id": "policy-task-1", "role": "worker"},
                },
            )

            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-policy",
                worker_id="worker-policy-1",
                capabilities=["worker", "reviewer", "forbidden-tool"],
                lease_seconds=30,
                adapter_policy=AdapterPolicy(allowed_mcp_tools=["reviewer"]),
            )
            self.assertTrue(worker.run_once())

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "policy-task-1"][0]
            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["result"]["adapter"]["status"], "rejected")
            self.assertEqual(task["result"]["adapter"]["reason"], "tool is not allowlisted")

            _, reputation = self._get(f"{node.base_url}/v1/reputation?actor_id=worker-policy-1")
            self.assertEqual(reputation["violations"], 1)
            self.assertEqual(reputation["score"], 85)
            self.assertFalse(reputation["quarantined"])

            _, violations = self._get(f"{node.base_url}/v1/violations?actor_id=worker-policy-1")
            self.assertEqual(len(violations["items"]), 1)
            self.assertEqual(violations["items"][0]["severity"], "medium")
        finally:
            node.stop()

    def test_repeated_policy_violations_trigger_quarantine(self) -> None:
        node = NodeHarness(
            node_id="policy-quarantine-node",
            token="token-policy-quarantine",
            db_path=str(Path(self.tempdir.name) / "policy-quarantine.db"),
            capabilities=["worker", "forbidden-tool"],
        )
        node.start()
        try:
            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-policy-quarantine",
                worker_id="worker-policy-2",
                capabilities=["worker", "forbidden-tool"],
                lease_seconds=30,
                adapter_policy=AdapterPolicy(allowed_mcp_tools=["safe-tool"]),
            )

            for index in range(3):
                self._post(
                    f"{node.base_url}/v1/bridges/import",
                    "token-policy-quarantine",
                    {
                        "protocol": "mcp",
                        "message": {
                            "id": f"mcp-policy-{index + 1}",
                            "method": "tools/call",
                            "params": {"name": "forbidden-tool", "arguments": {"index": index}},
                            "sender": "mcp-client",
                        },
                        "task_overrides": {"id": f"policy-q-task-{index + 1}", "role": "worker"},
                    },
                )
                self.assertTrue(worker.run_once())

            _, reputation = self._get(f"{node.base_url}/v1/reputation?actor_id=worker-policy-2")
            self.assertEqual(reputation["violations"], 3)
            self.assertEqual(reputation["score"], 55)
            self.assertTrue(reputation["quarantined"])

            _, quarantines = self._get(f"{node.base_url}/v1/quarantines?actor_id=worker-policy-2")
            self.assertEqual(len(quarantines["items"]), 1)
            self.assertTrue(quarantines["items"][0]["active"])

            _, violations = self._get(f"{node.base_url}/v1/violations?actor_id=worker-policy-2")
            self.assertEqual(len(violations["items"]), 3)

            self._post(
                f"{node.base_url}/v1/tasks",
                "token-policy-quarantine",
                {"id": "post-quarantine-task", "kind": "generic", "role": "worker", "payload": {}},
            )
            self.assertFalse(worker.run_once())

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            post_quarantine = [item for item in tasks["items"] if item["id"] == "post-quarantine-task"][0]
            self.assertEqual(post_quarantine["status"], "queued")
        finally:
            node.stop()

    def test_operator_can_quarantine_and_release_worker(self) -> None:
        node = NodeHarness(
            node_id="operator-governance-node",
            token="token-operator",
            db_path=str(Path(self.tempdir.name) / "operator-governance.db"),
            capabilities=["worker"],
            signing_secret="governance-secret",
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-operator",
                {"id": "operator-task-1", "kind": "generic", "role": "worker", "payload": {}},
            )

            status, applied = self._post(
                f"{node.base_url}/v1/quarantines",
                "token-operator",
                {
                    "actor_id": "worker-operator-1",
                    "actor_type": "worker",
                    "operator_id": "admin-1",
                    "scope": "task-claim",
                    "reason": "operator investigation hold",
                    "payload": {"operator": "admin"},
                },
            )
            self.assertEqual(status, 200)
            self.assertTrue(applied["quarantined"])
            self.assertEqual(applied["action"]["operator_id"], "admin-1")
            self.assertEqual(applied["action"]["receipt"]["action_type"], "quarantine-set")
            receipt_verification = verify_document(
                applied["action"]["receipt"],
                secret="governance-secret",
                expected_scope="governance-receipt",
                expected_key_id="operator-governance-node",
            )
            self.assertTrue(receipt_verification["verified"])

            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-operator",
                worker_id="worker-operator-1",
                capabilities=["worker"],
                lease_seconds=30,
            )
            self.assertFalse(worker.run_once())

            _, reputation = self._get(f"{node.base_url}/v1/reputation?actor_id=worker-operator-1")
            self.assertTrue(reputation["quarantined"])

            _, actions_before = self._get(f"{node.base_url}/v1/governance-actions?actor_id=worker-operator-1")
            self.assertEqual(len(actions_before["items"]), 1)
            self.assertEqual(actions_before["items"][0]["action_type"], "quarantine-set")
            self.assertEqual(actions_before["items"][0]["operator_id"], "admin-1")

            status, released = self._post(
                f"{node.base_url}/v1/quarantines/release",
                "token-operator",
                {
                    "actor_id": "worker-operator-1",
                    "actor_type": "worker",
                    "operator_id": "admin-1",
                    "reason": "operator cleared worker",
                    "payload": {"operator": "admin"},
                },
            )
            self.assertEqual(status, 200)
            self.assertFalse(released["quarantined"])
            self.assertEqual(released["action"]["operator_id"], "admin-1")
            self.assertEqual(released["action"]["receipt"]["action_type"], "quarantine-release")
            release_verification = verify_document(
                released["action"]["receipt"],
                secret="governance-secret",
                expected_scope="governance-receipt",
                expected_key_id="operator-governance-node",
            )
            self.assertTrue(release_verification["verified"])

            self.assertTrue(worker.run_once())

            _, actions_after = self._get(f"{node.base_url}/v1/governance-actions?actor_id=worker-operator-1")
            self.assertEqual(len(actions_after["items"]), 2)
            self.assertEqual(actions_after["items"][0]["action_type"], "quarantine-release")
            self.assertEqual(actions_after["items"][0]["operator_id"], "admin-1")
        finally:
            node.stop()

    def test_onchain_task_binding_and_receipt_generation(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example.invalid",
            explorer_base_url="https://testnet.bscscan.com",
            did_registry_address="0x000000000000000000000000000000000000d1d0",
            staking_pool_address="0x00000000000000000000000000000000000057a0",
            bounty_escrow_address="0x000000000000000000000000000000000000b077",
            local_did="did:agentcoin:test:worker-1",
            local_controller_address="0x1111111111111111111111111111111111111111",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="onchain-node",
            token="token-onchain",
            db_path=str(Path(self.tempdir.name) / "onchain.db"),
            capabilities=["worker"],
            signing_secret="onchain-secret",
            onchain=onchain,
        )
        node.start()
        try:
            _, status_payload = self._get(f"{node.base_url}/v1/onchain/status")
            self.assertTrue(status_payload["enabled"])
            self.assertEqual(status_payload["local_identity"]["did"], "did:agentcoin:test:worker-1")
            self.assertIn("transport", status_payload)
            self.assertTrue(status_payload["transport"]["proxy_enabled"])

            created_status, created = self._post(
                f"{node.base_url}/v1/tasks",
                "token-onchain",
                {
                    "id": "onchain-task-1",
                    "kind": "generic",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 42,
                },
            )
            self.assertEqual(created_status, 201)
            self.assertEqual(created["task"]["payload"]["_onchain"]["job_id"], 42)
            self.assertIsNotNone(created["task"]["payload"]["_onchain"]["spec_hash"])

            _, create_intent = self._post(
                f"{node.base_url}/v1/onchain/intents/build",
                "token-onchain",
                {
                    "task_id": "onchain-task-1",
                    "action": "createJob",
                    "params": {
                        "reward_amount_wei": "100000000000000000",
                        "evaluator_address": "0x2222222222222222222222222222222222222222",
                        "stake_required_wei": "25000000000000000",
                        "min_reputation": 80,
                        "deadline": 1893456000,
                    },
                },
            )
            self.assertEqual(create_intent["intent"]["function"], "createJob")
            self.assertEqual(create_intent["intent"]["args"]["minReputation"], 80)
            self.assertEqual(create_intent["intent"]["value_wei"], "100000000000000000")
            create_intent_verification = verify_document(
                create_intent["intent"],
                secret="onchain-secret",
                expected_scope="onchain-intent",
                expected_key_id="onchain-node",
            )
            self.assertTrue(create_intent_verification["verified"])

            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-onchain",
                {"worker_id": "worker-onchain-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            task = claim["task"]
            self.assertEqual(task["id"], "onchain-task-1")

            ack_status, ack_payload = self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-onchain",
                {
                    "task_id": "onchain-task-1",
                    "worker_id": "worker-onchain-1",
                    "lease_token": task["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-onchain-1"},
                },
            )
            self.assertEqual(ack_status, 200)
            self.assertTrue(ack_payload["ok"])

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            stored = [item for item in tasks["items"] if item["id"] == "onchain-task-1"][0]
            receipt = stored["result"]["_onchain_receipt"]
            self.assertEqual(receipt["job_id"], 42)
            self.assertEqual(receipt["intended_contract_action"], "completeJob")
            self.assertIn("submission_hash", receipt)
            self.assertTrue(receipt["receipt_uri"].startswith("ipfs://agentcoin-receipts/"))
            verification = verify_document(
                receipt,
                secret="onchain-secret",
                expected_scope="onchain-receipt",
                expected_key_id="onchain-node",
            )
            self.assertTrue(verification["verified"])

            _, submit_intent = self._post(
                f"{node.base_url}/v1/onchain/intents/build",
                "token-onchain",
                {"task_id": "onchain-task-1", "action": "submitWork"},
            )
            self.assertEqual(submit_intent["intent"]["function"], "submitWork")
            self.assertEqual(submit_intent["intent"]["args"]["jobId"], 42)
            self.assertTrue(submit_intent["intent"]["args"]["submissionHash"].startswith("0x"))

            _, accept_intent = self._post(
                f"{node.base_url}/v1/onchain/intents/build",
                "token-onchain",
                {"task_id": "onchain-task-1", "action": "acceptJob"},
            )
            self.assertEqual(accept_intent["intent"]["function"], "acceptJob")
            self.assertEqual(accept_intent["intent"]["args"]["jobId"], 42)
            self.assertTrue(accept_intent["intent"]["args"]["workerDid"].startswith("0x"))
            self.assertEqual(len(accept_intent["intent"]["args"]["workerDid"]), 66)

            _, complete_intent = self._post(
                f"{node.base_url}/v1/onchain/intents/build",
                "token-onchain",
                {"task_id": "onchain-task-1", "action": "completeJob", "params": {"score": 93}},
            )
            self.assertEqual(complete_intent["intent"]["function"], "completeJob")
            self.assertEqual(complete_intent["intent"]["args"]["score"], 93)
            complete_intent_verification = verify_document(
                complete_intent["intent"],
                secret="onchain-secret",
                expected_scope="onchain-intent",
                expected_key_id="onchain-node",
            )
            self.assertTrue(complete_intent_verification["verified"])

            _, rpc_payload = self._post(
                f"{node.base_url}/v1/onchain/rpc-payload",
                "token-onchain",
                {
                    "task_id": "onchain-task-1",
                    "action": "submitWork",
                    "rpc": {
                        "method": "eth_estimateGas",
                        "nonce": 7,
                        "gas": 250000,
                    },
                },
            )
            self.assertEqual(rpc_payload["rpc_payload"]["rpc_method"], "eth_estimateGas")
            self.assertEqual(rpc_payload["rpc_payload"]["request"]["method"], "eth_estimateGas")
            self.assertEqual(rpc_payload["rpc_payload"]["request"]["params"][0]["nonce"], "0x7")
            self.assertEqual(rpc_payload["rpc_payload"]["request"]["params"][0]["gas"], "0x3d090")
            self.assertEqual(rpc_payload["rpc_payload"]["call"]["function"], "submitWork")
            self.assertTrue(rpc_payload["rpc_payload"]["call"]["abi_encoding_required"])
            rpc_payload_verification = verify_document(
                rpc_payload["rpc_payload"],
                secret="onchain-secret",
                expected_scope="onchain-rpc-payload",
                expected_key_id="onchain-node",
            )
            self.assertTrue(rpc_payload_verification["verified"])

            _, replay = self._get(f"{node.base_url}/v1/tasks/replay-inspect?task_id=onchain-task-1")
            self.assertEqual(replay["onchain_receipt"]["job_id"], 42)
            self.assertEqual(replay["onchain_status"]["job_id"], 42)
            self.assertEqual(replay["onchain_intent_preview"]["submitWork"]["function"], "submitWork")
            self.assertEqual(replay["onchain_intent_preview"]["completeJob"]["function"], "completeJob")
            self.assertEqual(replay["onchain_intent_preview"]["estimateGas"]["rpc_method"], "eth_estimateGas")
        finally:
            node.stop()

    def test_onchain_rpc_plan_and_raw_relay(self) -> None:
        rpc = RpcHarness(
            {
                "eth_getTransactionCount": "0x9",
                "eth_gasPrice": "0x12a05f200",
                "eth_estimateGas": "0x5208",
                "eth_sendRawTransaction": "0xabc123",
            }
        )
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x000000000000000000000000000000000000b077",
            local_did="did:agentcoin:test:worker-2",
            local_controller_address="0x1111111111111111111111111111111111111111",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="onchain-rpc-node",
            token="token-rpc",
            db_path=str(Path(self.tempdir.name) / "onchain-rpc.db"),
            capabilities=["worker"],
            signing_secret="onchain-rpc-secret",
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-rpc",
                {
                    "id": "onchain-rpc-task-1",
                    "kind": "generic",
                    "role": "worker",
                    "payload": {"x": 2},
                    "attach_onchain_context": True,
                    "onchain_job_id": 88,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-rpc",
                {"worker_id": "worker-onchain-rpc", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            task = claim["task"]
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-rpc",
                {
                    "task_id": "onchain-rpc-task-1",
                    "worker_id": "worker-onchain-rpc",
                    "lease_token": task["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-onchain-rpc"},
                },
            )

            _, plan_payload = self._post(
                f"{node.base_url}/v1/onchain/rpc-plan",
                "token-rpc",
                {
                    "task_id": "onchain-rpc-task-1",
                    "action": "submitWork",
                    "rpc": {
                        "data": "0xdeadbeef",
                        "include_estimate_gas": True,
                    },
                },
            )
            plan = plan_payload["plan"]
            self.assertEqual(plan["kind"], "evm-json-rpc-plan")
            self.assertTrue(plan["resolved_live"])
            self.assertEqual(plan["rpc_payload"]["transaction"]["nonce"], "0x9")
            self.assertEqual(plan["rpc_payload"]["transaction"]["gasPrice"], "0x12a05f200")
            self.assertEqual(plan["rpc_payload"]["transaction"]["gas"], "0x5208")
            self.assertEqual(plan["rpc_payload"]["request"]["params"][0]["data"], "0xdeadbeef")
            self.assertFalse(plan["rpc_payload"]["call"]["abi_encoding_required"])
            self.assertEqual([item["method"] for item in rpc.calls[:3]], ["eth_getTransactionCount", "eth_gasPrice", "eth_estimateGas"])
            plan_verification = verify_document(
                plan,
                secret="onchain-rpc-secret",
                expected_scope="onchain-rpc-plan",
                expected_key_id="onchain-rpc-node",
            )
            self.assertTrue(plan_verification["verified"])

            _, relay_payload = self._post(
                f"{node.base_url}/v1/onchain/rpc/send-raw",
                "token-rpc",
                {"raw_transaction": "0x1234abcd"},
            )
            relay = relay_payload["relay"]
            self.assertEqual(relay["tx_hash"], "0xabc123")
            self.assertEqual(relay["rpc_payload"]["request"]["method"], "eth_sendRawTransaction")
            self.assertEqual(relay["rpc_payload"]["request"]["params"], ["0x1234abcd"])
            relay_verification = verify_document(
                relay,
                secret="onchain-rpc-secret",
                expected_scope="onchain-rpc-relay",
                expected_key_id="onchain-rpc-node",
            )
            self.assertTrue(relay_verification["verified"])
            self.assertEqual(rpc.calls[-1]["method"], "eth_sendRawTransaction")
        finally:
            node.stop()
            rpc.stop()

    def test_onchain_settlement_preview_uses_poaw_and_violations(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:settlement-worker",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="onchain-settlement-node",
            token="token-onchain-settlement",
            db_path=str(Path(self.tempdir.name) / "onchain-settlement.db"),
            capabilities=["worker"],
            signing_secret="settlement-secret",
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-onchain-settlement",
                {
                    "id": "settlement-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 77,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-onchain-settlement",
                {"worker_id": "worker-settlement-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-onchain-settlement",
                {
                    "task_id": "settlement-task-1",
                    "worker_id": "worker-settlement-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-settlement-1"},
                },
            )

            _, preview = self._get(f"{node.base_url}/v1/onchain/settlement-preview?task_id=settlement-task-1")
            settlement = preview["settlement"]
            self.assertEqual(settlement["recommended_sequence"], ["submitWork", "completeJob"])
            self.assertEqual(settlement["recommended_resolution"], "completeJob")
            self.assertGreaterEqual(settlement["score"], 80)
            self.assertEqual(settlement["intents"][0]["function"], "submitWork")
            self.assertEqual(settlement["intents"][1]["function"], "completeJob")
            preview_verification = verify_document(
                settlement,
                secret="settlement-secret",
                expected_scope="onchain-settlement-preview",
                expected_key_id="onchain-settlement-node",
            )
            self.assertTrue(preview_verification["verified"])

            node.node.store.record_policy_violation(
                actor_id="worker-settlement-1",
                actor_type="worker",
                task_id="settlement-task-1",
                source="adapter-policy",
                reason="sandbox escape attempt",
                severity="high",
            )
            _, preview_after = self._get(f"{node.base_url}/v1/onchain/settlement-preview?task_id=settlement-task-1")
            settlement_after = preview_after["settlement"]
            self.assertEqual(settlement_after["recommended_sequence"], ["submitWork", "slashJob"])
            self.assertEqual(settlement_after["recommended_resolution"], "slashJob")
            self.assertEqual(settlement_after["intents"][1]["function"], "slashJob")
            self.assertGreater(int(settlement_after["slash_amount_wei"]), 0)

            _, replay = self._get(f"{node.base_url}/v1/tasks/replay-inspect?task_id=settlement-task-1")
            self.assertEqual(replay["onchain_settlement_preview"]["recommended_resolution"], "slashJob")
        finally:
            node.stop()

    def test_dispute_api_drives_challenge_job_preview(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:challenge-worker",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="challenge-node",
            token="token-challenge",
            db_path=str(Path(self.tempdir.name) / "challenge.db"),
            capabilities=["worker"],
            signing_secret="challenge-secret",
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-challenge",
                {
                    "id": "challenge-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 88,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-challenge",
                {"worker_id": "worker-challenge-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-challenge",
                {
                    "task_id": "challenge-task-1",
                    "worker_id": "worker-challenge-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-challenge-1"},
                },
            )

            dispute_status, dispute_payload = self._post(
                f"{node.base_url}/v1/disputes",
                "token-challenge",
                {
                    "task_id": "challenge-task-1",
                    "challenger_id": "reviewer-challenge-1",
                    "actor_id": "worker-challenge-1",
                    "actor_type": "worker",
                    "reason": "deterministic check mismatch",
                    "evidence_hash": "evidence-hash-1",
                    "severity": "high",
                    "payload": {"oracle": "ci-runner"},
                },
            )
            self.assertEqual(dispute_status, 201)
            self.assertEqual(dispute_payload["dispute"]["status"], "open")

            _, disputes = self._get(f"{node.base_url}/v1/disputes?task_id=challenge-task-1&status=open")
            self.assertEqual(len(disputes["items"]), 1)
            self.assertEqual(disputes["items"][0]["challenger_id"], "reviewer-challenge-1")

            _, preview = self._get(f"{node.base_url}/v1/onchain/settlement-preview?task_id=challenge-task-1")
            settlement = preview["settlement"]
            self.assertEqual(settlement["recommended_sequence"], ["submitWork", "challengeJob"])
            self.assertEqual(settlement["recommended_resolution"], "challengeJob")
            self.assertEqual(settlement["open_dispute_count"], 1)
            self.assertEqual(settlement["intents"][1]["function"], "challengeJob")
            self.assertTrue(settlement["intents"][1]["args"]["evidenceHash"].startswith("0x"))
            self.assertEqual(len(settlement["intents"][1]["args"]["evidenceHash"]), 66)

            _, replay = self._get(f"{node.base_url}/v1/tasks/replay-inspect?task_id=challenge-task-1")
            self.assertEqual(len(replay["disputes"]), 1)
            self.assertEqual(replay["onchain_settlement_preview"]["recommended_resolution"], "challengeJob")

            resolve_status, resolved = self._post(
                f"{node.base_url}/v1/disputes/resolve",
                "token-challenge",
                {
                    "dispute_id": disputes["items"][0]["id"],
                    "resolution_status": "dismissed",
                    "reason": "challenge dismissed after review",
                    "operator_id": "operator-challenge-1",
                },
            )
            self.assertEqual(resolve_status, 200)
            self.assertEqual(resolved["dispute"]["status"], "dismissed")
        finally:
            node.stop()

    def test_onchain_status_exposes_explicit_transport_profile(self) -> None:
        node = NodeHarness(
            node_id="network-profile-node",
            token="token-network",
            db_path=str(Path(self.tempdir.name) / "network.db"),
            capabilities=["worker"],
            network=OutboundNetworkConfig(
                http_proxy="http://127.0.0.1:10809",
                https_proxy="http://127.0.0.1:10809",
                no_proxy_hosts=["127.0.0.1", ".tailnet.internal"],
                use_environment_proxies=False,
            ),
            onchain=OnchainBindings(
                enabled=True,
                bounty_escrow_address="0x000000000000000000000000000000000000b077",
                rpc_url="https://rpc.example.invalid",
            ),
        )
        node.start()
        try:
            _, status_payload = self._get(f"{node.base_url}/v1/onchain/status")
            self.assertTrue(status_payload["transport"]["explicit_http_proxy"])
            self.assertTrue(status_payload["transport"]["explicit_https_proxy"])
            self.assertFalse(status_payload["transport"]["use_environment_proxies"])
            self.assertIn(".tailnet.internal", status_payload["transport"]["no_proxy_hosts"])
        finally:
            node.stop()

    def test_runtime_adapter_http_json_and_cli_json(self) -> None:
        http_agent = HttpAgentHarness()
        http_agent.start()
        node = NodeHarness(
            node_id="runtime-node",
            token="token-runtime",
            db_path=str(Path(self.tempdir.name) / "runtime.db"),
            capabilities=["worker"],
        )
        node.start()
        try:
            _, runtimes = self._get(f"{node.base_url}/v1/runtimes")
            runtime_names = {item["runtime"] for item in runtimes["items"]}
            self.assertIn("http-json", runtime_names)
            self.assertIn("cli-json", runtime_names)

            created_status, _ = self._post(
                f"{node.base_url}/v1/tasks",
                "token-runtime",
                {
                    "id": "runtime-http-1",
                    "kind": "generic",
                    "role": "worker",
                    "payload": {"input": {"question": "ping"}},
                },
            )
            self.assertEqual(created_status, 201)
            bind_status, bound = self._post(
                f"{node.base_url}/v1/runtimes/bind",
                "token-runtime",
                {
                    "task_id": "runtime-http-1",
                    "runtime": "http-json",
                    "options": {"endpoint": http_agent.url, "method": "POST", "timeout_seconds": 5},
                },
            )
            self.assertEqual(bind_status, 200)
            self.assertEqual(bound["runtime"]["runtime"], "http-json")

            self._post(
                f"{node.base_url}/v1/tasks",
                "token-runtime",
                {
                    "id": "runtime-cli-1",
                    "kind": "generic",
                    "role": "worker",
                    "payload": {
                        "input": {"topic": "cli"},
                        "_runtime": {
                            "runtime": "cli-json",
                            "command": [
                                sys.executable,
                                "-c",
                                "import json,sys; data=json.load(sys.stdin); print(json.dumps({'runtime':'cli-json','task_id':data['task']['id'],'worker_id':data['worker_id']}))",
                            ],
                        },
                    },
                },
            )

            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-runtime",
                worker_id="worker-runtime-1",
                capabilities=["worker"],
                lease_seconds=30,
                adapter_policy=AdapterPolicy(
                    allowed_runtime_kinds=["http-json", "cli-json"],
                    allowed_http_hosts=["127.0.0.1"],
                    allow_subprocess=True,
                    allowed_commands=[sys.executable, Path(sys.executable).name],
                ),
            )
            self.assertTrue(worker.run_once())
            self.assertTrue(worker.run_once())

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            by_id = {item["id"]: item for item in tasks["items"]}
            self.assertEqual(by_id["runtime-http-1"]["result"]["adapter"]["protocol"], "http-json")
            self.assertEqual(by_id["runtime-http-1"]["result"]["runtime_execution"]["response"]["runtime"], "http-json")
            self.assertEqual(by_id["runtime-http-1"]["result"]["runtime_execution"]["response"]["echo"], {"question": "ping"})
            self.assertEqual(http_agent.calls[0]["task"]["id"], "runtime-http-1")

            self.assertEqual(by_id["runtime-cli-1"]["result"]["adapter"]["protocol"], "cli-json")
            self.assertEqual(by_id["runtime-cli-1"]["result"]["runtime_execution"]["stdout_json"]["runtime"], "cli-json")
            self.assertEqual(by_id["runtime-cli-1"]["result"]["runtime_execution"]["stdout_json"]["task_id"], "runtime-cli-1")
        finally:
            node.stop()
            http_agent.stop()

    def test_runtime_adapter_ollama_chat(self) -> None:
        ollama = OllamaHarness()
        ollama.start()
        node = NodeHarness(
            node_id="runtime-ollama-node",
            token="token-ollama",
            db_path=str(Path(self.tempdir.name) / "runtime-ollama.db"),
            capabilities=["worker"],
        )
        node.start()
        try:
            _, runtimes = self._get(f"{node.base_url}/v1/runtimes")
            runtime_names = {item["runtime"] for item in runtimes["items"]}
            self.assertIn("ollama-chat", runtime_names)

            self._post(
                f"{node.base_url}/v1/tasks",
                "token-ollama",
                {
                    "id": "runtime-ollama-1",
                    "kind": "generic",
                    "role": "worker",
                    "payload": {"input": {"prompt": "hello ollama"}},
                },
            )
            bind_status, bound = self._post(
                f"{node.base_url}/v1/runtimes/bind",
                "token-ollama",
                {
                    "task_id": "runtime-ollama-1",
                    "runtime": "ollama-chat",
                    "options": {
                        "endpoint": ollama.url,
                        "model": "qwen2.5:7b",
                        "prompt": "hello ollama",
                        "options": {"temperature": 0},
                        "timeout_seconds": 10,
                    },
                },
            )
            self.assertEqual(bind_status, 200)
            self.assertEqual(bound["runtime"]["runtime"], "ollama-chat")

            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-ollama",
                worker_id="worker-ollama-1",
                capabilities=["worker"],
                lease_seconds=30,
                adapter_policy=AdapterPolicy(
                    allowed_runtime_kinds=["ollama-chat"],
                    allowed_http_hosts=["127.0.0.1"],
                ),
            )
            self.assertTrue(worker.run_once())

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "runtime-ollama-1"][0]
            self.assertEqual(task["result"]["adapter"]["protocol"], "ollama-chat")
            self.assertEqual(task["result"]["adapter"]["model"], "qwen2.5:7b")
            self.assertEqual(task["result"]["runtime_execution"]["assistant_message"]["content"], "ollama:hello ollama")
            self.assertEqual(ollama.calls[0]["model"], "qwen2.5:7b")
            self.assertFalse(ollama.calls[0]["stream"])
            self.assertEqual(ollama.calls[0]["messages"][0]["content"], "hello ollama")
        finally:
            node.stop()
            ollama.stop()

    def test_runtime_adapter_openai_chat_for_openclaw_gateway(self) -> None:
        gateway = OpenAICompatHarness()
        gateway.start()
        node = NodeHarness(
            node_id="runtime-openai-node",
            token="token-openai",
            db_path=str(Path(self.tempdir.name) / "runtime-openai.db"),
            capabilities=["worker"],
        )
        node.start()
        try:
            _, runtimes = self._get(f"{node.base_url}/v1/runtimes")
            runtime_names = {item["runtime"] for item in runtimes["items"]}
            self.assertIn("openai-chat", runtime_names)

            self._post(
                f"{node.base_url}/v1/tasks",
                "token-openai",
                {
                    "id": "runtime-openai-1",
                    "kind": "generic",
                    "role": "worker",
                    "payload": {"input": {"prompt": "hello openclaw"}},
                },
            )
            bind_status, bound = self._post(
                f"{node.base_url}/v1/runtimes/bind",
                "token-openai",
                {
                    "task_id": "runtime-openai-1",
                    "runtime": "openai-chat",
                    "options": {
                        "endpoint": gateway.url,
                        "model": "openclaw/gateway",
                        "prompt": "hello openclaw",
                        "auth_token": "gw-secret-token",
                        "temperature": 0,
                        "timeout_seconds": 10,
                    },
                },
            )
            self.assertEqual(bind_status, 200)
            self.assertEqual(bound["runtime"]["runtime"], "openai-chat")

            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-openai",
                worker_id="worker-openai-1",
                capabilities=["worker"],
                lease_seconds=30,
                adapter_policy=AdapterPolicy(
                    allowed_runtime_kinds=["openai-chat"],
                    allowed_http_hosts=["127.0.0.1"],
                ),
            )
            self.assertTrue(worker.run_once())

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "runtime-openai-1"][0]
            self.assertEqual(task["result"]["adapter"]["protocol"], "openai-chat")
            self.assertEqual(task["result"]["adapter"]["model"], "openclaw/gateway")
            self.assertEqual(task["result"]["runtime_execution"]["assistant_message"]["content"], "openai:hello openclaw")
            self.assertEqual(gateway.calls[0]["model"], "openclaw/gateway")
            self.assertEqual(gateway.calls[0]["messages"][0]["content"], "hello openclaw")
            self.assertEqual(gateway.headers[0]["Authorization"], "Bearer gw-secret-token")
        finally:
            node.stop()
            gateway.stop()

    def test_openclaw_bind_helper_uses_openai_chat_runtime(self) -> None:
        node = NodeHarness(
            node_id="openclaw-bind-node",
            token="token-openclaw-bind",
            db_path=str(Path(self.tempdir.name) / "openclaw-bind.db"),
            capabilities=["worker"],
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-openclaw-bind",
                {
                    "id": "openclaw-bind-task-1",
                    "kind": "generic",
                    "role": "worker",
                    "payload": {"input": "review"},
                },
            )
            status, payload = self._post(
                f"{node.base_url}/v1/integrations/openclaw/bind",
                "token-openclaw-bind",
                {
                    "task_id": "openclaw-bind-task-1",
                    "endpoint": "http://127.0.0.1:3000/v1/chat/completions",
                    "model": "openclaw/gateway",
                    "auth_token": "abc",
                    "prompt": "review this",
                    "temperature": 0,
                },
            )
            self.assertEqual(status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["provider"], "openclaw-gateway")
            self.assertEqual(payload["runtime"]["runtime"], "openai-chat")
            self.assertEqual(payload["runtime"]["endpoint"], "http://127.0.0.1:3000/v1/chat/completions")
            self.assertEqual(payload["runtime"]["model"], "openclaw/gateway")

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "openclaw-bind-task-1"][0]
            self.assertEqual(task["payload"]["_runtime"]["runtime"], "openai-chat")
            self.assertEqual(task["payload"]["_runtime"]["provider"], "openclaw-gateway")
        finally:
            node.stop()

    def test_poaw_endpoints_expose_completion_and_violation_ledger(self) -> None:
        node = NodeHarness(
            node_id="poaw-node",
            token="token-poaw",
            db_path=str(Path(self.tempdir.name) / "poaw.db"),
            capabilities=["worker", "reviewer"],
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-poaw",
                {
                    "id": "poaw-task-1",
                    "kind": "review",
                    "role": "reviewer",
                    "workflow_id": "wf-poaw-http",
                    "required_capabilities": ["reviewer"],
                    "payload": {"input": "review this"},
                },
            )

            claim_status, claim_payload = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-poaw",
                {
                    "worker_id": "worker-poaw-http",
                    "worker_capabilities": ["reviewer"],
                    "lease_seconds": 30,
                },
            )
            self.assertEqual(claim_status, 200)
            self.assertEqual(claim_payload["task"]["id"], "poaw-task-1")

            ack_status, ack_payload = self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-poaw",
                {
                    "task_id": "poaw-task-1",
                    "worker_id": "worker-poaw-http",
                    "lease_token": claim_payload["task"]["lease_token"],
                    "success": True,
                    "result": {"approved": True},
                },
            )
            self.assertEqual(ack_status, 200)
            self.assertTrue(ack_payload["ok"])

            violation = node.node.store.record_policy_violation(
                actor_id="worker-poaw-http",
                actor_type="worker",
                task_id="poaw-task-1",
                source="adapter-policy",
                reason="allowlist mismatch",
                severity="medium",
            )
            self.assertEqual(violation["severity"], "medium")

            _, events = self._get(f"{node.base_url}/v1/poaw/events?actor_id=worker-poaw-http")
            self.assertEqual(len(events["items"]), 2)
            self.assertEqual(events["items"][0]["event_type"], "policy-violation")
            self.assertEqual(events["items"][1]["event_type"], "review-approved")

            _, summary = self._get(f"{node.base_url}/v1/poaw/summary?actor_id=worker-poaw-http&actor_type=worker")
            self.assertEqual(summary["event_count"], 2)
            self.assertEqual(summary["positive_points"], 14)
            self.assertEqual(summary["negative_points"], -15)
            self.assertEqual(summary["total_points"], -1)
            self.assertEqual(summary["reputation"]["violations"], 1)

            _, replay = self._get(f"{node.base_url}/v1/tasks/replay-inspect?task_id=poaw-task-1")
            self.assertEqual(replay["poaw_summary"]["event_count"], 2)
            self.assertEqual(len(replay["poaw_events"]), 2)
        finally:
            node.stop()

    def test_adapter_policy_allows_sandboxed_local_command(self) -> None:
        workspace = Path(self.tempdir.name) / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        node = NodeHarness(
            node_id="sandbox-node",
            token="token-sandbox",
            db_path=str(Path(self.tempdir.name) / "sandbox.db"),
            capabilities=["worker", "local-command"],
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/bridges/import",
                "token-sandbox",
                {
                    "protocol": "mcp",
                    "message": {
                        "id": "mcp-sandbox-1",
                        "method": "tools/call",
                        "params": {
                            "name": "local-command",
                            "arguments": {
                                "command": [sys.executable, "-c", "print('agentcoin-sandbox-ok')"],
                                "cwd": ".",
                            },
                        },
                        "sender": "mcp-client",
                    },
                    "task_overrides": {"id": "sandbox-task-1", "role": "worker"},
                },
            )

            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-sandbox",
                worker_id="worker-sandbox-1",
                capabilities=["worker", "local-command"],
                lease_seconds=30,
                adapter_policy=AdapterPolicy(
                    allowed_mcp_tools=["local-command"],
                    allow_subprocess=True,
                    allowed_commands=[sys.executable, Path(sys.executable).name],
                    subprocess_timeout_seconds=5,
                    workspace_root=str(workspace),
                ),
            )
            self.assertTrue(worker.run_once())

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "sandbox-task-1"][0]
            execution = task["result"]["bridge_execution"]["normalized_output"]["content"][0]["data"]["execution"]
            self.assertEqual(task["result"]["adapter"]["status"], "completed")
            self.assertEqual(execution["returncode"], 0)
            self.assertIn("agentcoin-sandbox-ok", execution["stdout"])

            _, audits = self._get(f"{node.base_url}/v1/audits?task_id=sandbox-task-1")
            self.assertEqual(len(audits["items"]), 1)
            self.assertEqual(audits["items"][0]["status"], "completed")
            self.assertEqual(
                audits["items"][0]["payload"]["result"]["execution_receipt"]["subprocess"]["returncode"],
                0,
            )

            _, replay = self._get(f"{node.base_url}/v1/tasks/replay-inspect?task_id=sandbox-task-1")
            self.assertEqual(replay["task"]["id"], "sandbox-task-1")
            self.assertEqual(len(replay["audits"]), 1)
            self.assertEqual(replay["bridge_export_preview"]["protocol"], "mcp")
        finally:
            node.stop()
