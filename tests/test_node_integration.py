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
from urllib.parse import urlparse
from urllib import error, request

from agentcoin.adapters import AdapterPolicy
from agentcoin.config import NodeConfig, OperatorIdentityConfig, PeerConfig, ScopedBearerTokenConfig
from agentcoin.discovery import LocalAgentDiscovery
from agentcoin.models import utc_now
from agentcoin.net import OutboundNetworkConfig
from agentcoin.node import AgentCoinNode
from agentcoin.onchain import OnchainBindings
from agentcoin.security import sign_document_with_ssh, sign_identity_request_headers, sign_operator_request_headers, verify_document
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
                 identity_public_key: str | None = None, identity_public_keys: list[str] | None = None,
                 identity_revoked_public_keys: list[str] | None = None,
                 operator_identities: list[OperatorIdentityConfig] | None = None,
                 scoped_bearer_tokens: list[ScopedBearerTokenConfig] | None = None,
                 operator_allow_loopback_bearer_fallback: bool = False,
                 operator_auth_timestamp_skew_seconds: int = 300,
                 operator_auth_nonce_ttl_seconds: int = 900,
                 config_path: str | None = None,
                 onchain: OnchainBindings | None = None,
                 network: OutboundNetworkConfig | None = None, runtimes: list[str] | None = None,
                 challenge_bond_required_wei: int = 0,
                 payment_required_workflows: list[str] | None = None,
                 payment_relay_auto_requeue_enabled: bool = False,
                 payment_relay_auto_requeue_delay_seconds: int = 30,
                 payment_relay_auto_requeue_max_requeues: int = 1,
                 poaw_policy_version: str = "0.2",
                 poaw_score_weights: dict[str, int] | None = None,
                 bridges: list[str] | None = None,
                 sync_interval_seconds: float = 3600,
                 settlement_relay_poll_seconds: float = 2.0,
                 settlement_relay_max_in_flight: int = 1) -> None:
        self.port = _free_port()
        self.config = NodeConfig(
            node_id=node_id,
            auth_token=token,
            signing_secret=signing_secret,
            require_signed_inbox=require_signed_inbox,
            identity_principal=identity_principal,
            identity_private_key_path=identity_private_key_path,
            identity_public_key=identity_public_key,
            identity_public_keys=identity_public_keys or [],
            identity_revoked_public_keys=identity_revoked_public_keys or [],
            operator_identities=operator_identities or [],
            scoped_bearer_tokens=scoped_bearer_tokens or [],
            operator_allow_loopback_bearer_fallback=operator_allow_loopback_bearer_fallback,
            operator_auth_timestamp_skew_seconds=operator_auth_timestamp_skew_seconds,
            operator_auth_nonce_ttl_seconds=operator_auth_nonce_ttl_seconds,
            config_path=config_path,
            host="127.0.0.1",
            port=self.port,
            database_path=db_path,
            git_root=git_root,
            sync_interval_seconds=sync_interval_seconds,
            settlement_relay_poll_seconds=settlement_relay_poll_seconds,
            settlement_relay_max_in_flight=settlement_relay_max_in_flight,
            capabilities=capabilities,
            runtimes=runtimes or ["python"],
            bridges=bridges or ["mcp", "a2a"],
            peers=peers or [],
            local_dispatch_fallback=local_dispatch_fallback,
            outbox_max_attempts=outbox_max_attempts,
            task_retry_limit=2,
            task_retry_backoff_seconds=1,
            payment_required_workflows=payment_required_workflows or [],
            payment_relay_auto_requeue_enabled=payment_relay_auto_requeue_enabled,
            payment_relay_auto_requeue_delay_seconds=payment_relay_auto_requeue_delay_seconds,
            payment_relay_auto_requeue_max_requeues=payment_relay_auto_requeue_max_requeues,
            challenge_bond_required_wei=challenge_bond_required_wei,
            poaw_policy_version=poaw_policy_version,
            poaw_score_weights=poaw_score_weights or {},
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


class LangGraphHarness:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.port = _free_port()
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), self._build_handler())
        self.thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/runs/wait"

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        harness = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
                payload = json.loads(raw.decode("utf-8"))
                harness.calls.append(payload)
                response = {
                    "thread_id": payload.get("thread_id"),
                    "run_id": "run-langgraph-1",
                    "state": "completed",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": f"langgraph:{json.dumps(payload.get('input'), ensure_ascii=False)}",
                        }
                    ],
                    "output": {
                        "role": "assistant",
                        "content": f"langgraph:{json.dumps(payload.get('input'), ensure_ascii=False)}",
                    },
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
                response_format = dict(payload.get("response_format") or {})
                assistant_message: dict[str, object]
                if response_format.get("type") == "json_schema":
                    assistant_message = {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "decision": "approve",
                                "summary": payload.get("messages", [{}])[-1].get("content", ""),
                            },
                            ensure_ascii=False,
                        ),
                        "parsed": {
                            "decision": "approve",
                            "summary": payload.get("messages", [{}])[-1].get("content", ""),
                        },
                    }
                else:
                    assistant_message = {
                        "role": "assistant",
                        "content": f"openai:{payload.get('messages', [{}])[-1].get('content', '')}",
                    }
                response = {
                    "id": "chatcmpl-openclaw-1",
                    "object": "chat.completion",
                    "model": payload.get("model"),
                    "choices": [
                        {
                            "index": 0,
                            "message": assistant_message,
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


class ClaudeHttpHarness:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.headers: list[dict[str, str]] = []
        self.port = _free_port()
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), self._build_handler())
        self.thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1/messages"

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        harness = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
                payload = json.loads(raw.decode("utf-8"))
                harness.calls.append(payload)
                harness.headers.append({key: value for key, value in self.headers.items()})
                last_message = payload.get("messages", [{}])[-1]
                content = last_message.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
                response_content: list[dict[str, object]] = [{"type": "text", "text": f"claude-http:{content}"}]
                if payload.get("tools"):
                    tool = dict((payload.get("tools") or [])[0] or {})
                    response_content.append(
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": tool.get("name"),
                            "input": {"echo": content},
                        }
                    )
                response = {
                    "id": "msg_claude_1",
                    "type": "message",
                    "role": "assistant",
                    "content": response_content,
                    "model": payload.get("model"),
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
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

    def _signed_post(
        self,
        url: str,
        token: str,
        payload: dict,
        *,
        key_id: str,
        shared_secret: str | None = None,
        private_key_path: str | None = None,
        principal: str | None = None,
        public_key: str | None = None,
        timestamp: str | None = None,
        nonce: str | None = None,
    ) -> tuple[int, dict]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        parsed = urlparse(url)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            **sign_operator_request_headers(
                method="POST",
                path=parsed.path,
                query=parsed.query,
                body=body,
                key_id=key_id,
                shared_secret=shared_secret,
                private_key_path=private_key_path,
                principal=principal,
                public_key=public_key,
                timestamp=timestamp,
                nonce=nonce,
            ),
        }
        req = request.Request(url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _signed_get(
        self,
        url: str,
        token: str,
        *,
        key_id: str,
        shared_secret: str | None = None,
        private_key_path: str | None = None,
        principal: str | None = None,
        public_key: str | None = None,
        timestamp: str | None = None,
        nonce: str | None = None,
    ) -> tuple[int, dict]:
        parsed = urlparse(url)
        headers = {
            "Authorization": f"Bearer {token}",
            **sign_operator_request_headers(
                method="GET",
                path=parsed.path,
                query=parsed.query,
                body=b"",
                key_id=key_id,
                shared_secret=shared_secret,
                private_key_path=private_key_path,
                principal=principal,
                public_key=public_key,
                timestamp=timestamp,
                nonce=nonce,
            ),
        }
        req = request.Request(url, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _get(self, url: str) -> tuple[int, dict]:
        with request.urlopen(url, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _get_auth(self, url: str, token: str) -> tuple[int, dict]:
        req = request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _request_raw(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> tuple[int, dict[str, str], str]:
        req = request.Request(url, data=body, headers=headers or {}, method=method)
        try:
            with request.urlopen(req, timeout=10) as resp:
                return resp.status, dict(resp.headers.items()), resp.read().decode("utf-8")
        except error.HTTPError as exc:
            return exc.code, dict(exc.headers.items()), exc.read().decode("utf-8")

    def _identity_signed_post(
        self,
        url: str,
        payload: dict,
        *,
        private_key_path: str,
        principal: str,
        public_key: str | None = None,
        timestamp: str | None = None,
        nonce: str | None = None,
    ) -> tuple[int, dict]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        parsed = urlparse(url)
        headers = {
            "Content-Type": "application/json",
            **sign_identity_request_headers(
                method="POST",
                path=parsed.path,
                query=parsed.query,
                body=body,
                private_key_path=private_key_path,
                principal=principal,
                public_key=public_key,
                timestamp=timestamp,
                nonce=nonce,
            ),
        }
        req = request.Request(url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _identity_signed_get(
        self,
        url: str,
        *,
        private_key_path: str,
        principal: str,
        public_key: str | None = None,
        timestamp: str | None = None,
        nonce: str | None = None,
    ) -> tuple[int, dict]:
        parsed = urlparse(url)
        headers = sign_identity_request_headers(
            method="GET",
            path=parsed.path,
            query=parsed.query,
            body=b"",
            private_key_path=private_key_path,
            principal=principal,
            public_key=public_key,
            timestamp=timestamp,
            nonce=nonce,
        )
        req = request.Request(url, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _identity_signed_post_raw(
        self,
        url: str,
        payload: dict,
        *,
        private_key_path: str,
        principal: str,
        public_key: str | None = None,
        timestamp: str | None = None,
        nonce: str | None = None,
    ) -> tuple[int, dict[str, str], dict]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        parsed = urlparse(url)
        headers = {
            "Content-Type": "application/json",
            **sign_identity_request_headers(
                method="POST",
                path=parsed.path,
                query=parsed.query,
                body=body,
                private_key_path=private_key_path,
                principal=principal,
                public_key=public_key,
                timestamp=timestamp,
                nonce=nonce,
            ),
        }
        status, response_headers, raw_body = self._request_raw(
            url,
            method="POST",
            headers=headers,
            body=body,
        )
        return status, response_headers, json.loads(raw_body)

    def _session_post(
        self,
        url: str,
        payload: dict,
        *,
        session_token: str,
    ) -> tuple[int, dict]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Agentcoin-Session {session_token}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _wait_for_queue_item_status(
        self,
        node: NodeHarness,
        queue_id: str,
        *,
        status: str,
        timeout: float = 5.0,
    ) -> dict:
        deadline = time.monotonic() + timeout
        last_item = None
        while time.monotonic() < deadline:
            last_item = node.node.store.get_settlement_relay_queue_item(queue_id)
            if last_item and last_item["status"] == status:
                return last_item
            time.sleep(0.05)
        raise AssertionError(f"queue item {queue_id} did not reach status {status!r}; last_item={last_item!r}")

    def _wait_for_payment_queue_item_status(
        self,
        node: NodeHarness,
        queue_id: str,
        *,
        status: str,
        timeout: float = 5.0,
    ) -> dict:
        deadline = time.monotonic() + timeout
        last_item = None
        while time.monotonic() < deadline:
            last_item = node.node.store.get_payment_relay_queue_item(queue_id)
            if last_item and last_item["status"] == status:
                return last_item
            time.sleep(0.05)
        raise AssertionError(f"payment queue item {queue_id} did not reach status {status!r}; last_item={last_item!r}")

    def _wait_until(self, predicate, *, timeout: float = 5.0, interval: float = 0.05, message: str = "condition not met"):
        deadline = time.monotonic() + timeout
        last_value = None
        while time.monotonic() < deadline:
            last_value = predicate()
            if last_value:
                return last_value
            time.sleep(interval)
        raise AssertionError(f"{message}; last_value={last_value!r}")

    def _complete_onchain_task(self, node: NodeHarness, token: str, task_id: str, worker_id: str) -> None:
        _, claim = self._post(
            f"{node.base_url}/v1/tasks/claim",
            token,
            {"worker_id": worker_id, "worker_capabilities": ["worker"], "lease_seconds": 30},
        )
        self._post(
            f"{node.base_url}/v1/tasks/ack",
            token,
            {
                "task_id": task_id,
                "worker_id": worker_id,
                "lease_token": claim["task"]["lease_token"],
                "success": True,
                "result": {"done": True, "worker_id": worker_id},
            },
        )

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

    def _write_node_config_file(self, path: Path, *, node_id: str, auth_token: str, peers: list[dict]) -> str:
        payload = {
            "node_id": node_id,
            "auth_token": auth_token,
            "database_path": str(Path(self.tempdir.name) / f"{node_id}.db"),
            "peers": peers,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return str(path)

    def test_node_bootstraps_local_identity_and_exposes_manifest(self) -> None:
        node = NodeHarness(
            node_id="bootstrap-manifest-node",
            token="token-bootstrap-manifest",
            db_path=str(Path(self.tempdir.name) / "bootstrap-manifest.db"),
            capabilities=["worker"],
        )
        node.start()
        try:
            _, health = self._get(f"{node.base_url}/healthz")
            self.assertEqual(health["local_identity"]["principal"], "bootstrap-manifest-node")
            self.assertTrue(str(health["local_identity"]["public_key"]).startswith("ssh-ed25519 "))
            self.assertTrue(str(health["local_identity"]["did"]).startswith("did:agentcoin:ssh-ed25519:"))
            self.assertTrue(Path(str(health["local_identity"]["private_key_path"])).exists())

            _, manifest = self._get(f"{node.base_url}/v1/manifest")
            self.assertEqual(manifest["kind"], "agentcoin-manifest")
            self.assertTrue(manifest["auth"]["passwordless"])
            self.assertEqual(manifest["identity"]["principal"], "bootstrap-manifest-node")
            self.assertEqual(manifest["identity"]["did"], health["local_identity"]["did"])
            self.assertEqual(manifest["routes"]["manifest"], f"{node.base_url}/v1/manifest")
            self.assertIn("eip-191", manifest["auth"]["request_signing"]["planned"])

            _, card = self._get(f"{node.base_url}/v1/card")
            self.assertEqual(card["identity"]["did"], health["local_identity"]["did"])
            self.assertEqual(card["endpoints"]["manifest"], f"{node.base_url}/v1/manifest")
        finally:
            node.stop()

    def test_manifest_and_card_support_cors_preflight(self) -> None:
        node = NodeHarness(
            node_id="cors-node",
            token="token-cors",
            db_path=str(Path(self.tempdir.name) / "cors.db"),
            capabilities=["worker"],
        )
        node.start()
        try:
            status, headers, _ = self._request_raw(
                f"{node.base_url}/v1/manifest",
                method="OPTIONS",
                headers={"Origin": "http://127.0.0.1:5173"},
            )
            self.assertEqual(status, HTTPStatus.NO_CONTENT)
            self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
            self.assertIn("Authorization", headers.get("Access-Control-Allow-Headers", ""))

            status, headers, body = self._request_raw(
                f"{node.base_url}/v1/card",
                method="GET",
                headers={"Origin": "http://127.0.0.1:5173"},
            )
            self.assertEqual(status, HTTPStatus.OK)
            self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
            payload = json.loads(body)
            self.assertEqual(payload["node_id"], "cors-node")
        finally:
            node.stop()

    def test_identity_auth_challenge_and_signed_verify(self) -> None:
        key_path, public_key = self._generate_identity(Path(self.tempdir.name) / "id_client_auth", "frontend-local-1")
        node = NodeHarness(
            node_id="identity-auth-node",
            token="token-identity-auth",
            db_path=str(Path(self.tempdir.name) / "identity-auth.db"),
            capabilities=["worker"],
        )
        node.start()
        try:
            _, challenge_payload = self._get(f"{node.base_url}/v1/auth/challenge")
            challenge = challenge_payload["challenge"]
            self.assertEqual(challenge["namespace"], "agentcoin-client-request")
            self.assertEqual(challenge["local_identity"]["principal"], "identity-auth-node")

            status, verified = self._identity_signed_post(
                f"{node.base_url}/v1/auth/verify",
                {
                    "challenge_id": challenge["challenge_id"],
                    "principal": "frontend-local-1",
                    "public_key": public_key,
                },
                private_key_path=key_path,
                principal="frontend-local-1",
                public_key=public_key,
            )
            self.assertEqual(status, 200)
            self.assertTrue(verified["ok"])
            self.assertEqual(verified["identity"]["principal"], "frontend-local-1")
            self.assertTrue(str(verified["identity"]["did"]).startswith("did:agentcoin:ssh-ed25519:"))
            self.assertTrue(verified["challenge"]["consumed"])
            self.assertEqual(verified["receipt"]["kind"], "agentcoin-identity-auth-receipt")

            replay_status, replay_payload = self._identity_signed_post(
                f"{node.base_url}/v1/auth/verify",
                {
                    "challenge_id": challenge["challenge_id"],
                    "principal": "frontend-local-1",
                    "public_key": public_key,
                },
                private_key_path=key_path,
                principal="frontend-local-1",
                public_key=public_key,
            )
            self.assertEqual(replay_status, 400)
            self.assertIn("challenge", replay_payload["error"])
        finally:
            node.stop()

    def test_identity_auth_verify_issues_reusable_loopback_session(self) -> None:
        key_path, public_key = self._generate_identity(Path(self.tempdir.name) / "id_client_session", "frontend-local-session")
        node = NodeHarness(
            node_id="identity-session-node",
            token="token-identity-session",
            db_path=str(Path(self.tempdir.name) / "identity-session.db"),
            capabilities=["worker"],
            runtimes=["openai-chat"],
        )
        node.start()
        try:
            _, challenge_payload = self._get(f"{node.base_url}/v1/auth/challenge")
            challenge = challenge_payload["challenge"]
            verify_status, verified = self._identity_signed_post(
                f"{node.base_url}/v1/auth/verify",
                {
                    "challenge_id": challenge["challenge_id"],
                    "principal": "frontend-local-session",
                    "public_key": public_key,
                },
                private_key_path=key_path,
                principal="frontend-local-session",
                public_key=public_key,
            )
            self.assertEqual(verify_status, HTTPStatus.OK)
            session_token = str(verified["session"]["session_token"])

            create_status, created = self._session_post(
                f"{node.base_url}/v1/tasks",
                {
                    "id": "session-local-task-1",
                    "kind": "generic",
                    "payload": {"input": "via-session"},
                },
                session_token=session_token,
            )
            self.assertEqual(create_status, HTTPStatus.CREATED)
            self.assertEqual(created["task"]["id"], "session-local-task-1")

            bind_status, bound = self._session_post(
                f"{node.base_url}/v1/runtimes/bind",
                {
                    "task_id": "session-local-task-1",
                    "runtime": "openai-chat",
                    "options": {
                        "endpoint": "http://127.0.0.1:12345/v1/chat/completions",
                        "model": "openclaw/gateway",
                    },
                },
                session_token=session_token,
            )
            self.assertEqual(bind_status, HTTPStatus.OK)
            self.assertEqual(bound["runtime"]["runtime"], "openai-chat")

            execute_status, executed = self._session_post(
                f"{node.base_url}/v1/workflow/execute",
                {
                    "workflow_name": "free-review",
                    "input": {"prompt": "via-session"},
                },
                session_token=session_token,
            )
            self.assertEqual(execute_status, HTTPStatus.ACCEPTED)
            self.assertFalse(executed["payment_required"])
            self.assertFalse(executed["payment_verified"])
            self.assertEqual(executed["task"]["payload"]["workflow_name"], "free-review")

            introspect_status, introspected = self._session_post(
                f"{node.base_url}/v1/payments/receipts/introspect",
                {
                    "payment_receipt": {
                        "kind": "agentcoin-payment-receipt",
                    }
                },
                session_token=session_token,
            )
            self.assertEqual(introspect_status, HTTPStatus.BAD_REQUEST)
            self.assertIn("receipt", introspected["error"])

            proof_status, proof_payload = self._session_post(
                f"{node.base_url}/v1/payments/receipts/onchain-proof",
                {
                    "payment_receipt": {
                        "kind": "agentcoin-payment-receipt",
                    }
                },
                session_token=session_token,
            )
            self.assertEqual(proof_status, HTTPStatus.BAD_REQUEST)
            self.assertIn("onchain", proof_payload["error"])

            plan_status, plan_payload = self._session_post(
                f"{node.base_url}/v1/payments/receipts/onchain-rpc-plan",
                {
                    "payment_receipt": {
                        "kind": "agentcoin-payment-receipt",
                    }
                },
                session_token=session_token,
            )
            self.assertEqual(plan_status, HTTPStatus.BAD_REQUEST)
            self.assertIn("onchain", plan_payload["error"])

            bundle_status, bundle_payload = self._session_post(
                f"{node.base_url}/v1/payments/receipts/onchain-raw-bundle",
                {
                    "payment_receipt": {
                        "kind": "agentcoin-payment-receipt",
                    }
                },
                session_token=session_token,
            )
            self.assertEqual(bundle_status, HTTPStatus.BAD_REQUEST)
            self.assertIn("onchain", bundle_payload["error"])
        finally:
            node.stop()

    def test_identity_auth_session_cannot_access_non_allowed_endpoint(self) -> None:
        key_path, public_key = self._generate_identity(Path(self.tempdir.name) / "id_client_session_denied", "frontend-local-session-denied")
        node = NodeHarness(
            node_id="identity-session-denied-node",
            token="token-identity-session-denied",
            db_path=str(Path(self.tempdir.name) / "identity-session-denied.db"),
            capabilities=["worker"],
        )
        node.start()
        try:
            _, challenge_payload = self._get(f"{node.base_url}/v1/auth/challenge")
            challenge = challenge_payload["challenge"]
            verify_status, verified = self._identity_signed_post(
                f"{node.base_url}/v1/auth/verify",
                {
                    "challenge_id": challenge["challenge_id"],
                    "principal": "frontend-local-session-denied",
                    "public_key": public_key,
                },
                private_key_path=key_path,
                principal="frontend-local-session-denied",
                public_key=public_key,
            )
            self.assertEqual(verify_status, HTTPStatus.OK)
            session_token = str(verified["session"]["session_token"])

            denied_status, denied_payload = self._session_post(
                f"{node.base_url}/v1/outbox/flush",
                {},
                session_token=session_token,
            )
            self.assertEqual(denied_status, HTTPStatus.FORBIDDEN)
            self.assertIn("not allowed", denied_payload["error"])
        finally:
            node.stop()

    def test_local_agent_discovery_reports_copilot_candidates(self) -> None:
        key_path, public_key = self._generate_identity(
            Path(self.tempdir.name) / "id_client_local_discovery",
            "frontend-local-discovery",
        )
        local_appdata = Path(self.tempdir.name) / "AppData" / "Local"
        home = Path(self.tempdir.name) / "home"
        executable = local_appdata / "GitHub CLI" / "copilot" / "copilot.exe"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")
        claude_executable = local_appdata / "Programs" / "Claude Code" / "claude.exe"
        claude_executable.parent.mkdir(parents=True, exist_ok=True)
        claude_executable.write_text("", encoding="utf-8")

        package_json = local_appdata / "copilot" / "pkg" / "win32-x64" / "1.0.17" / "package.json"
        package_json.parent.mkdir(parents=True, exist_ok=True)
        package_json.write_text(
            json.dumps({"name": "@github/copilot", "version": "1.0.17"}),
            encoding="utf-8",
        )

        extension_json = home / ".vscode" / "extensions" / "github.copilot-chat-0.42.3" / "package.json"
        extension_json.parent.mkdir(parents=True, exist_ok=True)
        extension_json.write_text(
            json.dumps({"name": "copilot-chat", "publisher": "GitHub", "version": "0.42.3"}),
            encoding="utf-8",
        )
        codex_json = home / ".vscode" / "extensions" / "openai.chatgpt-26.5401.11717-win32-x64" / "package.json"
        codex_json.parent.mkdir(parents=True, exist_ok=True)
        codex_json.write_text(
            json.dumps(
                {
                    "name": "chatgpt",
                    "publisher": "openai",
                    "version": "26.5401.11717",
                    "displayName": "Codex – OpenAI’s coding agent",
                }
            ),
            encoding="utf-8",
        )
        cline_json = home / ".vscode" / "extensions" / "saoudrizwan.claude-dev-3.77.0" / "package.json"
        cline_json.parent.mkdir(parents=True, exist_ok=True)
        cline_json.write_text(
            json.dumps(
                {
                    "name": "claude-dev",
                    "publisher": "saoudrizwan",
                    "version": "3.77.0",
                    "displayName": "Cline",
                }
            ),
            encoding="utf-8",
        )

        def fake_runner(command: list[str]) -> tuple[int, str, str]:
            if command[0] == str(claude_executable) and command[-1] == "--help":
                return 0, "Claude Code CLI\n  --mcp  Start Model Context Protocol transport\n", ""
            if command[0] == str(claude_executable) and command[-1] == "--version":
                return 0, "0.9.3", ""
            if command[-1] == "--help":
                return 0, "GitHub Copilot CLI\n  --acp  Start as Agent Client Protocol server\n", ""
            if command[-1] == "--version":
                return 0, "1.0.17", ""
            return 1, "", "unsupported"

        node = NodeHarness(
            node_id="local-discovery-node",
            token="token-local-discovery",
            db_path=str(Path(self.tempdir.name) / "local-discovery.db"),
            capabilities=["worker"],
        )
        node.node.discovery = LocalAgentDiscovery(
            env={"LOCALAPPDATA": str(local_appdata)},
            home=home,
            system_name="Windows",
            which=lambda name: str(executable) if name == "copilot" else (str(claude_executable) if name == "claude" else None),
            command_runner=fake_runner,
        )
        node.start()
        try:
            status, payload = self._identity_signed_get(
                f"{node.base_url}/v1/discovery/local-agents",
                private_key_path=key_path,
                principal="frontend-local-discovery",
                public_key=public_key,
            )
            self.assertEqual(status, HTTPStatus.OK)
            ids = {item["id"] for item in payload["items"]}
            self.assertIn("github-copilot-cli", ids)
            self.assertIn("claude-code-cli", ids)
            self.assertIn("github-copilot-chat-vscode", ids)
            self.assertIn("openai-codex-vscode", ids)
            self.assertIn("cline-vscode", ids)
            cli_item = [item for item in payload["items"] if item["id"] == "github-copilot-cli"][0]
            self.assertIn("acp", cli_item["protocols"])
            self.assertEqual(cli_item["agentcoin_compatibility"]["preferred_integration"], "acp-bridge")
            claude_item = [item for item in payload["items"] if item["id"] == "claude-code-cli"][0]
            self.assertEqual(claude_item["publisher"], "Anthropic")
            self.assertIn("mcp", claude_item["protocols"])
            self.assertEqual(claude_item["agentcoin_compatibility"]["preferred_integration"], "mcp-host-adapter")
            codex_item = [item for item in payload["items"] if item["id"] == "openai-codex-vscode"][0]
            self.assertEqual(codex_item["publisher"], "openai")
            cline_item = [item for item in payload["items"] if item["id"] == "cline-vscode"][0]
            self.assertEqual(cline_item["display_name"], "Cline")
        finally:
            node.stop()

    def test_local_agent_registration_start_and_stop_for_acp_cli(self) -> None:
        key_path, public_key = self._generate_identity(
            Path(self.tempdir.name) / "id_client_local_agent_manage",
            "frontend-local-agent-manage",
        )
        sleeper = Path(self.tempdir.name) / "fake_acp_agent.py"
        sleeper.write_text(
            "import time\n"
            "try:\n"
            "    time.sleep(30)\n"
            "except KeyboardInterrupt:\n"
            "    pass\n",
            encoding="utf-8",
        )

        class FakeDiscovery:
            system_name = "Windows"
            is_wsl = False

            @staticmethod
            def discover() -> list[dict[str, object]]:
                return [
                    {
                        "id": "github-copilot-cli",
                        "family": "github-copilot",
                        "title": "GitHub Copilot CLI",
                        "type": "local-cli-agent",
                        "publisher": "GitHub",
                        "protocols": ["acp"],
                        "agentcoin_compatibility": {
                            "attachable_today": False,
                            "preferred_integration": "acp-bridge",
                            "integration_candidates": ["acp-bridge"],
                            "launch_hint": [sys.executable, str(sleeper)],
                        },
                    }
                ]

        node = NodeHarness(
            node_id="local-agent-manage-node",
            token="token-local-agent-manage",
            db_path=str(Path(self.tempdir.name) / "local-agent-manage.db"),
            capabilities=["worker"],
        )
        node.node.discovery = FakeDiscovery()
        node.start()
        try:
            register_status, register_payload = self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/register",
                {"discovered_id": "github-copilot-cli"},
                private_key_path=key_path,
                principal="frontend-local-agent-manage",
                public_key=public_key,
            )
            self.assertEqual(register_status, HTTPStatus.CREATED)
            registration = register_payload["item"]
            self.assertEqual(registration["status"], "registered")
            self.assertEqual(registration["preferred_integration"], "acp-bridge")

            managed_status, managed_payload = self._identity_signed_get(
                f"{node.base_url}/v1/discovery/local-agents/managed",
                private_key_path=key_path,
                principal="frontend-local-agent-manage",
                public_key=public_key,
            )
            self.assertEqual(managed_status, HTTPStatus.OK)
            self.assertEqual(len(managed_payload["items"]), 1)
            self.assertEqual(managed_payload["items"][0]["status"], "registered")

            start_status, start_payload = self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/start",
                {"registration_id": registration["registration_id"]},
                private_key_path=key_path,
                principal="frontend-local-agent-manage",
                public_key=public_key,
            )
            self.assertEqual(start_status, HTTPStatus.OK)
            self.assertEqual(start_payload["item"]["status"], "running")
            self.assertTrue(int(start_payload["item"]["pid"] or 0) > 0)

            running_status, running_payload = self._identity_signed_get(
                f"{node.base_url}/v1/discovery/local-agents/managed",
                private_key_path=key_path,
                principal="frontend-local-agent-manage",
                public_key=public_key,
            )
            self.assertEqual(running_status, HTTPStatus.OK)
            self.assertEqual(running_payload["items"][0]["status"], "running")

            stop_status, stop_payload = self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/stop",
                {"registration_id": registration["registration_id"]},
                private_key_path=key_path,
                principal="frontend-local-agent-manage",
                public_key=public_key,
            )
            self.assertEqual(stop_status, HTTPStatus.OK)
            self.assertEqual(stop_payload["item"]["status"], "stopped")
            self.assertIsNone(stop_payload["item"]["pid"])
        finally:
            node.stop()

    def test_local_agent_acp_session_open_list_and_close(self) -> None:
        key_path, public_key = self._generate_identity(
            Path(self.tempdir.name) / "id_client_local_agent_acp",
            "frontend-local-agent-acp",
        )
        sleeper = Path(self.tempdir.name) / "fake_acp_agent_session.py"
        sleeper.write_text(
            "import time\n"
            "try:\n"
            "    time.sleep(30)\n"
            "except KeyboardInterrupt:\n"
            "    pass\n",
            encoding="utf-8",
        )

        class FakeDiscovery:
            system_name = "Windows"
            is_wsl = False

            @staticmethod
            def discover() -> list[dict[str, object]]:
                return [
                    {
                        "id": "github-copilot-cli",
                        "family": "github-copilot",
                        "title": "GitHub Copilot CLI",
                        "type": "local-cli-agent",
                        "publisher": "GitHub",
                        "protocols": ["acp"],
                        "agentcoin_compatibility": {
                            "attachable_today": False,
                            "preferred_integration": "acp-bridge",
                            "integration_candidates": ["acp-bridge"],
                            "launch_hint": [sys.executable, str(sleeper)],
                        },
                    }
                ]

        node = NodeHarness(
            node_id="local-agent-acp-node",
            token="token-local-agent-acp",
            db_path=str(Path(self.tempdir.name) / "local-agent-acp.db"),
            capabilities=["worker"],
        )
        node.node.discovery = FakeDiscovery()
        node.start()
        try:
            register_status, register_payload = self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/register",
                {"discovered_id": "github-copilot-cli"},
                private_key_path=key_path,
                principal="frontend-local-agent-acp",
                public_key=public_key,
            )
            self.assertEqual(register_status, HTTPStatus.CREATED)
            registration = register_payload["item"]

            open_status, open_payload = self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/acp-session/open",
                {"registration_id": registration["registration_id"]},
                private_key_path=key_path,
                principal="frontend-local-agent-acp",
                public_key=public_key,
            )
            self.assertEqual(open_status, HTTPStatus.OK)
            session = open_payload["session"]
            self.assertEqual(session["protocol"], "acp")
            self.assertEqual(session["transport"], "stdio")
            self.assertEqual(session["status"], "open")
            self.assertEqual(session["handshake_state"], "transport-ready")
            self.assertEqual(session["protocol_state"], "initialize-pending")
            self.assertTrue(int(session["pid"] or 0) > 0)
            self.assertEqual(session["summary"]["turn_count"], 0)
            self.assertIsNone(session["summary"]["active_turn_id"])
            self.assertFalse(open_payload["protocol_boundary"]["protocol_messages_implemented"])

            managed_status, managed_payload = self._identity_signed_get(
                f"{node.base_url}/v1/discovery/local-agents/managed",
                private_key_path=key_path,
                principal="frontend-local-agent-acp",
                public_key=public_key,
            )
            self.assertEqual(managed_status, HTTPStatus.OK)
            self.assertEqual(managed_payload["items"][0]["status"], "running")

            sessions_status, sessions_payload = self._identity_signed_get(
                f"{node.base_url}/v1/discovery/local-agents/acp-sessions",
                private_key_path=key_path,
                principal="frontend-local-agent-acp",
                public_key=public_key,
            )
            self.assertEqual(sessions_status, HTTPStatus.OK)
            self.assertEqual(len(sessions_payload["items"]), 1)
            self.assertEqual(sessions_payload["items"][0]["session_id"], session["session_id"])
            self.assertEqual(sessions_payload["items"][0]["summary"]["turn_count"], 0)
            self.assertTrue(sessions_payload["protocol_boundary"]["transport_ready"])
            self.assertFalse(sessions_payload["protocol_boundary"]["protocol_messages_implemented"])

            close_status, close_payload = self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/acp-session/close",
                {"session_id": session["session_id"]},
                private_key_path=key_path,
                principal="frontend-local-agent-acp",
                public_key=public_key,
            )
            self.assertEqual(close_status, HTTPStatus.OK)
            self.assertEqual(close_payload["session"]["status"], "closed")
            self.assertEqual(close_payload["session"]["handshake_state"], "closed")

            sessions_after_status, sessions_after_payload = self._identity_signed_get(
                f"{node.base_url}/v1/discovery/local-agents/acp-sessions",
                private_key_path=key_path,
                principal="frontend-local-agent-acp",
                public_key=public_key,
            )
            self.assertEqual(sessions_after_status, HTTPStatus.OK)
            self.assertEqual(sessions_after_payload["items"], [])
        finally:
            node.stop()

    def test_local_agent_acp_initialize_dispatch_writes_candidate_frame(self) -> None:
        key_path, public_key = self._generate_identity(
            Path(self.tempdir.name) / "id_client_local_agent_acp_init",
            "frontend-local-agent-acp-init",
        )
        capture_path = Path(self.tempdir.name) / "acp_initialize_capture.json"
        sleeper = Path(self.tempdir.name) / "fake_acp_agent_initialize.py"
        sleeper.write_text(
            "import json, sys, time\n"
            f"capture_path = r'''{capture_path}'''\n"
            "line = sys.stdin.readline()\n"
            "with open(capture_path, 'w', encoding='utf-8') as handle:\n"
            "    handle.write(line)\n"
            "    handle.flush()\n"
            "request = json.loads(line)\n"
            "response = {\n"
            "    'id': request.get('id'),\n"
            "    'result': {\n"
            "        'protocolVersion': request.get('params', {}).get('protocolVersion'),\n"
            "        'serverInfo': {'name': 'fake-acp-server', 'version': '0.1-test'},\n"
            "        'serverCapabilities': {'tasks': True},\n"
            "    },\n"
            "}\n"
            "sys.stdout.write(json.dumps(response) + '\\n')\n"
            "sys.stdout.flush()\n"
            "try:\n"
            "    time.sleep(30)\n"
            "except KeyboardInterrupt:\n"
            "    pass\n",
            encoding="utf-8",
        )

        class FakeDiscovery:
            system_name = "Windows"
            is_wsl = False

            @staticmethod
            def discover() -> list[dict[str, object]]:
                return [
                    {
                        "id": "github-copilot-cli",
                        "family": "github-copilot",
                        "title": "GitHub Copilot CLI",
                        "type": "local-cli-agent",
                        "publisher": "GitHub",
                        "protocols": ["acp"],
                        "agentcoin_compatibility": {
                            "attachable_today": False,
                            "preferred_integration": "acp-bridge",
                            "integration_candidates": ["acp-bridge"],
                            "launch_hint": [sys.executable, str(sleeper)],
                        },
                    }
                ]

        node = NodeHarness(
            node_id="local-agent-acp-init-node",
            token="token-local-agent-acp-init",
            db_path=str(Path(self.tempdir.name) / "local-agent-acp-init.db"),
            capabilities=["worker"],
        )
        node.node.discovery = FakeDiscovery()
        node.start()
        try:
            _, register_payload = self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/register",
                {"discovered_id": "github-copilot-cli"},
                private_key_path=key_path,
                principal="frontend-local-agent-acp-init",
                public_key=public_key,
            )
            registration = register_payload["item"]
            _, open_payload = self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/acp-session/open",
                {"registration_id": registration["registration_id"]},
                private_key_path=key_path,
                principal="frontend-local-agent-acp-init",
                public_key=public_key,
            )
            session_id = open_payload["session"]["session_id"]

            initialize_status, initialize_payload = self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/acp-session/initialize",
                {
                    "session_id": session_id,
                    "protocol_version": "0.1-preview",
                    "client_capabilities": {"tasks": True},
                    "client_info": {"name": "agentcoin-test", "version": "0.1-test"},
                    "dispatch": True,
                },
                private_key_path=key_path,
                principal="frontend-local-agent-acp-init",
                public_key=public_key,
            )
            self.assertEqual(initialize_status, HTTPStatus.OK)
            self.assertTrue(initialize_payload["dispatched"])
            self.assertEqual(initialize_payload["session"]["handshake_state"], "initialize-sent")
            self.assertEqual(initialize_payload["session"]["protocol_state"], "server-capabilities-pending")
            self.assertEqual(initialize_payload["initialize_intent"]["request"]["method"], "initialize")
            self.assertEqual(
                initialize_payload["initialize_intent"]["request"]["params"]["protocolVersion"],
                "0.1-preview",
            )

            deadline = time.time() + 5
            while time.time() < deadline and not capture_path.exists():
                time.sleep(0.1)
            self.assertTrue(capture_path.exists())
            captured = json.loads(capture_path.read_text(encoding="utf-8"))
            self.assertEqual(captured["method"], "initialize")
            self.assertEqual(captured["params"]["protocolVersion"], "0.1-preview")
            self.assertEqual(captured["params"]["clientCapabilities"], {"tasks": True})
            self.assertEqual(captured["params"]["clientInfo"]["name"], "agentcoin-test")

            poll_deadline = time.time() + 5
            poll_status = HTTPStatus.OK
            poll_payload: dict[str, object] = {}
            while time.time() < poll_deadline:
                poll_status, polled = self._identity_signed_post(
                    f"{node.base_url}/v1/discovery/local-agents/acp-session/poll",
                    {"session_id": session_id},
                    private_key_path=key_path,
                    principal="frontend-local-agent-acp-init",
                    public_key=public_key,
                )
                poll_payload = polled
                if polled.get("latest_server_frame"):
                    break
                time.sleep(0.1)
            self.assertEqual(poll_status, HTTPStatus.OK)
            self.assertEqual(poll_payload["session"]["handshake_state"], "initialize-response-captured")
            self.assertEqual(poll_payload["session"]["protocol_state"], "server-response-captured")
            self.assertEqual(len(poll_payload["turns"]), 1)
            self.assertEqual(poll_payload["turns"][0]["phase"], "initialize")
            self.assertTrue(poll_payload["turns"][0]["response_captured"])
            self.assertEqual(poll_payload["session"]["summary"]["turn_count"], 1)
            self.assertEqual(poll_payload["session"]["summary"]["active_phase"], "initialize")
            self.assertTrue(poll_payload["session"]["summary"]["active_response_captured"])
            self.assertEqual(poll_payload["session"]["summary"]["pending_request_ids"], [])
            latest_server_frame = poll_payload["latest_server_frame"]
            initialize_response_frame = poll_payload["initialize_response_frame"]
            self.assertIsNotNone(latest_server_frame)
            self.assertIsNotNone(initialize_response_frame)
            self.assertEqual(
                initialize_response_frame["parsed"]["id"],
                initialize_payload["initialize_intent"]["request"]["id"],
            )
            self.assertEqual(latest_server_frame["parsed"]["result"]["serverInfo"]["name"], "fake-acp-server")
            self.assertEqual(latest_server_frame["parsed"]["result"]["serverCapabilities"], {"tasks": True})
            self.assertEqual(
                poll_payload["protocol_boundary"]["server_response_parsing_implemented"],
                "best-effort-json-frame-capture-only",
            )
        finally:
            node.stop()

    def test_local_agent_acp_task_request_dispatch_writes_prompt_candidate_frame(self) -> None:
        key_path, public_key = self._generate_identity(
            Path(self.tempdir.name) / "id_client_local_agent_acp_task",
            "frontend-local-agent-acp-task",
        )
        initialize_capture_path = Path(self.tempdir.name) / "acp_initialize_capture_task.json"
        task_capture_path = Path(self.tempdir.name) / "acp_task_capture.json"
        sleeper = Path(self.tempdir.name) / "fake_acp_agent_task.py"
        sleeper.write_text(
            "import json, sys, time\n"
            f"initialize_capture_path = r'''{initialize_capture_path}'''\n"
            f"task_capture_path = r'''{task_capture_path}'''\n"
            "line1 = sys.stdin.readline()\n"
            "with open(initialize_capture_path, 'w', encoding='utf-8') as handle:\n"
            "    handle.write(line1)\n"
            "request1 = json.loads(line1)\n"
            "response1 = {\n"
            "    'id': request1.get('id'),\n"
            "    'result': {\n"
            "        'protocolVersion': request1.get('params', {}).get('protocolVersion'),\n"
            "        'serverInfo': {'name': 'fake-acp-server', 'version': '0.1-test'},\n"
            "        'serverCapabilities': {'tasks': True},\n"
            "    },\n"
            "}\n"
            "sys.stdout.write(json.dumps(response1) + '\\n')\n"
            "sys.stdout.flush()\n"
            "line2 = sys.stdin.readline()\n"
            "with open(task_capture_path, 'w', encoding='utf-8') as handle:\n"
            "    handle.write(line2)\n"
            "request2 = json.loads(line2)\n"
            "response2 = {\n"
            "    'id': request2.get('id'),\n"
            "    'result': {\n"
            "        'stopReason': 'end_turn',\n"
            "        'content': [{'type': 'text', 'text': 'task-ok'}],\n"
            "    },\n"
            "}\n"
            "sys.stdout.write(json.dumps(response2) + '\\n')\n"
            "sys.stdout.flush()\n"
            "try:\n"
            "    time.sleep(30)\n"
            "except KeyboardInterrupt:\n"
            "    pass\n",
            encoding="utf-8",
        )

        class FakeDiscovery:
            system_name = "Windows"
            is_wsl = False

            @staticmethod
            def discover() -> list[dict[str, object]]:
                return [
                    {
                        "id": "github-copilot-cli",
                        "family": "github-copilot",
                        "title": "GitHub Copilot CLI",
                        "type": "local-cli-agent",
                        "publisher": "GitHub",
                        "protocols": ["acp"],
                        "agentcoin_compatibility": {
                            "attachable_today": False,
                            "preferred_integration": "acp-bridge",
                            "integration_candidates": ["acp-bridge"],
                            "launch_hint": [sys.executable, str(sleeper)],
                        },
                    }
                ]

        node = NodeHarness(
            node_id="local-agent-acp-task-node",
            token="token-local-agent-acp-task",
            db_path=str(Path(self.tempdir.name) / "local-agent-acp-task.db"),
            capabilities=["worker"],
        )
        node.node.discovery = FakeDiscovery()
        node.start()
        try:
            self._identity_signed_post(
                f"{node.base_url}/v1/tasks",
                {
                    "id": "acp-task-1",
                    "kind": "review",
                    "role": "reviewer",
                    "payload": {"input": {"prompt": "Review this ACP task request"}},
                },
                private_key_path=key_path,
                principal="frontend-local-agent-acp-task",
                public_key=public_key,
            )
            _, register_payload = self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/register",
                {"discovered_id": "github-copilot-cli"},
                private_key_path=key_path,
                principal="frontend-local-agent-acp-task",
                public_key=public_key,
            )
            registration = register_payload["item"]
            _, open_payload = self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/acp-session/open",
                {"registration_id": registration["registration_id"]},
                private_key_path=key_path,
                principal="frontend-local-agent-acp-task",
                public_key=public_key,
            )
            session_id = open_payload["session"]["session_id"]
            self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/acp-session/initialize",
                {
                    "session_id": session_id,
                    "protocol_version": "0.1-preview",
                    "client_capabilities": {"tasks": True},
                    "client_info": {"name": "agentcoin-test", "version": "0.1-test"},
                    "dispatch": True,
                },
                private_key_path=key_path,
                principal="frontend-local-agent-acp-task",
                public_key=public_key,
            )

            task_request_status, task_request_payload = self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/acp-session/task-request",
                {
                    "session_id": session_id,
                    "task_id": "acp-task-1",
                    "server_session_id": "server-session-123",
                    "dispatch": True,
                },
                private_key_path=key_path,
                principal="frontend-local-agent-acp-task",
                public_key=public_key,
            )
            self.assertEqual(task_request_status, HTTPStatus.OK)
            self.assertTrue(task_request_payload["dispatched"])
            self.assertEqual(task_request_payload["task_request_intent"]["request"]["method"], "prompt")
            self.assertEqual(
                task_request_payload["task_request_intent"]["request"]["params"]["sessionId"],
                "server-session-123",
            )
            self.assertEqual(
                task_request_payload["task_request_intent"]["request"]["params"]["prompt"][0]["text"],
                "Review this ACP task request",
            )
            self.assertEqual(task_request_payload["session"]["protocol_state"], "task-response-pending")
            self.assertEqual(
                task_request_payload["protocol_boundary"]["task_semantics_implemented"],
                "prompt-request-skeleton-only",
            )

            deadline = time.time() + 5
            while time.time() < deadline and not task_capture_path.exists():
                time.sleep(0.1)
            self.assertTrue(task_capture_path.exists())
            captured = json.loads(task_capture_path.read_text(encoding="utf-8"))
            self.assertEqual(captured["method"], "prompt")
            self.assertEqual(captured["params"]["sessionId"], "server-session-123")
            self.assertEqual(captured["params"]["prompt"][0]["text"], "Review this ACP task request")

            poll_deadline = time.time() + 5
            poll_payload: dict[str, object] = {}
            while time.time() < poll_deadline:
                _, polled = self._identity_signed_post(
                    f"{node.base_url}/v1/discovery/local-agents/acp-session/poll",
                    {"session_id": session_id},
                    private_key_path=key_path,
                    principal="frontend-local-agent-acp-task",
                    public_key=public_key,
                )
                poll_payload = polled
                latest = polled.get("latest_server_frame") or {}
                parsed = latest.get("parsed") if isinstance(latest, dict) else None
                if isinstance(parsed, dict) and parsed.get("result", {}).get("content"):
                    break
                time.sleep(0.1)
            latest_server_frame = poll_payload["latest_server_frame"]
            task_response_frame = poll_payload["task_response_frame"]
            self.assertEqual(poll_payload["session"]["protocol_state"], "task-response-captured")
            self.assertEqual(len(poll_payload["turns"]), 2)
            self.assertEqual(poll_payload["turns"][0]["phase"], "initialize")
            self.assertEqual(poll_payload["turns"][1]["phase"], "task-request")
            self.assertTrue(poll_payload["turns"][1]["response_captured"])
            self.assertEqual(poll_payload["session"]["summary"]["turn_count"], 2)
            self.assertEqual(poll_payload["session"]["summary"]["active_phase"], "task-request")
            self.assertEqual(poll_payload["session"]["summary"]["active_task_id"], "acp-task-1")
            self.assertTrue(poll_payload["session"]["summary"]["active_response_captured"])
            self.assertEqual(poll_payload["session"]["summary"]["pending_request_ids"], [])
            self.assertIsNotNone(task_response_frame)
            self.assertEqual(
                task_response_frame["parsed"]["id"],
                task_request_payload["task_request_intent"]["request"]["id"],
            )
            self.assertEqual(latest_server_frame["parsed"]["result"]["content"][0]["text"], "task-ok")

            apply_status, applied = self._identity_signed_post(
                f"{node.base_url}/v1/discovery/local-agents/acp-session/apply-task-result",
                {"session_id": session_id, "task_id": "acp-task-1"},
                private_key_path=key_path,
                principal="frontend-local-agent-acp-task",
                public_key=public_key,
            )
            self.assertEqual(apply_status, HTTPStatus.OK)
            self.assertEqual(
                applied["protocol_boundary"]["result_mapping_implemented"],
                "latest-response-frame-to-task-result-skeleton",
            )
            self.assertEqual(applied["task"]["status"], "completed")
            self.assertEqual(applied["result"]["output_text"], "task-ok")
            self.assertEqual(applied["result"]["adapter"]["protocol"], "acp")
            self.assertEqual(
                applied["result"]["runtime_execution"]["assistant_message"]["content"],
                "task-ok",
            )
            self.assertEqual(
                applied["result"]["execution_receipt"]["protocol"],
                "acp",
            )

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "acp-task-1"][0]
            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["result"]["runtime_execution"]["assistant_message"]["content"], "task-ok")

            _, audits = self._get(f"{node.base_url}/v1/audits?task_id=acp-task-1")
            self.assertEqual(len(audits["items"]), 1)
            self.assertEqual(audits["items"][0]["event_type"], "external-result")
        finally:
            node.stop()

    def test_workflow_execute_returns_402_without_payment_receipt(self) -> None:
        key_path, public_key = self._generate_identity(Path(self.tempdir.name) / "id_client_payment_402", "frontend-local-payment-402")
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            local_controller_address="0x2222222222222222222222222222222222222222",
        )
        node = NodeHarness(
            node_id="payment-402-node",
            token="token-payment-402",
            db_path=str(Path(self.tempdir.name) / "payment-402.db"),
            capabilities=["worker"],
            signing_secret="payment-402-secret",
            payment_required_workflows=["premium-review"],
            onchain=onchain,
        )
        node.start()
        try:
            status, headers, payload = self._identity_signed_post_raw(
                f"{node.base_url}/v1/workflow/execute",
                {
                    "workflow_name": "premium-review",
                    "input": {"prompt": "review this secret workflow"},
                },
                private_key_path=key_path,
                principal="frontend-local-payment-402",
                public_key=public_key,
            )
            self.assertEqual(status, HTTPStatus.PAYMENT_REQUIRED)
            self.assertTrue(payload["payment"]["required"])
            self.assertEqual(payload["payment"]["receipt_kind"], "agentcoin-payment-receipt")
            self.assertEqual(payload["payment"]["proof_type"], "local-operator-attestation")
            self.assertEqual(payload["payment"]["challenge"]["workflow_name"], "premium-review")
            self.assertEqual(payload["payment"]["challenge"]["amount_wei"], str(node.config.payment_quote_amount_wei))
            self.assertEqual(payload["payment"]["challenge"]["bounty_escrow_address"], onchain.bounty_escrow_address)
            self.assertEqual(payload["payment"]["quote"]["workflow_name"], "premium-review")
            self.assertEqual(payload["payment"]["quote"]["quote_id"], payload["payment"]["challenge"]["challenge_id"])
            self.assertEqual(payload["payment"]["quote"]["quote_digest"], payload["payment"]["challenge"]["quote_digest"])
            self.assertEqual(headers.get("X-Agentcoin-Payment-Required"), "true")
            self.assertEqual(headers.get("X-Agentcoin-Payment-Amount-Wei"), str(node.config.payment_quote_amount_wei))
            self.assertEqual(headers.get("X-Agentcoin-Payment-Asset"), node.config.payment_quote_asset)
            self.assertEqual(headers.get("X-Agentcoin-Payment-Recipient"), onchain.local_controller_address)
            self.assertEqual(headers.get("X-Agentcoin-Payment-Bounty-Escrow"), onchain.bounty_escrow_address)
        finally:
            node.stop()

    def test_workflow_execute_accepts_signed_payment_receipt(self) -> None:
        key_path, public_key = self._generate_identity(Path(self.tempdir.name) / "id_client_payment_ok", "frontend-local-payment-ok")
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            local_controller_address="0x2222222222222222222222222222222222222222",
        )
        node = NodeHarness(
            node_id="payment-ok-node",
            token="token-payment-ok",
            db_path=str(Path(self.tempdir.name) / "payment-ok.db"),
            capabilities=["worker"],
            signing_secret="payment-ok-secret",
            payment_required_workflows=["premium-review"],
            onchain=onchain,
        )
        node.start()
        try:
            challenge_status, challenge_payload = self._identity_signed_post(
                f"{node.base_url}/v1/workflow/execute",
                {
                    "workflow_name": "premium-review",
                    "input": {"prompt": "review this secret workflow"},
                },
                private_key_path=key_path,
                principal="frontend-local-payment-ok",
                public_key=public_key,
            )
            self.assertEqual(challenge_status, HTTPStatus.PAYMENT_REQUIRED)
            challenge_id = challenge_payload["payment"]["challenge"]["challenge_id"]

            issue_status, issued = self._post(
                f"{node.base_url}/v1/payments/receipts/issue",
                "token-payment-ok",
                {
                    "challenge_id": challenge_id,
                    "payer": "did:agentcoin:ssh-ed25519:testpayer",
                    "tx_hash": "0xabc123",
                },
            )
            self.assertEqual(issue_status, HTTPStatus.CREATED)
            receipt = issued["receipt"]
            receipt_id = str(receipt["receipt_id"])
            self.assertEqual(receipt["quote"]["quote_id"], challenge_id)
            self.assertEqual(receipt["quote_digest"], receipt["quote"]["quote_digest"])
            self.assertEqual(receipt["payment_proof"]["proof_type"], "local-operator-attestation")
            self.assertEqual(receipt["payment_proof"]["challenge_id"], challenge_id)
            self.assertEqual(receipt["payment_proof"]["quote_digest"], receipt["quote_digest"])
            self.assertEqual(receipt["payment_proof_digest"], issued["attestation"]["payment_proof_digest"])
            self.assertEqual(issued["attestation"]["kind"], "agentcoin-payment-attestation")
            self.assertTrue(issued["attestation"]["active"])
            self.assertEqual(issued["attestation"]["status"], "issued")
            receipt_verification = verify_document(
                receipt,
                secret="payment-ok-secret",
                expected_scope="payment-receipt",
                expected_key_id="payment-ok-node",
            )
            self.assertTrue(receipt_verification["verified"])

            introspect_before_status, introspect_before = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/introspect",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-ok",
                public_key=public_key,
            )
            self.assertEqual(introspect_before_status, HTTPStatus.OK)
            self.assertTrue(introspect_before["introspection"]["verified"])
            self.assertTrue(introspect_before["introspection"]["active"])
            self.assertEqual(introspect_before["introspection"]["status"], "issued")
            self.assertEqual(introspect_before["introspection"]["quote"]["quote_id"], challenge_id)
            self.assertEqual(introspect_before["introspection"]["quote_digest"], receipt["quote_digest"])
            self.assertEqual(introspect_before["introspection"]["payment_proof_digest"], receipt["payment_proof_digest"])
            self.assertEqual(
                introspect_before["introspection"]["payment_proof"]["proof_type"],
                "local-operator-attestation",
            )
            self.assertEqual(introspect_before["introspection"]["attestation"]["status"], "issued")
            self.assertTrue(introspect_before["introspection"]["attestation"]["active"])

            proof_before_status, proof_before = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-proof",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-ok",
                public_key=public_key,
            )
            self.assertEqual(proof_before_status, HTTPStatus.OK)
            self.assertEqual(proof_before["proof"]["kind"], "agentcoin-payment-onchain-proof")
            self.assertEqual(proof_before["proof"]["status"], "issued")
            self.assertTrue(proof_before["proof"]["active"])
            self.assertEqual(proof_before["proof"]["quote_digest"], receipt["quote_digest"])
            self.assertEqual(proof_before["proof"]["payment_proof_digest"], receipt["payment_proof_digest"])
            self.assertEqual(
                proof_before["proof"]["contracts"]["bounty_escrow"],
                onchain.bounty_escrow_address,
            )
            self.assertEqual(
                proof_before["proof"]["projection"]["args"]["receipt_id"],
                receipt_id,
            )
            proof_verification = verify_document(
                proof_before["proof"],
                secret="payment-ok-secret",
                expected_scope="payment-onchain-proof",
                expected_key_id="payment-ok-node",
            )
            self.assertTrue(proof_verification["verified"])

            plan_before_status, plan_before = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-rpc-plan",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-ok",
                public_key=public_key,
            )
            self.assertEqual(plan_before_status, HTTPStatus.OK)
            self.assertEqual(plan_before["plan"]["kind"], "agentcoin-payment-onchain-rpc-plan")
            self.assertEqual(plan_before["plan"]["proof"]["status"], "issued")
            self.assertEqual(plan_before["plan"]["intent"]["function"], "submitPaymentProof")
            self.assertEqual(
                plan_before["plan"]["intent"]["signature"],
                "submitPaymentProof(bytes32,bytes32,bytes32,bytes32,bytes32)",
            )
            self.assertEqual(
                plan_before["plan"]["proof"]["payment_proof_digest"],
                receipt["payment_proof_digest"],
            )
            self.assertEqual(
                plan_before["plan"]["rpc_payload"]["call"]["signature"],
                "submitPaymentProof(bytes32,bytes32,bytes32,bytes32,bytes32)",
            )
            self.assertGreaterEqual(len(plan_before["plan"]["probes"]), 2)
            plan_verification = verify_document(
                plan_before["plan"],
                secret="payment-ok-secret",
                expected_scope="payment-onchain-rpc-plan",
                expected_key_id="payment-ok-node",
            )
            self.assertTrue(plan_verification["verified"])

            execute_status, executed = self._identity_signed_post(
                f"{node.base_url}/v1/workflow/execute",
                {
                    "workflow_name": "premium-review",
                    "input": {"prompt": "review this secret workflow"},
                    "payment_receipt": receipt,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-ok",
                public_key=public_key,
            )
            self.assertEqual(execute_status, HTTPStatus.ACCEPTED)
            self.assertTrue(executed["payment_required"])
            self.assertTrue(executed["payment_verified"])
            self.assertEqual(executed["task"]["kind"], "workflow-execute")
            self.assertEqual(executed["task"]["payload"]["workflow_name"], "premium-review")
            self.assertEqual(executed["task"]["payload"]["_payment_receipt"]["challenge_id"], challenge_id)
            self.assertEqual(
                executed["task"]["payload"]["_payment_verification"]["receipt_status"]["status"],
                "consumed",
            )
            self.assertEqual(
                executed["task"]["payload"]["_payment_verification"]["receipt_status"]["consumed_task_id"],
                executed["task"]["id"],
            )

            status_code, receipt_status_payload = self._get_auth(
                f"{node.base_url}/v1/payments/receipts/status?receipt_id={receipt_id}",
                "token-payment-ok",
            )
            self.assertEqual(status_code, HTTPStatus.OK)
            self.assertEqual(receipt_status_payload["receipt"]["status"], "consumed")
            self.assertEqual(receipt_status_payload["receipt"]["consumed_task_id"], executed["task"]["id"])

            introspect_after_status, introspect_after = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/introspect",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-ok",
                public_key=public_key,
            )
            self.assertEqual(introspect_after_status, HTTPStatus.OK)
            self.assertFalse(introspect_after["introspection"]["active"])
            self.assertEqual(introspect_after["introspection"]["status"], "consumed")
            self.assertIn("consumed", introspect_after["introspection"]["reason"])
            self.assertEqual(introspect_after["introspection"]["quote_digest"], receipt["quote_digest"])
            self.assertEqual(introspect_after["introspection"]["payment_proof_digest"], receipt["payment_proof_digest"])
            self.assertEqual(introspect_after["introspection"]["attestation"]["status"], "consumed")
            self.assertFalse(introspect_after["introspection"]["attestation"]["active"])

            proof_after_status, proof_after = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-proof",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-ok",
                public_key=public_key,
            )
            self.assertEqual(proof_after_status, HTTPStatus.OK)
            self.assertEqual(proof_after["proof"]["status"], "consumed")
            self.assertFalse(proof_after["proof"]["active"])
            self.assertEqual(proof_after["proof"]["payment_proof_digest"], receipt["payment_proof_digest"])
            self.assertEqual(
                proof_after["proof"]["projection"]["args"]["attestation_digest"],
                proof_after["proof"]["attestation_digest"],
            )

            plan_after_status, plan_after = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-rpc-plan",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-ok",
                public_key=public_key,
            )
            self.assertEqual(plan_after_status, HTTPStatus.OK)
            self.assertEqual(plan_after["plan"]["proof"]["status"], "consumed")
            self.assertFalse(plan_after["plan"]["proof"]["active"])
            self.assertEqual(
                plan_after["plan"]["proof"]["payment_proof_digest"],
                receipt["payment_proof_digest"],
            )

            replay_status, replay_payload = self._identity_signed_post(
                f"{node.base_url}/v1/workflow/execute",
                {
                    "workflow_name": "premium-review",
                    "input": {"prompt": "review this secret workflow"},
                    "payment_receipt": receipt,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-ok",
                public_key=public_key,
            )
            self.assertEqual(replay_status, HTTPStatus.BAD_REQUEST)
            self.assertIn("already been consumed", replay_payload["error"])
        finally:
            node.stop()

    def test_payment_onchain_raw_bundle_and_relay(self) -> None:
        rpc = RpcHarness({"eth_sendRawTransaction": "0xpaymentproof1"})
        rpc.start()
        key_path, public_key = self._generate_identity(Path(self.tempdir.name) / "id_client_payment_relay", "frontend-local-payment-relay")
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            explorer_base_url="https://testnet.bscscan.com",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            local_controller_address="0x3333333333333333333333333333333333333333",
        )
        node = NodeHarness(
            node_id="payment-relay-node",
            token="token-payment-relay",
            db_path=str(Path(self.tempdir.name) / "payment-relay.db"),
            capabilities=["worker"],
            signing_secret="payment-relay-secret",
            payment_required_workflows=["premium-review"],
            onchain=onchain,
        )
        node.start()
        try:
            challenge_status, challenge_payload = self._identity_signed_post(
                f"{node.base_url}/v1/workflow/execute",
                {
                    "workflow_name": "premium-review",
                    "input": {"prompt": "review this secret workflow"},
                },
                private_key_path=key_path,
                principal="frontend-local-payment-relay",
                public_key=public_key,
            )
            self.assertEqual(challenge_status, HTTPStatus.PAYMENT_REQUIRED)
            challenge_id = challenge_payload["payment"]["challenge"]["challenge_id"]

            issue_status, issued = self._post(
                f"{node.base_url}/v1/payments/receipts/issue",
                "token-payment-relay",
                {
                    "challenge_id": challenge_id,
                    "payer": "did:agentcoin:ssh-ed25519:testpayer",
                    "tx_hash": "0xabc999",
                },
            )
            self.assertEqual(issue_status, HTTPStatus.CREATED)
            receipt = issued["receipt"]

            bundle_status, bundle_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-raw-bundle",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                    "raw_transactions": [
                        {"action": "submitPaymentProof", "raw_transaction": "0xaaaabbbb", "signed_by": "wallet-1"},
                    ],
                },
                private_key_path=key_path,
                principal="frontend-local-payment-relay",
                public_key=public_key,
            )
            self.assertEqual(bundle_status, HTTPStatus.OK)
            bundle = bundle_payload["bundle"]
            self.assertEqual(bundle["kind"], "evm-payment-raw-bundle")
            self.assertEqual(bundle["step_count"], 1)
            self.assertEqual(bundle["steps"][0]["action"], "submitPaymentProof")
            self.assertEqual(bundle["steps"][0]["raw_relay_payload"]["request"]["method"], "eth_sendRawTransaction")
            bundle_verification = verify_document(
                bundle,
                secret="payment-relay-secret",
                expected_scope="payment-onchain-raw-bundle",
                expected_key_id="payment-relay-node",
            )
            self.assertTrue(bundle_verification["verified"])

            relay_status, relay_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                    "raw_transactions": [
                        {"action": "submitPaymentProof", "raw_transaction": "0xaaaabbbb"},
                    ],
                },
                private_key_path=key_path,
                principal="frontend-local-payment-relay",
                public_key=public_key,
            )
            self.assertEqual(relay_status, HTTPStatus.OK)
            relay = relay_payload["relay"]
            self.assertEqual(relay["kind"], "evm-payment-relay")
            self.assertEqual(relay["completed_steps"], 1)
            self.assertEqual(relay["final_status"], "completed")
            self.assertTrue(relay["relay_record_id"])
            self.assertEqual(relay["submitted_steps"][0]["tx_hash"], "0xpaymentproof1")
            relay_verification = verify_document(
                relay,
                secret="payment-relay-secret",
                expected_scope="payment-onchain-relay",
                expected_key_id="payment-relay-node",
            )
            self.assertTrue(relay_verification["verified"])
            history_status, history_payload = self._get_auth(
                f"{node.base_url}/v1/payments/receipts/onchain-relays?receipt_id={receipt['receipt_id']}",
                "token-payment-relay",
            )
            self.assertEqual(history_status, HTTPStatus.OK)
            self.assertEqual(len(history_payload["items"]), 1)
            self.assertEqual(history_payload["items"][0]["id"], relay["relay_record_id"])

            latest_status, latest_payload = self._get_auth(
                f"{node.base_url}/v1/payments/receipts/onchain-relays/latest?receipt_id={receipt['receipt_id']}",
                "token-payment-relay",
            )
            self.assertEqual(latest_status, HTTPStatus.OK)
            self.assertEqual(latest_payload["id"], relay["relay_record_id"])
            self.assertEqual([call["method"] for call in rpc.calls], ["eth_sendRawTransaction"])
        finally:
            node.stop()
            rpc.stop()

    def test_payment_onchain_relay_queue_persists_items(self) -> None:
        key_path, public_key = self._generate_identity(
            Path(self.tempdir.name) / "id_client_payment_queue",
            "frontend-local-payment-queue",
        )
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            explorer_base_url="https://testnet.bscscan.com",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            local_controller_address="0x3333333333333333333333333333333333333333",
        )
        node = NodeHarness(
            node_id="payment-queue-node",
            token="token-payment-queue",
            db_path=str(Path(self.tempdir.name) / "payment-queue.db"),
            capabilities=["worker"],
            signing_secret="payment-queue-secret",
            payment_required_workflows=["premium-review"],
            onchain=onchain,
        )
        node.start()
        try:
            challenge_status, challenge_payload = self._identity_signed_post(
                f"{node.base_url}/v1/workflow/execute",
                {"workflow_name": "premium-review", "input": {"prompt": "queue this proof"}},
                private_key_path=key_path,
                principal="frontend-local-payment-queue",
                public_key=public_key,
            )
            self.assertEqual(challenge_status, HTTPStatus.PAYMENT_REQUIRED)
            challenge_id = challenge_payload["payment"]["challenge"]["challenge_id"]

            issue_status, issued = self._post(
                f"{node.base_url}/v1/payments/receipts/issue",
                "token-payment-queue",
                {
                    "challenge_id": challenge_id,
                    "payer": "did:agentcoin:ssh-ed25519:testpayer",
                    "tx_hash": "0xqueueproof",
                },
            )
            self.assertEqual(issue_status, HTTPStatus.CREATED)
            receipt = issued["receipt"]

            queued_status, queued_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                    "raw_transactions": [
                        {"action": "submitPaymentProof", "raw_transaction": "0xaaaa"},
                    ],
                    "rpc_url": "https://bsc-testnet.example/rpc",
                    "max_attempts": 4,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-queue",
                public_key=public_key,
            )
            self.assertEqual(queued_status, HTTPStatus.CREATED)
            item = queued_payload["item"]
            self.assertEqual(item["receipt_id"], receipt["receipt_id"])
            self.assertEqual(item["workflow_name"], "premium-review")
            self.assertEqual(item["status"], "queued")
            self.assertEqual(item["max_attempts"], 4)

            list_status, list_payload = self._get_auth(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue?receipt_id={receipt['receipt_id']}",
                "token-payment-queue",
            )
            self.assertEqual(list_status, HTTPStatus.OK)
            self.assertEqual(len(list_payload["items"]), 1)
            self.assertEqual(list_payload["items"][0]["id"], item["id"])

            _, health = self._get(f"{node.base_url}/healthz")
            self.assertEqual(health["stats"]["payment_relay_queue"], 1)
            self.assertEqual(health["stats"]["payment_relay_queue_queued"], 1)
        finally:
            node.stop()

    def test_background_payment_relay_worker_processes_queued_items(self) -> None:
        rpc = RpcHarness({"eth_sendRawTransaction": "0xpaymentqueue1"})
        rpc.start()
        key_path, public_key = self._generate_identity(
            Path(self.tempdir.name) / "id_client_payment_queue_bg",
            "frontend-local-payment-queue-bg",
        )
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            explorer_base_url="https://testnet.bscscan.com",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            local_controller_address="0x3333333333333333333333333333333333333333",
        )
        node = NodeHarness(
            node_id="payment-queue-worker-node",
            token="token-payment-queue-worker",
            db_path=str(Path(self.tempdir.name) / "payment-queue-worker.db"),
            capabilities=["worker"],
            signing_secret="payment-queue-worker-secret",
            payment_required_workflows=["premium-review"],
            onchain=onchain,
            settlement_relay_poll_seconds=0.1,
        )
        node.start()
        try:
            challenge_status, challenge_payload = self._identity_signed_post(
                f"{node.base_url}/v1/workflow/execute",
                {"workflow_name": "premium-review", "input": {"prompt": "queue this proof in background"}},
                private_key_path=key_path,
                principal="frontend-local-payment-queue-bg",
                public_key=public_key,
            )
            self.assertEqual(challenge_status, HTTPStatus.PAYMENT_REQUIRED)
            challenge_id = challenge_payload["payment"]["challenge"]["challenge_id"]

            issue_status, issued = self._post(
                f"{node.base_url}/v1/payments/receipts/issue",
                "token-payment-queue-worker",
                {
                    "challenge_id": challenge_id,
                    "payer": "did:agentcoin:ssh-ed25519:testpayer",
                    "tx_hash": "0xqueueproofbg",
                },
            )
            self.assertEqual(issue_status, HTTPStatus.CREATED)
            receipt = issued["receipt"]

            queued_status, queued_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                    "raw_transactions": [
                        {"action": "submitPaymentProof", "raw_transaction": "0xbbbb"},
                    ],
                    "rpc_url": rpc.url,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-queue-bg",
                public_key=public_key,
            )
            self.assertEqual(queued_status, HTTPStatus.CREATED)
            item = queued_payload["item"]

            completed = self._wait_for_payment_queue_item_status(node, item["id"], status="completed", timeout=3.0)
            self.assertEqual(completed["attempts"], 1)
            self.assertTrue(completed["last_relay_id"])
            self.assertEqual(len(rpc.calls), 1)

            latest_status, latest_payload = self._get_auth(
                f"{node.base_url}/v1/payments/receipts/onchain-relays/latest?receipt_id={receipt['receipt_id']}",
                "token-payment-queue-worker",
            )
            self.assertEqual(latest_status, HTTPStatus.OK)
            self.assertEqual(latest_payload["id"], completed["last_relay_id"])
            self.assertEqual(latest_payload["final_status"], "completed")
        finally:
            node.stop()
            rpc.stop()

    def test_client_can_pause_and_resume_payment_relay_queue_item(self) -> None:
        rpc = RpcHarness({"eth_sendRawTransaction": "0xpaymentpause1"})
        rpc.start()
        key_path, public_key = self._generate_identity(
            Path(self.tempdir.name) / "id_client_payment_pause",
            "frontend-local-payment-pause",
        )
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            explorer_base_url="https://testnet.bscscan.com",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            local_controller_address="0x3333333333333333333333333333333333333333",
        )
        node = NodeHarness(
            node_id="payment-pause-node",
            token="token-payment-pause",
            db_path=str(Path(self.tempdir.name) / "payment-pause.db"),
            capabilities=["worker"],
            signing_secret="payment-pause-secret",
            payment_required_workflows=["premium-review"],
            onchain=onchain,
            settlement_relay_poll_seconds=0.1,
        )
        node.start()
        try:
            challenge_status, challenge_payload = self._identity_signed_post(
                f"{node.base_url}/v1/workflow/execute",
                {"workflow_name": "premium-review", "input": {"prompt": "pause this proof"}},
                private_key_path=key_path,
                principal="frontend-local-payment-pause",
                public_key=public_key,
            )
            self.assertEqual(challenge_status, HTTPStatus.PAYMENT_REQUIRED)
            challenge_id = challenge_payload["payment"]["challenge"]["challenge_id"]

            issue_status, issued = self._post(
                f"{node.base_url}/v1/payments/receipts/issue",
                "token-payment-pause",
                {
                    "challenge_id": challenge_id,
                    "payer": "did:agentcoin:ssh-ed25519:testpayer",
                    "tx_hash": "0xpaymentpause",
                },
            )
            self.assertEqual(issue_status, HTTPStatus.CREATED)
            receipt = issued["receipt"]

            queued_status, queued_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                    "raw_transactions": [
                        {"action": "submitPaymentProof", "raw_transaction": "0xaaaa"},
                    ],
                    "rpc_url": rpc.url,
                    "delay_seconds": 2,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-pause",
                public_key=public_key,
            )
            self.assertEqual(queued_status, HTTPStatus.CREATED)
            item = queued_payload["item"]

            paused_status, paused_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue/pause",
                {"queue_id": item["id"]},
                private_key_path=key_path,
                principal="frontend-local-payment-pause",
                public_key=public_key,
            )
            self.assertEqual(paused_status, HTTPStatus.OK)
            self.assertEqual(paused_payload["item"]["status"], "paused")

            time.sleep(0.6)
            paused = node.node.store.get_payment_relay_queue_item(item["id"])
            assert paused is not None
            self.assertEqual(paused["status"], "paused")
            self.assertEqual(len(rpc.calls), 0)

            queue_status, queue_payload = self._get_auth(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue?status=paused",
                "token-payment-pause",
            )
            self.assertEqual(queue_status, HTTPStatus.OK)
            self.assertEqual(len(queue_payload["items"]), 1)
            self.assertEqual(queue_payload["items"][0]["id"], item["id"])

            resumed_status, resumed_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue/resume",
                {"queue_id": item["id"], "delay_seconds": 0},
                private_key_path=key_path,
                principal="frontend-local-payment-pause",
                public_key=public_key,
            )
            self.assertEqual(resumed_status, HTTPStatus.OK)
            self.assertEqual(resumed_payload["item"]["status"], "queued")

            completed = self._wait_for_payment_queue_item_status(node, item["id"], status="completed", timeout=3.0)
            self.assertEqual(completed["attempts"], 1)
            self.assertEqual(len(rpc.calls), 1)

            _, health = self._get(f"{node.base_url}/healthz")
            self.assertEqual(health["stats"]["payment_relay_queue_paused"], 0)
            self.assertEqual(health["stats"]["payment_relay_queue_completed"], 1)
        finally:
            node.stop()
            rpc.stop()

    def test_client_can_requeue_dead_letter_payment_relay_item(self) -> None:
        rpc = RpcHarness({"eth_sendRawTransaction": "0xpaymentrequeue1"})
        rpc.start()
        key_path, public_key = self._generate_identity(
            Path(self.tempdir.name) / "id_client_payment_requeue",
            "frontend-local-payment-requeue",
        )
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="http://127.0.0.1:1",
            explorer_base_url="https://testnet.bscscan.com",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            local_controller_address="0x3333333333333333333333333333333333333333",
        )
        node = NodeHarness(
            node_id="payment-requeue-node",
            token="token-payment-requeue",
            db_path=str(Path(self.tempdir.name) / "payment-requeue.db"),
            capabilities=["worker"],
            signing_secret="payment-requeue-secret",
            payment_required_workflows=["premium-review"],
            onchain=onchain,
            settlement_relay_poll_seconds=0.1,
        )
        node.start()
        try:
            challenge_status, challenge_payload = self._identity_signed_post(
                f"{node.base_url}/v1/workflow/execute",
                {"workflow_name": "premium-review", "input": {"prompt": "requeue this proof"}},
                private_key_path=key_path,
                principal="frontend-local-payment-requeue",
                public_key=public_key,
            )
            self.assertEqual(challenge_status, HTTPStatus.PAYMENT_REQUIRED)
            challenge_id = challenge_payload["payment"]["challenge"]["challenge_id"]

            issue_status, issued = self._post(
                f"{node.base_url}/v1/payments/receipts/issue",
                "token-payment-requeue",
                {
                    "challenge_id": challenge_id,
                    "payer": "did:agentcoin:ssh-ed25519:testpayer",
                    "tx_hash": "0xpaymentrequeue",
                },
            )
            self.assertEqual(issue_status, HTTPStatus.CREATED)
            receipt = issued["receipt"]

            queued_status, queued_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                    "raw_transactions": [
                        {"action": "submitPaymentProof", "raw_transaction": "0xaaaa"},
                    ],
                    "rpc_url": "http://127.0.0.1:1",
                    "timeout_seconds": 0.2,
                    "max_attempts": 1,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-requeue",
                public_key=public_key,
            )
            self.assertEqual(queued_status, HTTPStatus.CREATED)
            item = queued_payload["item"]

            dead_letter = self._wait_for_payment_queue_item_status(node, item["id"], status="dead-letter", timeout=3.0)
            self.assertEqual(dead_letter["attempts"], 1)
            self.assertTrue(dead_letter["last_relay_id"])

            latest_failed_status, latest_failed_payload = self._get_auth(
                f"{node.base_url}/v1/payments/receipts/onchain-relays/latest-failed?receipt_id={receipt['receipt_id']}",
                "token-payment-requeue",
            )
            self.assertEqual(latest_failed_status, HTTPStatus.OK)
            self.assertEqual(latest_failed_payload["final_status"], "failed")
            self.assertEqual(latest_failed_payload["receipt_id"], receipt["receipt_id"])

            summary_status, summary_payload = self._get_auth(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue/summary?receipt_id={receipt['receipt_id']}",
                "token-payment-requeue",
            )
            self.assertEqual(summary_status, HTTPStatus.OK)
            self.assertEqual(summary_payload["item_count"], 1)
            self.assertEqual(summary_payload["counts"]["dead-letter"], 1)
            self.assertEqual(summary_payload["latest_failed_item"]["id"], item["id"])

            helper_status, helper_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay/replay-helper",
                {"receipt_id": receipt["receipt_id"]},
                private_key_path=key_path,
                principal="frontend-local-payment-requeue",
                public_key=public_key,
            )
            self.assertEqual(helper_status, HTTPStatus.OK)
            helper = helper_payload["helper"]
            self.assertEqual(helper["receipt_id"], receipt["receipt_id"])
            self.assertEqual(helper["source_type"], "queue-item")
            self.assertEqual(helper["queue_requeue_request"]["queue_id"], item["id"])
            self.assertEqual(helper["direct_relay_request"]["raw_transactions"][0]["action"], "submitPaymentProof")
            helper_verification = verify_document(
                helper,
                secret="payment-requeue-secret",
                expected_scope="payment-onchain-relay-replay-helper",
                expected_key_id="payment-requeue-node",
            )
            self.assertTrue(helper_verification["verified"])

            requeued_status, requeued_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue/requeue",
                {
                    "queue_id": item["id"],
                    "rpc_url": rpc.url,
                    "timeout_seconds": 10,
                    "max_attempts": 2,
                    "delay_seconds": 0,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-requeue",
                public_key=public_key,
            )
            self.assertEqual(requeued_status, HTTPStatus.OK)
            self.assertEqual(requeued_payload["item"]["status"], "queued")
            self.assertEqual(requeued_payload["item"]["attempts"], 0)
            self.assertEqual(requeued_payload["item"]["max_attempts"], 2)
            self.assertEqual(requeued_payload["item"]["payload"]["rpc_url"], rpc.url)

            completed = self._wait_for_payment_queue_item_status(node, item["id"], status="completed", timeout=3.0)
            self.assertEqual(completed["attempts"], 1)
            self.assertTrue(completed["last_relay_id"])
            self.assertEqual(len(rpc.calls), 1)

            history_status, history_payload = self._get_auth(
                f"{node.base_url}/v1/payments/receipts/onchain-relays?receipt_id={receipt['receipt_id']}",
                "token-payment-requeue",
            )
            self.assertEqual(history_status, HTTPStatus.OK)
            self.assertEqual(len(history_payload["items"]), 2)
            self.assertEqual(history_payload["items"][0]["final_status"], "completed")
            self.assertEqual(history_payload["items"][1]["final_status"], "failed")

            ops_status, ops_summary = self._identity_signed_get(
                f"{node.base_url}/v1/payments/ops/summary?receipt_id={receipt['receipt_id']}&relay_limit=2",
                private_key_path=key_path,
                principal="frontend-local-payment-requeue",
                public_key=public_key,
            )
            self.assertEqual(ops_status, HTTPStatus.OK)
            self.assertEqual(ops_summary["kind"], "agentcoin-payment-ops-summary")
            self.assertEqual(ops_summary["receipt_id"], receipt["receipt_id"])
            self.assertEqual(ops_summary["queue_summary"]["item_count"], 1)
            self.assertEqual(ops_summary["latest_failed_relay"]["final_status"], "failed")
            self.assertEqual(len(ops_summary["recent_relays"]), 2)
            ops_verification = verify_document(
                ops_summary,
                secret="payment-requeue-secret",
                expected_scope="payment-ops-summary",
                expected_key_id="payment-requeue-node",
            )
            self.assertTrue(ops_verification["verified"])
        finally:
            node.stop()
            rpc.stop()

    def test_client_can_cancel_and_delete_payment_relay_queue_item(self) -> None:
        key_path, public_key = self._generate_identity(
            Path(self.tempdir.name) / "id_client_payment_cancel",
            "frontend-local-payment-cancel",
        )
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            explorer_base_url="https://testnet.bscscan.com",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            local_controller_address="0x3333333333333333333333333333333333333333",
        )
        node = NodeHarness(
            node_id="payment-cancel-node",
            token="token-payment-cancel",
            db_path=str(Path(self.tempdir.name) / "payment-cancel.db"),
            capabilities=["worker"],
            signing_secret="payment-cancel-secret",
            payment_required_workflows=["premium-review"],
            onchain=onchain,
            settlement_relay_poll_seconds=0.1,
        )
        node.start()
        try:
            challenge_status, challenge_payload = self._identity_signed_post(
                f"{node.base_url}/v1/workflow/execute",
                {"workflow_name": "premium-review", "input": {"prompt": "cancel this proof"}},
                private_key_path=key_path,
                principal="frontend-local-payment-cancel",
                public_key=public_key,
            )
            self.assertEqual(challenge_status, HTTPStatus.PAYMENT_REQUIRED)
            challenge_id = challenge_payload["payment"]["challenge"]["challenge_id"]

            issue_status, issued = self._post(
                f"{node.base_url}/v1/payments/receipts/issue",
                "token-payment-cancel",
                {
                    "challenge_id": challenge_id,
                    "payer": "did:agentcoin:ssh-ed25519:testpayer",
                    "tx_hash": "0xpaymentcancel",
                },
            )
            self.assertEqual(issue_status, HTTPStatus.CREATED)
            receipt = issued["receipt"]

            queued_status, queued_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                    "raw_transactions": [
                        {"action": "submitPaymentProof", "raw_transaction": "0xaaaa"},
                    ],
                    "rpc_url": "https://bsc-testnet.example/rpc",
                    "delay_seconds": 2,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-cancel",
                public_key=public_key,
            )
            self.assertEqual(queued_status, HTTPStatus.CREATED)
            item = queued_payload["item"]

            cancel_status, cancel_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue/cancel",
                {"queue_id": item["id"]},
                private_key_path=key_path,
                principal="frontend-local-payment-cancel",
                public_key=public_key,
            )
            self.assertEqual(cancel_status, HTTPStatus.OK)
            self.assertEqual(cancel_payload["item"]["status"], "dead-letter")
            self.assertEqual(cancel_payload["item"]["last_error"], "cancelled")

            queue_status, queue_payload = self._get_auth(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue?status=dead-letter",
                "token-payment-cancel",
            )
            self.assertEqual(queue_status, HTTPStatus.OK)
            self.assertEqual(len(queue_payload["items"]), 1)
            self.assertEqual(queue_payload["items"][0]["id"], item["id"])

            delete_status, delete_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue/delete",
                {"queue_id": item["id"]},
                private_key_path=key_path,
                principal="frontend-local-payment-cancel",
                public_key=public_key,
            )
            self.assertEqual(delete_status, HTTPStatus.OK)
            self.assertTrue(delete_payload["ok"])

            _, queue_after = self._get_auth(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue?receipt_id={receipt['receipt_id']}",
                "token-payment-cancel",
            )
            self.assertEqual(queue_after["items"], [])

            _, health = self._get(f"{node.base_url}/healthz")
            self.assertEqual(health["stats"]["payment_relay_queue"], 0)
        finally:
            node.stop()

    def test_background_payment_relay_worker_auto_requeues_transient_dead_letter(self) -> None:
        key_path, public_key = self._generate_identity(
            Path(self.tempdir.name) / "id_client_payment_auto_requeue",
            "frontend-local-payment-auto-requeue",
        )
        rpc = RpcHarness({"eth_sendRawTransaction": "0xpaymentautorequeue1"})
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="http://127.0.0.1:1",
            explorer_base_url="https://testnet.bscscan.com",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            local_controller_address="0x3333333333333333333333333333333333333333",
        )
        node = NodeHarness(
            node_id="payment-auto-requeue-node",
            token="token-payment-auto-requeue",
            db_path=str(Path(self.tempdir.name) / "payment-auto-requeue.db"),
            capabilities=["worker"],
            signing_secret="payment-auto-requeue-secret",
            payment_required_workflows=["premium-review"],
            onchain=onchain,
            settlement_relay_poll_seconds=0.1,
            payment_relay_auto_requeue_enabled=True,
            payment_relay_auto_requeue_delay_seconds=1,
            payment_relay_auto_requeue_max_requeues=1,
        )
        node.start()
        try:
            challenge_status, challenge_payload = self._identity_signed_post(
                f"{node.base_url}/v1/workflow/execute",
                {"workflow_name": "premium-review", "input": {"prompt": "auto requeue this proof"}},
                private_key_path=key_path,
                principal="frontend-local-payment-auto-requeue",
                public_key=public_key,
            )
            self.assertEqual(challenge_status, HTTPStatus.PAYMENT_REQUIRED)
            challenge_id = challenge_payload["payment"]["challenge"]["challenge_id"]

            issue_status, issued = self._post(
                f"{node.base_url}/v1/payments/receipts/issue",
                "token-payment-auto-requeue",
                {
                    "challenge_id": challenge_id,
                    "payer": "did:agentcoin:ssh-ed25519:testpayer",
                    "tx_hash": "0xpaymentautorequeue",
                },
            )
            self.assertEqual(issue_status, HTTPStatus.CREATED)
            receipt = issued["receipt"]

            queued_status, queued_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                    "raw_transactions": [
                        {"action": "submitPaymentProof", "raw_transaction": "0xaaaa"},
                    ],
                    "timeout_seconds": 0.2,
                    "max_attempts": 1,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-auto-requeue",
                public_key=public_key,
            )
            self.assertEqual(queued_status, HTTPStatus.CREATED)
            item = queued_payload["item"]

            dead_letter = self._wait_for_payment_queue_item_status(node, item["id"], status="dead-letter", timeout=3.0)
            self.assertEqual(dead_letter["attempts"], 1)
            self.assertTrue(dead_letter["last_relay_id"])

            rpc.start()
            node.node.config.onchain.rpc_url = rpc.url

            completed = self._wait_for_payment_queue_item_status(node, item["id"], status="completed", timeout=4.0)
            self.assertEqual(completed["attempts"], 1)
            self.assertEqual(completed["payload"]["_auto_requeue_count"], 1)
            self.assertTrue(completed["last_relay_id"])
            self.assertEqual(len(rpc.calls), 1)

            ops_status, ops_summary = self._identity_signed_get(
                f"{node.base_url}/v1/payments/ops/summary?receipt_id={receipt['receipt_id']}",
                private_key_path=key_path,
                principal="frontend-local-payment-auto-requeue",
                public_key=public_key,
            )
            self.assertEqual(ops_status, HTTPStatus.OK)
            self.assertTrue(ops_summary["auto_requeue_policy"]["enabled"])
            self.assertEqual(ops_summary["auto_requeue_policy"]["max_requeues"], 1)
        finally:
            node.stop()
            rpc.stop()

    def test_client_can_disable_and_reenable_payment_relay_auto_requeue(self) -> None:
        key_path, public_key = self._generate_identity(
            Path(self.tempdir.name) / "id_client_payment_auto_requeue_override",
            "frontend-local-payment-auto-requeue-override",
        )
        rpc = RpcHarness({"eth_sendRawTransaction": "0xpaymentautorequeueoverride1"})
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="http://127.0.0.1:1",
            explorer_base_url="https://testnet.bscscan.com",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            local_controller_address="0x3333333333333333333333333333333333333333",
        )
        node = NodeHarness(
            node_id="payment-auto-requeue-override-node",
            token="token-payment-auto-requeue-override",
            db_path=str(Path(self.tempdir.name) / "payment-auto-requeue-override.db"),
            capabilities=["worker"],
            signing_secret="payment-auto-requeue-override-secret",
            payment_required_workflows=["premium-review"],
            onchain=onchain,
            settlement_relay_poll_seconds=0.1,
            payment_relay_auto_requeue_enabled=True,
            payment_relay_auto_requeue_delay_seconds=2,
            payment_relay_auto_requeue_max_requeues=2,
        )
        node.start()
        try:
            challenge_status, challenge_payload = self._identity_signed_post(
                f"{node.base_url}/v1/workflow/execute",
                {"workflow_name": "premium-review", "input": {"prompt": "manually govern auto requeue"}},
                private_key_path=key_path,
                principal="frontend-local-payment-auto-requeue-override",
                public_key=public_key,
            )
            self.assertEqual(challenge_status, HTTPStatus.PAYMENT_REQUIRED)
            challenge_id = challenge_payload["payment"]["challenge"]["challenge_id"]

            issue_status, issued = self._post(
                f"{node.base_url}/v1/payments/receipts/issue",
                "token-payment-auto-requeue-override",
                {
                    "challenge_id": challenge_id,
                    "payer": "did:agentcoin:ssh-ed25519:testpayer",
                    "tx_hash": "0xpaymentautorequeueoverride",
                },
            )
            self.assertEqual(issue_status, HTTPStatus.CREATED)
            receipt = issued["receipt"]

            queued_status, queued_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue",
                {
                    "workflow_name": "premium-review",
                    "payment_receipt": receipt,
                    "raw_transactions": [
                        {"action": "submitPaymentProof", "raw_transaction": "0xbbbb"},
                    ],
                    "timeout_seconds": 0.2,
                    "max_attempts": 1,
                },
                private_key_path=key_path,
                principal="frontend-local-payment-auto-requeue-override",
                public_key=public_key,
            )
            self.assertEqual(queued_status, HTTPStatus.CREATED)
            item = queued_payload["item"]

            disable_status, disable_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue/auto-requeue/disable",
                {
                    "queue_id": item["id"],
                    "reason": "manual-review-pending",
                },
                private_key_path=key_path,
                principal="frontend-local-payment-auto-requeue-override",
                public_key=public_key,
            )
            self.assertEqual(disable_status, HTTPStatus.OK)
            self.assertTrue(disable_payload["item"]["payload"]["_auto_requeue_disabled"])
            self.assertEqual(
                disable_payload["item"]["payload"]["_auto_requeue_disabled_reason"],
                "manual-review-pending",
            )

            dead_letter = self._wait_for_payment_queue_item_status(node, item["id"], status="dead-letter", timeout=3.0)
            self.assertEqual(dead_letter["attempts"], 1)
            self.assertTrue(dead_letter["payload"]["_auto_requeue_disabled"])

            summary_status, summary_payload = self._identity_signed_get(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue/summary?receipt_id={receipt['receipt_id']}",
                private_key_path=key_path,
                principal="frontend-local-payment-auto-requeue-override",
                public_key=public_key,
            )
            self.assertEqual(summary_status, HTTPStatus.OK)
            self.assertEqual(summary_payload["auto_requeue_disabled_count"], 1)
            self.assertEqual(len(summary_payload["auto_requeue_disabled_items"]), 1)
            self.assertEqual(
                summary_payload["auto_requeue_disabled_items"][0]["reason"],
                "manual-review-pending",
            )
            self.assertEqual(
                summary_payload["latest_auto_requeue_override"]["state"],
                "disabled",
            )

            rpc.start()
            node.node.config.onchain.rpc_url = rpc.url
            time.sleep(2.5)
            still_dead_letter = node.node.store.get_payment_relay_queue_item(item["id"])
            self.assertIsNotNone(still_dead_letter)
            self.assertEqual(still_dead_letter["status"], "dead-letter")
            self.assertTrue(still_dead_letter["payload"]["_auto_requeue_disabled"])
            self.assertEqual(len(rpc.calls), 0)

            enable_status, enable_payload = self._identity_signed_post(
                f"{node.base_url}/v1/payments/receipts/onchain-relay-queue/auto-requeue/enable",
                {"queue_id": item["id"]},
                private_key_path=key_path,
                principal="frontend-local-payment-auto-requeue-override",
                public_key=public_key,
            )
            self.assertEqual(enable_status, HTTPStatus.OK)
            self.assertNotIn("_auto_requeue_disabled", enable_payload["item"]["payload"])

            completed = self._wait_for_payment_queue_item_status(node, item["id"], status="completed", timeout=5.0)
            self.assertEqual(completed["payload"]["_auto_requeue_count"], 1)
            self.assertIn("_auto_requeue_reenabled_at", completed["payload"])
            self.assertEqual(len(rpc.calls), 1)

            ops_status, ops_summary = self._identity_signed_get(
                f"{node.base_url}/v1/payments/ops/summary?receipt_id={receipt['receipt_id']}",
                private_key_path=key_path,
                principal="frontend-local-payment-auto-requeue-override",
                public_key=public_key,
            )
            self.assertEqual(ops_status, HTTPStatus.OK)
            self.assertEqual(ops_summary["auto_requeue_disabled_items"], [])
            self.assertEqual(
                ops_summary["latest_auto_requeue_override"]["state"],
                "enabled",
            )
            self.assertEqual(
                ops_summary["latest_auto_requeue_override"]["id"],
                item["id"],
            )
        finally:
            node.stop()
            rpc.stop()

    def test_signed_client_identity_can_create_and_bind_local_tasks_without_bearer(self) -> None:
        key_path, public_key = self._generate_identity(Path(self.tempdir.name) / "id_client_local_task", "frontend-local-2")
        node = NodeHarness(
            node_id="client-local-node",
            token="token-client-local",
            db_path=str(Path(self.tempdir.name) / "client-local.db"),
            capabilities=["worker"],
            runtimes=["openai-chat"],
        )
        node.start()
        try:
            status, created = self._identity_signed_post(
                f"{node.base_url}/v1/tasks",
                {
                    "id": "client-local-task-1",
                    "kind": "review",
                    "role": "reviewer",
                    "required_capabilities": ["reviewer"],
                    "payload": {"input": {"prompt": "review local diff"}},
                },
                private_key_path=key_path,
                principal="frontend-local-2",
                public_key=public_key,
            )
            self.assertEqual(status, HTTPStatus.CREATED)
            self.assertEqual(created["task"]["id"], "client-local-task-1")

            bind_status, bound = self._identity_signed_post(
                f"{node.base_url}/v1/runtimes/bind",
                {
                    "task_id": "client-local-task-1",
                    "runtime": "openai-chat",
                    "options": {
                        "endpoint": "http://127.0.0.1:12345/v1/chat/completions",
                        "model": "openclaw/gateway",
                        "prompt": "review local diff",
                    },
                },
                private_key_path=key_path,
                principal="frontend-local-2",
                public_key=public_key,
            )
            self.assertEqual(bind_status, HTTPStatus.OK)
            self.assertEqual(bound["runtime"]["runtime"], "openai-chat")

            eval_status, evaluated = self._identity_signed_post(
                f"{node.base_url}/v1/tasks/dispatch/evaluate",
                {
                    "id": "client-local-task-eval-1",
                    "kind": "review",
                    "role": "reviewer",
                    "required_capabilities": ["worker"],
                    "payload": {
                        "_runtime": {
                            "runtime": "openai-chat",
                        }
                    },
                },
                private_key_path=key_path,
                principal="frontend-local-2",
                public_key=public_key,
            )
            self.assertEqual(eval_status, HTTPStatus.OK)
            self.assertEqual(evaluated["requirements"]["runtime"], "openai-chat")

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "client-local-task-1"][0]
            self.assertEqual(task["payload"]["_runtime"]["runtime"], "openai-chat")
        finally:
            node.stop()

    def test_signed_client_identity_request_rejects_replayed_nonce(self) -> None:
        key_path, public_key = self._generate_identity(Path(self.tempdir.name) / "id_client_nonce", "frontend-local-3")
        node = NodeHarness(
            node_id="client-nonce-node",
            token="token-client-nonce",
            db_path=str(Path(self.tempdir.name) / "client-nonce.db"),
            capabilities=["worker"],
        )
        node.start()
        try:
            shared_nonce = "nonce-client-local-replay"
            shared_timestamp = utc_now()
            status, _ = self._identity_signed_post(
                f"{node.base_url}/v1/tasks",
                {
                    "id": "client-replay-task-1",
                    "kind": "generic",
                    "payload": {"input": "first"},
                },
                private_key_path=key_path,
                principal="frontend-local-3",
                public_key=public_key,
                nonce=shared_nonce,
                timestamp=shared_timestamp,
            )
            self.assertEqual(status, HTTPStatus.CREATED)

            replay_status, replay_payload = self._identity_signed_post(
                f"{node.base_url}/v1/tasks",
                {
                    "id": "client-replay-task-2",
                    "kind": "generic",
                    "payload": {"input": "second"},
                },
                private_key_path=key_path,
                principal="frontend-local-3",
                public_key=public_key,
                nonce=shared_nonce,
                timestamp=shared_timestamp,
            )
            self.assertEqual(replay_status, HTTPStatus.UNAUTHORIZED)
            self.assertIn("nonce", replay_payload["error"])
        finally:
            node.stop()

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
            self.assertIn("committee-member", capability_ids)

            _, examples = self._get(f"{node.base_url}/v1/schema/examples")
            self.assertEqual(examples["task_envelope"]["@type"], "agentcoin:TaskEnvelope")
            self.assertEqual(examples["receipts"]["deterministic_execution_receipt"]["@type"], "agentcoin:DeterministicExecutionReceipt")
            self.assertEqual(examples["receipts"]["subjective_review_receipt"]["schema_version"], "0.1")
            self.assertEqual(examples["receipts"]["settlement_relay_receipt"]["@type"], "agentcoin:SettlementRelayReceipt")

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

    def test_review_ack_adds_subjective_review_receipt(self) -> None:
        node = NodeHarness(
            node_id="review-receipt-node",
            token="token-review-receipt",
            db_path=str(Path(self.tempdir.name) / "review-receipt.db"),
            capabilities=["reviewer"],
        )
        node.start()
        try:
            created_status, _ = self._post(
                f"{node.base_url}/v1/tasks",
                "token-review-receipt",
                {
                    "id": "review-receipt-task-1",
                    "kind": "review",
                    "role": "reviewer",
                    "payload": {"_review": {"target_task_id": "git-task-1", "reviewer_type": "ai"}},
                },
            )
            self.assertEqual(created_status, 201)

            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-review-receipt",
                {"worker_id": "reviewer-1", "worker_capabilities": ["reviewer"], "lease_seconds": 30},
            )
            ack_status, ack = self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-review-receipt",
                {
                    "task_id": "review-receipt-task-1",
                    "worker_id": "reviewer-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"approved": True, "notes": "looks good", "worker_id": "reviewer-1"},
                },
            )
            self.assertEqual(ack_status, 200)
            self.assertTrue(ack["ok"])

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "review-receipt-task-1"][0]
            review_receipt = task["result"]["review_receipt"]
            self.assertEqual(review_receipt["@type"], "agentcoin:SubjectiveReviewReceipt")
            self.assertEqual(review_receipt["schema_version"], "0.1")
            self.assertEqual(review_receipt["reviewer_type"], "ai")
            self.assertEqual(review_receipt["target_task_id"], "git-task-1")
            self.assertTrue(review_receipt["approved"])
        finally:
            node.stop()

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

    def test_peer_health_tracks_failed_sync_and_sets_cooldown(self) -> None:
        node_a = NodeHarness(
            node_id="health-peer-a",
            token="token-health-a",
            db_path=str(Path(self.tempdir.name) / "health-peer-a.db"),
            capabilities=["planner"],
            peers=[
                PeerConfig(
                    peer_id="offline-peer",
                    name="Offline Peer",
                    url="http://127.0.0.1:1",
                    auth_token="token-offline",
                )
            ],
        )
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-health-a", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["peer_id"], "offline-peer")
            self.assertEqual(sync_payload["items"][0]["status"], "error")

            health_status, health = self._get(f"{node_a.base_url}/v1/peer-health?peer_id=offline-peer")
            self.assertEqual(health_status, 200)
            self.assertEqual(health["sync_failures"], 1)
            self.assertEqual(health["delivery_failures"], 0)
            self.assertTrue(health["dispatch_blocked"]["cooldown"])
            self.assertFalse(health["dispatch_blocked"]["blacklisted"])
        finally:
            node_a.stop()

    def test_dispatch_evaluate_surfaces_blacklisted_candidate_and_prefers_healthy_peer(self) -> None:
        node_b = NodeHarness(
            node_id="health-peer-b",
            token="token-health-b",
            db_path=str(Path(self.tempdir.name) / "health-peer-b.db"),
            capabilities=["reviewer"],
        )
        node_c = NodeHarness(
            node_id="health-peer-c",
            token="token-health-c",
            db_path=str(Path(self.tempdir.name) / "health-peer-c.db"),
            capabilities=["reviewer"],
        )
        node_a = NodeHarness(
            node_id="health-peer-root",
            token="token-health-root",
            db_path=str(Path(self.tempdir.name) / "health-peer-root.db"),
            capabilities=["planner"],
            peers=[
                PeerConfig(peer_id="health-peer-b", name="Health Peer B", url="", auth_token="token-health-b"),
                PeerConfig(peer_id="health-peer-c", name="Health Peer C", url="", auth_token="token-health-c"),
            ],
        )
        node_b.start()
        node_c.start()
        node_a.config.peers[0].url = node_b.base_url
        node_a.config.peers[1].url = node_c.base_url
        node_a.start()
        try:
            sync_status, _ = self._post(f"{node_a.base_url}/v1/peers/sync", "token-health-root", {})
            self.assertEqual(sync_status, 200)

            blacklist_status, blacklisted = self._post(
                f"{node_a.base_url}/v1/peer-health/blacklist",
                "token-health-root",
                {"peer_id": "health-peer-b", "blacklist_seconds": 120, "reason": "manual isolation"},
            )
            self.assertEqual(blacklist_status, 200)
            self.assertTrue(blacklisted["dispatch_blocked"]["blacklisted"])

            evaluate_status, evaluated = self._post(
                f"{node_a.base_url}/v1/tasks/dispatch/evaluate",
                "token-health-root",
                {
                    "id": "health-aware-task",
                    "kind": "review",
                    "role": "reviewer",
                    "required_capabilities": ["reviewer"],
                    "payload": {"input": "select healthy reviewer"},
                },
            )
            self.assertEqual(evaluate_status, 200)
            self.assertEqual(len(evaluated["candidates"]), 2)
            self.assertEqual(evaluated["candidates"][0]["target_ref"], "health-peer-c")
            blocked = [item for item in evaluated["candidates"] if item["target_ref"] == "health-peer-b"][0]
            self.assertFalse(blocked["dispatchable"])
            self.assertTrue(blocked["health"]["dispatch_blocked"]["blacklisted"])
            self.assertLess(blocked["score"], evaluated["candidates"][0]["score"])

            dispatch_status, dispatched = self._post(
                f"{node_a.base_url}/v1/tasks/dispatch",
                "token-health-root",
                {
                    "id": "health-aware-task-2",
                    "kind": "review",
                    "role": "reviewer",
                    "required_capabilities": ["reviewer"],
                    "payload": {"input": "actual dispatch"},
                },
            )
            self.assertEqual(dispatch_status, 201)
            self.assertEqual(dispatched["target"]["target_ref"], "health-peer-c")
        finally:
            node_a.stop()
            node_b.stop()
            node_c.stop()

    def test_dispatch_evaluate_penalizes_peer_backlog(self) -> None:
        node_b = NodeHarness(
            node_id="backlog-peer-b",
            token="token-backlog-b",
            db_path=str(Path(self.tempdir.name) / "backlog-peer-b.db"),
            capabilities=["reviewer"],
        )
        node_c = NodeHarness(
            node_id="backlog-peer-c",
            token="token-backlog-c",
            db_path=str(Path(self.tempdir.name) / "backlog-peer-c.db"),
            capabilities=["reviewer"],
        )
        node_a = NodeHarness(
            node_id="backlog-peer-a",
            token="token-backlog-a",
            db_path=str(Path(self.tempdir.name) / "backlog-peer-a.db"),
            capabilities=["planner"],
            peers=[
                PeerConfig(peer_id="backlog-peer-b", name="Backlog Peer B", url="", auth_token="token-backlog-b"),
                PeerConfig(peer_id="backlog-peer-c", name="Backlog Peer C", url="", auth_token="token-backlog-c"),
            ],
        )
        node_b.start()
        node_c.start()
        node_a.config.peers[0].url = node_b.base_url
        node_a.config.peers[1].url = node_c.base_url
        node_a.start()
        try:
            sync_status, _ = self._post(f"{node_a.base_url}/v1/peers/sync", "token-backlog-a", {})
            self.assertEqual(sync_status, 200)

            node_a.node.store.queue_outbox(
                "queued-message-1",
                f"{node_c.base_url}/v1/inbox",
                "token-backlog-c",
                {"id": "queued-message-1", "sender": "backlog-peer-a"},
            )
            node_a.node.store.queue_outbox(
                "queued-message-2",
                f"{node_c.base_url}/v1/inbox",
                "token-backlog-c",
                {"id": "queued-message-2", "sender": "backlog-peer-a"},
            )

            evaluate_status, evaluated = self._post(
                f"{node_a.base_url}/v1/tasks/dispatch/evaluate",
                "token-backlog-a",
                {
                    "id": "backlog-aware-task",
                    "kind": "review",
                    "role": "reviewer",
                    "required_capabilities": ["reviewer"],
                    "payload": {"input": "prefer less loaded peer"},
                },
            )
            self.assertEqual(evaluate_status, 200)
            self.assertEqual(evaluated["candidates"][0]["target_ref"], "backlog-peer-b")
            peer_c = [item for item in evaluated["candidates"] if item["target_ref"] == "backlog-peer-c"][0]
            self.assertEqual(peer_c["backlog"]["pending"], 2)
            self.assertLess(peer_c["score"], evaluated["candidates"][0]["score"])
            self.assertLess(peer_c["score_breakdown"]["relay_backlog_penalty"], 0)
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
            self.assertEqual(received[0]["payload"]["_verification"]["claimed_public_key"], pub_a)
            self.assertEqual(received[0]["payload"]["_verification"]["matched_public_key"], pub_a)
            self.assertEqual(received[0]["payload"]["_verification"]["trusted_key_count"], 1)
            self.assertEqual(received[0]["payload"]["_verification"]["revoked_key_count"], 0)

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

    def test_ssh_identity_rotation_accepts_additional_trusted_key(self) -> None:
        key_a_old, pub_a_old = self._generate_identity(Path(self.tempdir.name) / "id_a_old", "node-a")
        key_a_new, pub_a_new = self._generate_identity(Path(self.tempdir.name) / "id_a_new", "node-a")
        key_b, pub_b = self._generate_identity(Path(self.tempdir.name) / "id_b_rot", "node-b")

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-rotate-b.db"),
            capabilities=["worker"],
            peers=[
                PeerConfig(
                    peer_id="node-a",
                    name="Node A",
                    url="http://127.0.0.1:1",
                    auth_token="token-a",
                    identity_principal="node-a",
                    identity_public_key=pub_a_old,
                    identity_public_keys=[pub_a_new],
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
            db_path=str(Path(self.tempdir.name) / "ssh-rotate-a.db"),
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
            identity_private_key_path=key_a_new,
            identity_public_key=pub_a_new,
            identity_public_keys=[pub_a_old],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.config.peers[0].url = node_a.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_b.base_url}/v1/peers/sync", "token-b", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["status"], "ok")
            self.assertTrue(sync_payload["items"][0]["identity_signed"])

            _, card_payload = self._get(f"{node_a.base_url}/v1/card")
            self.assertEqual(card_payload["identity"]["public_key"], pub_a_new)
            self.assertEqual(card_payload["identity"]["public_keys"], [pub_a_new, pub_a_old])

            self._post(
                f"{node_a.base_url}/v1/tasks",
                "token-a",
                {"id": "ssh-rotate-1", "kind": "notify", "payload": {"x": 9}, "deliver_to": "node-b"},
            )
            flush_status, flushed = self._post(f"{node_a.base_url}/v1/outbox/flush", "token-a", {})
            self.assertEqual(flush_status, 200)
            self.assertEqual(flushed["flushed"], 1)

            _, tasks = self._get(f"{node_b.base_url}/v1/tasks")
            received = [item for item in tasks["items"] if item["id"] == "ssh-rotate-1"]
            self.assertEqual(len(received), 1)
            self.assertTrue(received[0]["payload"]["_verification"]["verified"])
            self.assertEqual(received[0]["payload"]["_verification"]["claimed_public_key"], pub_a_new)
            self.assertEqual(received[0]["payload"]["_verification"]["matched_public_key"], pub_a_new)
            self.assertEqual(received[0]["payload"]["_verification"]["trusted_key_count"], 2)
            self.assertEqual(received[0]["payload"]["_verification"]["revoked_key_count"], 0)

            self.assertEqual(node_b.config.peers[0].trusted_identity_public_keys, [pub_a_old, pub_a_new])
            self.assertEqual(node_a.config.card.identity["public_keys"], [pub_a_new, pub_a_old])
            self.assertEqual(node_a.config.card.identity["revoked_public_keys"], [])
        finally:
            node_a.stop()
            node_b.stop()

    def test_ssh_identity_rotation_rejects_untrusted_new_key(self) -> None:
        key_a_old, pub_a_old = self._generate_identity(Path(self.tempdir.name) / "id_a_old_reject", "node-a")
        key_a_new, pub_a_new = self._generate_identity(Path(self.tempdir.name) / "id_a_new_reject", "node-a")

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-rotate-reject-b.db"),
            capabilities=["worker"],
            peers=[
                PeerConfig(
                    peer_id="node-a",
                    name="Node A",
                    url="http://127.0.0.1:1",
                    auth_token="token-a",
                    identity_principal="node-a",
                    identity_public_key=pub_a_old,
                )
            ],
            require_signed_inbox=True,
        )
        node_b.start()
        try:
            rotated_payload = sign_document_with_ssh(
                {"id": "ssh-rotate-reject-1", "kind": "notify", "payload": {"x": 10}, "sender": "node-a"},
                private_key_path=key_a_new,
                principal="node-a",
                namespace="agentcoin-task",
                public_key=pub_a_new,
            )
            bad_status, bad_payload = self._post(f"{node_b.base_url}/v1/inbox", "token-b", rotated_payload)
            self.assertEqual(bad_status, 400)
            self.assertIn("signature", bad_payload["error"])
            self.assertEqual(node_b.config.peers[0].trusted_identity_public_keys, [pub_a_old])
        finally:
            node_b.stop()

    def test_ssh_identity_revocation_rejects_explicitly_revoked_key(self) -> None:
        key_a_old, pub_a_old = self._generate_identity(Path(self.tempdir.name) / "id_a_old_revoked", "node-a")
        key_a_new, pub_a_new = self._generate_identity(Path(self.tempdir.name) / "id_a_new_revoked", "node-a")

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-revoke-b.db"),
            capabilities=["worker"],
            peers=[
                PeerConfig(
                    peer_id="node-a",
                    name="Node A",
                    url="http://127.0.0.1:1",
                    auth_token="token-a",
                    identity_principal="node-a",
                    identity_public_key=pub_a_old,
                    identity_public_keys=[pub_a_new],
                    identity_revoked_public_keys=[pub_a_old],
                )
            ],
            require_signed_inbox=True,
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-revoke-a.db"),
            capabilities=["planner"],
            identity_principal="node-a",
            identity_private_key_path=key_a_new,
            identity_public_key=pub_a_new,
            identity_public_keys=[pub_a_old],
            identity_revoked_public_keys=[pub_a_old],
        )
        node_b.start()
        node_a.start()
        try:
            revoked_payload = sign_document_with_ssh(
                {"id": "ssh-revoke-1", "kind": "notify", "payload": {"x": 11}, "sender": "node-a"},
                private_key_path=key_a_old,
                principal="node-a",
                namespace="agentcoin-task",
                public_key=pub_a_old,
            )
            bad_status, bad_payload = self._post(f"{node_b.base_url}/v1/inbox", "token-b", revoked_payload)
            self.assertEqual(bad_status, 400)
            self.assertIn("revoked", bad_payload["error"])

            accepted_payload = sign_document_with_ssh(
                {"id": "ssh-revoke-2", "kind": "notify", "payload": {"x": 12}, "sender": "node-a"},
                private_key_path=key_a_new,
                principal="node-a",
                namespace="agentcoin-task",
                public_key=pub_a_new,
            )
            accepted_status, accepted = self._post(f"{node_b.base_url}/v1/inbox", "token-b", accepted_payload)
            self.assertEqual(accepted_status, 201)
            self.assertTrue(accepted["verified"])

            _, tasks = self._get(f"{node_b.base_url}/v1/tasks")
            received = [item for item in tasks["items"] if item["id"] == "ssh-revoke-2"]
            self.assertEqual(len(received), 1)
            self.assertTrue(received[0]["payload"]["_verification"]["verified"])
            self.assertEqual(received[0]["payload"]["_verification"]["claimed_public_key"], pub_a_new)
            self.assertEqual(received[0]["payload"]["_verification"]["matched_public_key"], pub_a_new)
            self.assertEqual(received[0]["payload"]["_verification"]["trusted_key_count"], 1)
            self.assertEqual(received[0]["payload"]["_verification"]["revoked_key_count"], 1)

            self.assertEqual(node_b.config.peers[0].trusted_identity_public_keys, [pub_a_new])
            self.assertEqual(node_b.config.peers[0].revoked_identity_public_keys, [pub_a_old])
            self.assertEqual(node_a.config.card.identity["public_keys"], [pub_a_new])
            self.assertEqual(node_a.config.card.identity["revoked_public_keys"], [pub_a_old])
        finally:
            node_a.stop()
            node_b.stop()

    def test_peer_sync_surfaces_pending_identity_trust_updates(self) -> None:
        key_b_old, pub_b_old = self._generate_identity(Path(self.tempdir.name) / "id_b_old_pending", "node-b")
        _, pub_b_new = self._generate_identity(Path(self.tempdir.name) / "id_b_new_pending", "node-b")

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-pending-b.db"),
            capabilities=["worker"],
            identity_principal="node-b",
            identity_private_key_path=key_b_old,
            identity_public_key=pub_b_old,
            identity_public_keys=[pub_b_new],
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-pending-a.db"),
            capabilities=["planner"],
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b_old,
                )
            ],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["status"], "ok")
            report = sync_payload["items"][0]["identity_trust"]
            self.assertFalse(report["aligned"])
            self.assertTrue(report["requires_review"])
            self.assertEqual(report["configured_trusted_public_keys"], [pub_b_old])
            self.assertEqual(report["advertised_active_public_keys"], [pub_b_old, pub_b_new])
            self.assertEqual(report["pending_trust_public_keys"], [pub_b_new])
            self.assertEqual(report["pending_revocation_public_keys"], [])
            self.assertEqual(report["stale_trusted_public_keys"], [])

            _, peer_cards = self._get(f"{node_a.base_url}/v1/peer-cards")
            stored = [item for item in peer_cards["items"] if item["peer_id"] == "node-b"]
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]["identity_trust"]["pending_trust_public_keys"], [pub_b_new])
            self.assertEqual(stored[0]["identity_trust"]["advertised_public_keys"], [pub_b_old, pub_b_new])
        finally:
            node_a.stop()
            node_b.stop()

    def test_peer_sync_surfaces_pending_identity_revocation_updates(self) -> None:
        key_b_old, pub_b_old = self._generate_identity(Path(self.tempdir.name) / "id_b_old_revoke_pending", "node-b")
        key_b_new, pub_b_new = self._generate_identity(Path(self.tempdir.name) / "id_b_new_revoke_pending", "node-b")

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-pending-revoke-b.db"),
            capabilities=["worker"],
            identity_principal="node-b",
            identity_private_key_path=key_b_new,
            identity_public_key=pub_b_new,
            identity_public_keys=[pub_b_old],
            identity_revoked_public_keys=[pub_b_old],
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-pending-revoke-a.db"),
            capabilities=["planner"],
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b_old,
                    identity_public_keys=[pub_b_new],
                )
            ],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["status"], "ok")
            report = sync_payload["items"][0]["identity_trust"]
            self.assertFalse(report["aligned"])
            self.assertTrue(report["requires_review"])
            self.assertEqual(report["configured_trusted_public_keys"], [pub_b_old, pub_b_new])
            self.assertEqual(report["advertised_active_public_keys"], [pub_b_new])
            self.assertEqual(report["advertised_revoked_public_keys"], [pub_b_old])
            self.assertEqual(report["pending_trust_public_keys"], [])
            self.assertEqual(report["pending_revocation_public_keys"], [pub_b_old])
            self.assertEqual(report["stale_trusted_public_keys"], [pub_b_old])

            _, peer_cards = self._get(f"{node_a.base_url}/v1/peer-cards")
            stored = [item for item in peer_cards["items"] if item["peer_id"] == "node-b"]
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]["identity_trust"]["pending_revocation_public_keys"], [pub_b_old])
            self.assertEqual(stored[0]["identity_trust"]["stale_trusted_public_keys"], [pub_b_old])
        finally:
            node_a.stop()
            node_b.stop()

    def test_operator_can_apply_pending_peer_identity_trust_update(self) -> None:
        key_b_old, pub_b_old = self._generate_identity(Path(self.tempdir.name) / "id_b_old_apply", "node-b")
        _, pub_b_new = self._generate_identity(Path(self.tempdir.name) / "id_b_new_apply", "node-b")

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-apply-b.db"),
            capabilities=["worker"],
            identity_principal="node-b",
            identity_private_key_path=key_b_old,
            identity_public_key=pub_b_old,
            identity_public_keys=[pub_b_new],
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-apply-a.db"),
            capabilities=["planner"],
            signing_secret="governance-secret",
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b_old,
                )
            ],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["identity_trust"]["pending_trust_public_keys"], [pub_b_new])

            apply_status, applied = self._post(
                f"{node_a.base_url}/v1/peers/identity-trust/apply",
                "token-a",
                {
                    "peer_id": "node-b",
                    "operator_id": "admin-1",
                    "reason": "approve rotated peer key",
                    "actions": ["apply-pending-trust"],
                    "payload": {"ticket": "TRUST-101"},
                },
            )
            self.assertEqual(apply_status, 200)
            self.assertEqual(applied["applied_actions"], ["apply-pending-trust"])
            self.assertEqual(applied["noop_actions"], [])
            self.assertTrue(applied["runtime_only"])
            self.assertFalse(applied["persisted_to_config"])
            self.assertFalse(applied["before"]["aligned"])
            self.assertTrue(applied["after"]["aligned"])
            self.assertEqual(applied["after"]["pending_trust_public_keys"], [])
            self.assertEqual(node_a.config.peers[0].trusted_identity_public_keys, [pub_b_old, pub_b_new])
            self.assertEqual(applied["action"]["operator_id"], "admin-1")
            self.assertEqual(applied["action"]["receipt"]["action_type"], "peer-identity-trust-apply")
            self.assertEqual(applied["action"]["receipt"]["@type"], "agentcoin:GovernanceActionReceipt")
            self.assertEqual(applied["action"]["receipt"]["target"]["kind"], "peer-identity-trust")
            self.assertEqual(applied["action"]["receipt"]["target"]["peer_id"], "node-b")
            self.assertEqual(applied["action"]["receipt"]["mutation"]["trusted_keys_added"], [pub_b_new])
            self.assertEqual(
                applied["action"]["receipt"]["reason_codes"],
                [
                    "pending-trust-key",
                    "requested-apply-pending-trust",
                    "applied-apply-pending-trust",
                    "runtime-only",
                ],
            )
            self.assertEqual(applied["action"]["receipt"]["auth_context"]["policy_tier"], "trust-admin")
            self.assertIn("before", applied["action"]["receipt"]["state_digests"])
            self.assertIn("after", applied["action"]["receipt"]["state_digests"])
            apply_verification = verify_document(
                applied["action"]["receipt"],
                secret="governance-secret",
                expected_scope="governance-receipt",
                expected_key_id="node-a",
            )
            self.assertTrue(apply_verification["verified"])

            _, peer_cards = self._get(f"{node_a.base_url}/v1/peer-cards")
            stored = [item for item in peer_cards["items"] if item["peer_id"] == "node-b"]
            self.assertEqual(len(stored), 1)
            self.assertTrue(stored[0]["identity_trust"]["aligned"])

            _, actions = self._get(f"{node_a.base_url}/v1/governance-actions?actor_id=node-b")
            self.assertEqual(actions["items"][0]["action_type"], "peer-identity-trust-apply")
            self.assertEqual(actions["items"][0]["operator_id"], "admin-1")
        finally:
            node_a.stop()
            node_b.stop()

    def test_signed_operator_request_is_required_for_trust_admin_endpoints(self) -> None:
        key_b_old, pub_b_old = self._generate_identity(Path(self.tempdir.name) / "id_b_old_signed_apply", "node-b")
        _, pub_b_new = self._generate_identity(Path(self.tempdir.name) / "id_b_new_signed_apply", "node-b")

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-signed-apply-b.db"),
            capabilities=["worker"],
            identity_principal="node-b",
            identity_private_key_path=key_b_old,
            identity_public_key=pub_b_old,
            identity_public_keys=[pub_b_new],
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-signed-apply-a.db"),
            capabilities=["planner"],
            signing_secret="governance-secret",
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="trust-admin:ops-1",
                    shared_secret="trust-operator-secret",
                    scopes=["trust-admin"],
                )
            ],
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b_old,
                )
            ],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["identity_trust"]["pending_trust_public_keys"], [pub_b_new])

            bearer_status, bearer_denied = self._post(
                f"{node_a.base_url}/v1/peers/identity-trust/apply",
                "token-a",
                {
                    "peer_id": "node-b",
                    "operator_id": "trust-admin:ops-1",
                    "reason": "approve rotated peer key",
                    "actions": ["apply-pending-trust"],
                },
            )
            self.assertEqual(bearer_status, 401)
            self.assertEqual(bearer_denied["policy_receipt"]["decision"], "rejected")
            self.assertEqual(bearer_denied["policy_receipt"]["reason_code"], "signed-request-required")
            denial_verification = verify_document(
                bearer_denied["policy_receipt"],
                secret="governance-secret",
                expected_scope="operator-auth-receipt",
                expected_key_id="node-a",
            )
            self.assertTrue(denial_verification["verified"])

            signed_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            signed_nonce = "trust-auth-nonce-1"
            signed_status, signed_applied = self._signed_post(
                f"{node_a.base_url}/v1/peers/identity-trust/apply",
                "token-a",
                {
                    "peer_id": "node-b",
                    "operator_id": "trust-admin:ops-1",
                    "reason": "approve rotated peer key",
                    "actions": ["apply-pending-trust"],
                    "payload": {"ticket": "TRUST-SIGNED-1"},
                },
                key_id="trust-admin:ops-1",
                shared_secret="trust-operator-secret",
                timestamp=signed_timestamp,
                nonce=signed_nonce,
            )
            self.assertEqual(signed_status, 200)
            self.assertEqual(signed_applied["action"]["operator_id"], "trust-admin:ops-1")
            self.assertEqual(signed_applied["action"]["receipt"]["auth_context"]["mode"], "signed-hmac")
            self.assertEqual(signed_applied["action"]["receipt"]["auth_context"]["key_id"], "trust-admin:ops-1")
            self.assertEqual(signed_applied["action"]["receipt"]["auth_context"]["policy_tier"], "trust-admin")
            self.assertEqual(signed_applied["action"]["receipt"]["auth_context"]["operator_id"], "trust-admin:ops-1")

            replay_status, replay_denied = self._signed_post(
                f"{node_a.base_url}/v1/peers/identity-trust/apply",
                "token-a",
                {
                    "peer_id": "node-b",
                    "operator_id": "trust-admin:ops-1",
                    "reason": "approve rotated peer key",
                    "actions": ["apply-pending-trust"],
                    "payload": {"ticket": "TRUST-SIGNED-1"},
                },
                key_id="trust-admin:ops-1",
                shared_secret="trust-operator-secret",
                timestamp=signed_timestamp,
                nonce=signed_nonce,
            )
            self.assertEqual(replay_status, 401)
            self.assertEqual(replay_denied["policy_receipt"]["reason_code"], "nonce-reused")

            audits = node_a.node.store.list_operator_auth_audits(
                endpoint="/v1/peers/identity-trust/apply",
                limit=10,
            )
            self.assertEqual([item["decision"] for item in audits[:3]], ["denied", "allowed", "denied"])
            self.assertEqual(audits[0]["payload"]["policy_receipt"]["reason_code"], "nonce-reused")
            self.assertEqual(audits[1]["key_id"], "trust-admin:ops-1")
            self.assertEqual(audits[1]["auth_mode"], "signed-hmac")
            self.assertEqual(audits[2]["payload"]["policy_receipt"]["reason_code"], "signed-request-required")
        finally:
            node_a.stop()
            node_b.stop()

    def test_operator_can_apply_pending_peer_identity_revocation_update(self) -> None:
        key_b_old, pub_b_old = self._generate_identity(Path(self.tempdir.name) / "id_b_old_apply_revoke", "node-b")
        key_b_new, pub_b_new = self._generate_identity(Path(self.tempdir.name) / "id_b_new_apply_revoke", "node-b")

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-apply-revoke-b.db"),
            capabilities=["worker"],
            identity_principal="node-b",
            identity_private_key_path=key_b_new,
            identity_public_key=pub_b_new,
            identity_public_keys=[pub_b_old],
            identity_revoked_public_keys=[pub_b_old],
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-apply-revoke-a.db"),
            capabilities=["planner"],
            signing_secret="governance-secret",
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b_old,
                    identity_public_keys=[pub_b_new],
                )
            ],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["identity_trust"]["pending_revocation_public_keys"], [pub_b_old])

            apply_status, applied = self._post(
                f"{node_a.base_url}/v1/peers/identity-trust/apply",
                "token-a",
                {
                    "peer_id": "node-b",
                    "operator_id": "admin-2",
                    "reason": "apply revoked key report",
                    "actions": ["apply-pending-revocations"],
                },
            )
            self.assertEqual(apply_status, 200)
            self.assertEqual(applied["applied_actions"], ["apply-pending-revocations"])
            self.assertTrue(applied["after"]["aligned"])
            self.assertEqual(applied["after"]["pending_revocation_public_keys"], [])
            self.assertEqual(node_a.config.peers[0].trusted_identity_public_keys, [pub_b_new])
            self.assertEqual(node_a.config.peers[0].revoked_identity_public_keys, [pub_b_old])

            _, peer_cards = self._get(f"{node_a.base_url}/v1/peer-cards")
            stored = [item for item in peer_cards["items"] if item["peer_id"] == "node-b"]
            self.assertEqual(len(stored), 1)
            self.assertTrue(stored[0]["identity_trust"]["aligned"])
            self.assertEqual(stored[0]["identity_trust"]["advertised_revoked_public_keys"], [pub_b_old])
        finally:
            node_a.stop()
            node_b.stop()

    def test_operator_can_adopt_advertised_peer_identity_principal_and_persist_to_config(self) -> None:
        config_path = self._write_node_config_file(
            Path(self.tempdir.name) / "node-a-principal-adopt.json",
            node_id="node-a",
            auth_token="token-a",
            peers=[
                {
                    "peer_id": "node-b",
                    "name": "Node B",
                    "url": "http://127.0.0.1:1",
                    "auth_token": "token-b",
                    "identity_principal": "node-b-old",
                }
            ],
        )

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-principal-adopt-b.db"),
            capabilities=["worker"],
            identity_principal="node-b-next",
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-principal-adopt-a.db"),
            capabilities=["planner"],
            signing_secret="governance-secret",
            config_path=config_path,
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b-old",
                )
            ],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)
            report = sync_payload["items"][0]["identity_trust"]
            self.assertFalse(report["aligned"])
            self.assertFalse(report["principal_match"])
            self.assertEqual(report["configured_principal"], "node-b-old")
            self.assertEqual(report["advertised_principal"], "node-b-next")

            apply_status, applied = self._post(
                f"{node_a.base_url}/v1/peers/identity-trust/apply",
                "token-a",
                {
                    "peer_id": "node-b",
                    "operator_id": "admin-principal",
                    "reason": "adopt peer principal rename",
                    "actions": ["adopt-advertised-principal"],
                    "persist_to_config": True,
                },
            )
            self.assertEqual(apply_status, 200)
            self.assertEqual(applied["applied_actions"], ["adopt-advertised-principal"])
            self.assertEqual(applied["noop_actions"], [])
            self.assertTrue(applied["persisted_to_config"])
            self.assertEqual(applied["before"]["configured_principal"], "node-b-old")
            self.assertEqual(applied["after"]["configured_principal"], "node-b-next")
            self.assertTrue(applied["after"]["principal_match"])
            self.assertTrue(applied["after"]["aligned"])
            self.assertEqual(node_a.config.peers[0].identity_principal, "node-b-next")
            self.assertEqual(node_a.config.peers[0].trusted_identity_public_keys, [])

            persisted = json.loads(Path(config_path).read_text(encoding="utf-8"))
            self.assertEqual(persisted["peers"][0]["identity_principal"], "node-b-next")
            self.assertNotIn("identity_public_key", persisted["peers"][0])

            _, actions = self._get(f"{node_a.base_url}/v1/governance-actions?actor_id=node-b")
            self.assertEqual(actions["items"][0]["payload"]["applied_actions"], ["adopt-advertised-principal"])
        finally:
            node_a.stop()
            node_b.stop()

    def test_operator_can_remove_stale_trusted_peer_identity_key_and_persist_to_config(self) -> None:
        _, pub_b_old = self._generate_identity(Path(self.tempdir.name) / "id_b_old_remove_stale", "node-b")
        key_b_new, pub_b_new = self._generate_identity(Path(self.tempdir.name) / "id_b_new_remove_stale", "node-b")
        config_path = self._write_node_config_file(
            Path(self.tempdir.name) / "node-a-remove-stale.json",
            node_id="node-a",
            auth_token="token-a",
            peers=[
                {
                    "peer_id": "node-b",
                    "name": "Node B",
                    "url": "http://127.0.0.1:1",
                    "auth_token": "token-b",
                    "identity_principal": "node-b",
                    "identity_public_key": pub_b_old,
                    "identity_public_keys": [pub_b_new],
                }
            ],
        )

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-remove-stale-b.db"),
            capabilities=["worker"],
            identity_principal="node-b",
            identity_private_key_path=key_b_new,
            identity_public_key=pub_b_new,
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-remove-stale-a.db"),
            capabilities=["planner"],
            signing_secret="governance-secret",
            config_path=config_path,
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b_old,
                    identity_public_keys=[pub_b_new],
                )
            ],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)
            report = sync_payload["items"][0]["identity_trust"]
            self.assertEqual(report["configured_trusted_public_keys"], [pub_b_old, pub_b_new])
            self.assertEqual(report["advertised_active_public_keys"], [pub_b_new])
            self.assertEqual(report["stale_trusted_public_keys"], [pub_b_old])
            self.assertFalse(report["aligned"])

            apply_status, applied = self._post(
                f"{node_a.base_url}/v1/peers/identity-trust/apply",
                "token-a",
                {
                    "peer_id": "node-b",
                    "operator_id": "admin-stale",
                    "reason": "drop stale rotated key",
                    "actions": ["remove-stale-trusted"],
                    "persist_to_config": True,
                },
            )
            self.assertEqual(apply_status, 200)
            self.assertEqual(applied["applied_actions"], ["remove-stale-trusted"])
            self.assertEqual(applied["noop_actions"], [])
            self.assertTrue(applied["persisted_to_config"])
            self.assertEqual(applied["before"]["stale_trusted_public_keys"], [pub_b_old])
            self.assertEqual(applied["after"]["configured_trusted_public_keys"], [pub_b_new])
            self.assertEqual(applied["after"]["stale_trusted_public_keys"], [])
            self.assertTrue(applied["after"]["aligned"])
            self.assertEqual(node_a.config.peers[0].trusted_identity_public_keys, [pub_b_new])
            self.assertEqual(node_a.config.peers[0].identity_public_key, pub_b_new)
            self.assertEqual(node_a.config.peers[0].identity_public_keys, [])

            persisted = json.loads(Path(config_path).read_text(encoding="utf-8"))
            self.assertEqual(persisted["peers"][0]["identity_public_key"], pub_b_new)
            self.assertNotIn("identity_public_keys", persisted["peers"][0])

            _, actions = self._get(f"{node_a.base_url}/v1/governance-actions?actor_id=node-b")
            self.assertEqual(actions["items"][0]["payload"]["applied_actions"], ["remove-stale-trusted"])
        finally:
            node_a.stop()
            node_b.stop()

    def test_operator_can_persist_peer_identity_trust_update_to_config_file(self) -> None:
        key_b_old, pub_b_old = self._generate_identity(Path(self.tempdir.name) / "id_b_old_persist", "node-b")
        _, pub_b_new = self._generate_identity(Path(self.tempdir.name) / "id_b_new_persist", "node-b")
        config_path = self._write_node_config_file(
            Path(self.tempdir.name) / "node-a-persist.json",
            node_id="node-a",
            auth_token="token-a",
            peers=[
                {
                    "peer_id": "node-b",
                    "name": "Node B",
                    "url": "http://127.0.0.1:1",
                    "auth_token": "token-b",
                    "identity_principal": "node-b",
                    "identity_public_key": pub_b_old,
                }
            ],
        )

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-persist-b.db"),
            capabilities=["worker"],
            identity_principal="node-b",
            identity_private_key_path=key_b_old,
            identity_public_key=pub_b_old,
            identity_public_keys=[pub_b_new],
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-persist-a.db"),
            capabilities=["planner"],
            signing_secret="governance-secret",
            config_path=config_path,
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b_old,
                )
            ],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["identity_trust"]["pending_trust_public_keys"], [pub_b_new])

            apply_status, applied = self._post(
                f"{node_a.base_url}/v1/peers/identity-trust/apply",
                "token-a",
                {
                    "peer_id": "node-b",
                    "operator_id": "admin-persist",
                    "reason": "persist rotated peer key",
                    "actions": ["apply-pending-trust"],
                    "persist_to_config": True,
                    "payload": {"ticket": "TRUST-202"},
                },
            )
            self.assertEqual(apply_status, 200)
            self.assertFalse(applied["runtime_only"])
            self.assertTrue(applied["persisted_to_config"])
            self.assertEqual(applied["config_path"], str(Path(config_path).resolve()))
            self.assertTrue(applied["after"]["aligned"])
            self.assertEqual(node_a.config.peers[0].trusted_identity_public_keys, [pub_b_old, pub_b_new])
            self.assertTrue(applied["action"]["payload"]["persisted_to_config"])

            persisted = json.loads(Path(config_path).read_text(encoding="utf-8"))
            self.assertEqual(len(persisted["peers"]), 1)
            self.assertEqual(persisted["peers"][0]["identity_public_key"], pub_b_old)
            self.assertEqual(persisted["peers"][0]["identity_public_keys"], [pub_b_new])
            self.assertNotIn("identity_revoked_public_keys", persisted["peers"][0])
        finally:
            node_a.stop()
            node_b.stop()

    def test_operator_persist_requires_loaded_config_path(self) -> None:
        key_b_old, pub_b_old = self._generate_identity(Path(self.tempdir.name) / "id_b_old_no_persist", "node-b")
        _, pub_b_new = self._generate_identity(Path(self.tempdir.name) / "id_b_new_no_persist", "node-b")

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-no-persist-b.db"),
            capabilities=["worker"],
            identity_principal="node-b",
            identity_private_key_path=key_b_old,
            identity_public_key=pub_b_old,
            identity_public_keys=[pub_b_new],
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-no-persist-a.db"),
            capabilities=["planner"],
            signing_secret="governance-secret",
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b_old,
                )
            ],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["identity_trust"]["pending_trust_public_keys"], [pub_b_new])

            apply_status, applied = self._post(
                f"{node_a.base_url}/v1/peers/identity-trust/apply",
                "token-a",
                {
                    "peer_id": "node-b",
                    "operator_id": "admin-fail",
                    "reason": "try persistence without config",
                    "actions": ["apply-pending-trust"],
                    "persist_to_config": True,
                },
            )
            self.assertEqual(apply_status, 400)
            self.assertIn("loaded via --config", applied["error"])
            self.assertEqual(node_a.config.peers[0].trusted_identity_public_keys, [pub_b_old])

            _, actions = self._get(f"{node_a.base_url}/v1/governance-actions?actor_id=node-b")
            self.assertEqual(actions["items"], [])
        finally:
            node_a.stop()
            node_b.stop()

    def test_operator_can_preview_peer_identity_trust_update_without_mutation(self) -> None:
        key_b_old, pub_b_old = self._generate_identity(Path(self.tempdir.name) / "id_b_old_preview", "node-b")
        _, pub_b_new = self._generate_identity(Path(self.tempdir.name) / "id_b_new_preview", "node-b")
        config_path = self._write_node_config_file(
            Path(self.tempdir.name) / "node-a-preview.json",
            node_id="node-a",
            auth_token="token-a",
            peers=[
                {
                    "peer_id": "node-b",
                    "name": "Node B",
                    "url": "http://127.0.0.1:1",
                    "auth_token": "token-b",
                    "identity_principal": "node-b",
                    "identity_public_key": pub_b_old,
                }
            ],
        )

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-preview-b.db"),
            capabilities=["worker"],
            identity_principal="node-b",
            identity_private_key_path=key_b_old,
            identity_public_key=pub_b_old,
            identity_public_keys=[pub_b_new],
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-preview-a.db"),
            capabilities=["planner"],
            signing_secret="governance-secret",
            config_path=config_path,
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b_old,
                )
            ],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["identity_trust"]["pending_trust_public_keys"], [pub_b_new])

            preview_status, preview = self._post(
                f"{node_a.base_url}/v1/peers/identity-trust/apply",
                "token-a",
                {
                    "peer_id": "node-b",
                    "operator_id": "admin-preview",
                    "reason": "preview rotated peer key",
                    "actions": ["apply-pending-trust"],
                    "preview_only": True,
                },
            )
            self.assertEqual(preview_status, 200)
            self.assertTrue(preview["preview_only"])
            self.assertFalse(preview["persisted_to_config"])
            self.assertTrue(preview["would_persist_to_config"])
            self.assertTrue(preview["after"]["aligned"])
            self.assertEqual(preview["config_preview"]["after_peer"]["identity_public_keys"], [pub_b_new])
            self.assertIn("identity_public_keys", preview["config_preview"]["diff"])

            self.assertEqual(node_a.config.peers[0].trusted_identity_public_keys, [pub_b_old])
            persisted = json.loads(Path(config_path).read_text(encoding="utf-8"))
            self.assertEqual(persisted["peers"][0]["identity_public_key"], pub_b_old)
            self.assertNotIn("identity_public_keys", persisted["peers"][0])

            _, actions = self._get(f"{node_a.base_url}/v1/governance-actions?actor_id=node-b")
            self.assertEqual(actions["items"], [])
        finally:
            node_a.stop()
            node_b.stop()

    def test_operator_can_export_peer_identity_trust_reconciliation_with_preview(self) -> None:
        key_b_old, pub_b_old = self._generate_identity(Path(self.tempdir.name) / "id_b_old_export_preview", "node-b")
        _, pub_b_new = self._generate_identity(Path(self.tempdir.name) / "id_b_new_export_preview", "node-b")
        config_path = self._write_node_config_file(
            Path(self.tempdir.name) / "node-a-export-preview.json",
            node_id="node-a",
            auth_token="token-a",
            peers=[
                {
                    "peer_id": "node-b",
                    "name": "Node B",
                    "url": "http://127.0.0.1:1",
                    "auth_token": "token-b",
                    "identity_principal": "node-b",
                    "identity_public_key": pub_b_old,
                }
            ],
        )

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-export-preview-b.db"),
            capabilities=["worker"],
            identity_principal="node-b",
            identity_private_key_path=key_b_old,
            identity_public_key=pub_b_old,
            identity_public_keys=[pub_b_new],
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-export-preview-a.db"),
            capabilities=["planner"],
            signing_secret="governance-secret",
            config_path=config_path,
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b_old,
                )
            ],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, _ = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)

            export_status, exported = self._post(
                f"{node_a.base_url}/v1/peers/identity-trust/export",
                "token-a",
                {"peer_id": "node-b"},
            )
            self.assertEqual(export_status, 200)
            self.assertTrue(exported["ok"])
            self.assertEqual(exported["config_path"], str(Path(config_path).resolve()))
            self.assertEqual(len(exported["items"]), 1)
            item = exported["items"][0]
            self.assertTrue(item["has_peer_card"])
            self.assertTrue(item["actionable"])
            self.assertEqual(item["severity"], "medium")
            self.assertEqual(item["severity_rank"], 2)
            self.assertEqual(item["severity_reasons"], ["pending-trust-key"])
            self.assertEqual(item["identity_trust"]["severity"], "medium")
            self.assertEqual(item["suggested_actions"], ["apply-pending-trust"])
            self.assertEqual(item["preview"]["applied_actions"], ["apply-pending-trust"])
            self.assertTrue(item["preview"]["would_persist_to_config"])
            self.assertEqual(item["preview"]["after"]["configured_trusted_public_keys"], [pub_b_old, pub_b_new])
            self.assertIn("identity_public_keys", item["preview"]["config_preview"]["diff"])

            _, actions = self._get(f"{node_a.base_url}/v1/governance-actions?actor_id=node-b")
            self.assertEqual(actions["items"], [])
            self.assertEqual(node_a.config.peers[0].trusted_identity_public_keys, [pub_b_old])
        finally:
            node_a.stop()
            node_b.stop()

    def test_operator_can_export_peer_identity_trust_reconciliation_without_loaded_config(self) -> None:
        key_b_old, pub_b_old = self._generate_identity(Path(self.tempdir.name) / "id_b_old_export_runtime", "node-b")
        _, pub_b_new = self._generate_identity(Path(self.tempdir.name) / "id_b_new_export_runtime", "node-b")

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-export-runtime-b.db"),
            capabilities=["worker"],
            identity_principal="node-b",
            identity_private_key_path=key_b_old,
            identity_public_key=pub_b_old,
            identity_public_keys=[pub_b_new],
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-export-runtime-a.db"),
            capabilities=["planner"],
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b_old,
                )
            ],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, _ = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)

            export_status, exported = self._post(
                f"{node_a.base_url}/v1/peers/identity-trust/export",
                "token-a",
                {"peer_id": "node-b"},
            )
            self.assertEqual(export_status, 200)
            item = exported["items"][0]
            self.assertIsNone(exported["config_path"])
            self.assertEqual(item["severity"], "medium")
            self.assertEqual(item["severity_reasons"], ["pending-trust-key"])
            self.assertEqual(item["suggested_actions"], ["apply-pending-trust"])
            self.assertFalse(item["preview"]["would_persist_to_config"])
            self.assertIsNone(item["preview"]["config_path"])
            self.assertIsNone(item["preview"]["config_preview"])
            self.assertEqual(item["preview"]["after"]["configured_trusted_public_keys"], [pub_b_old, pub_b_new])
            self.assertEqual(node_a.config.peers[0].trusted_identity_public_keys, [pub_b_old])
        finally:
            node_a.stop()
            node_b.stop()

    def test_operator_can_export_peer_identity_trust_reconciliation_sorted_by_severity(self) -> None:
        key_b_old, pub_b_old = self._generate_identity(Path(self.tempdir.name) / "id_b_old_export_severity", "node-b")
        _, pub_b_new = self._generate_identity(Path(self.tempdir.name) / "id_b_new_export_severity", "node-b")
        key_c_old, pub_c_old = self._generate_identity(Path(self.tempdir.name) / "id_c_old_export_severity", "node-c")

        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "ssh-export-severity-b.db"),
            capabilities=["worker"],
            identity_principal="node-b",
            identity_private_key_path=key_b_old,
            identity_public_key=pub_b_old,
            identity_public_keys=[pub_b_new],
        )
        node_c = NodeHarness(
            node_id="node-c",
            token="token-c",
            db_path=str(Path(self.tempdir.name) / "ssh-export-severity-c.db"),
            capabilities=["worker"],
            identity_principal="node-c",
            identity_private_key_path=key_c_old,
            identity_public_key=pub_c_old,
        )
        node_a = NodeHarness(
            node_id="node-a",
            token="token-a",
            db_path=str(Path(self.tempdir.name) / "ssh-export-severity-a.db"),
            capabilities=["planner"],
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b_old,
                ),
                PeerConfig(
                    peer_id="node-c",
                    name="Node C",
                    url="http://127.0.0.1:1",
                    auth_token="token-c",
                    identity_principal="node-c",
                    identity_public_key=pub_c_old,
                    identity_revoked_public_keys=[pub_c_old],
                ),
            ],
        )
        node_a.config.peers[0].url = node_b.base_url
        node_a.config.peers[1].url = node_c.base_url
        node_b.start()
        node_c.start()
        node_a.start()
        try:
            sync_status, _ = self._post(f"{node_a.base_url}/v1/peers/sync", "token-a", {})
            self.assertEqual(sync_status, 200)

            export_status, exported = self._post(
                f"{node_a.base_url}/v1/peers/identity-trust/export",
                "token-a",
                {"include_preview": False},
            )
            self.assertEqual(export_status, 200)
            self.assertEqual([item["peer_id"] for item in exported["items"]], ["node-c", "node-b"])

            critical = exported["items"][0]
            medium = exported["items"][1]
            self.assertEqual(critical["severity"], "critical")
            self.assertEqual(critical["severity_rank"], 4)
            self.assertEqual(critical["severity_reasons"], ["revoked-key-still-advertised"])
            self.assertEqual(critical["identity_trust"]["revoked_still_advertised_public_keys"], [pub_c_old])
            self.assertFalse(critical["actionable"])
            self.assertIsNone(critical["preview"])

            self.assertEqual(medium["severity"], "medium")
            self.assertEqual(medium["severity_rank"], 2)
            self.assertEqual(medium["severity_reasons"], ["pending-trust-key"])
        finally:
            node_a.stop()
            node_c.stop()
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

    def test_background_sync_loop_recovers_after_weak_network_peer_returns(self) -> None:
        recovery_node = NodeHarness(
            node_id="weak-network-peer-b",
            token="token-weak-network-b",
            db_path=str(Path(self.tempdir.name) / "weak-network-peer-b.db"),
            capabilities=["worker"],
        )
        root_node = NodeHarness(
            node_id="weak-network-root",
            token="token-weak-network-root",
            db_path=str(Path(self.tempdir.name) / "weak-network-root.db"),
            capabilities=["planner"],
            peers=[
                PeerConfig(
                    peer_id="weak-network-peer-b",
                    name="Weak Network Peer",
                    url=recovery_node.base_url,
                    auth_token="token-weak-network-b",
                )
            ],
            outbox_max_attempts=4,
            sync_interval_seconds=0.2,
        )
        root_node.start()
        try:
            self._post(
                f"{root_node.base_url}/v1/tasks/dispatch",
                "token-weak-network-root",
                {
                    "id": "weak-network-remote-1",
                    "kind": "code",
                    "deliver_to": "weak-network-peer-b",
                    "required_capabilities": ["worker"],
                },
            )

            def weak_network_failures_ready():
                health = root_node.node.store.get_peer_health("weak-network-peer-b")
                outbox = root_node.node.store.list_outbox(limit=10)
                task = root_node.node.store.get_task("weak-network-remote-1")
                if not health or not outbox or not task:
                    return None
                item = outbox[0]
                if health["sync_failures"] >= 2 and health["delivery_failures"] >= 1 and item["status"] == "retrying":
                    return {"health": health, "outbox": item, "task": task}
                return None

            failed_state = self._wait_until(
                weak_network_failures_ready,
                timeout=4.0,
                interval=0.1,
                message="weak-network failure state did not materialize",
            )
            self.assertEqual(failed_state["task"]["delivery_status"], "pending")
            self.assertEqual(failed_state["outbox"]["status"], "retrying")
            self.assertGreaterEqual(int(failed_state["outbox"]["attempts"] or 0), 1)

            recovery_node.start()

            def weak_network_recovery_ready():
                outbox_items = root_node.node.store.list_outbox(limit=10)
                if not outbox_items:
                    return None
                state = {
                    "task": root_node.node.store.get_task("weak-network-remote-1"),
                    "outbox": outbox_items[0],
                    "peer_cards": root_node.node.store.list_peer_cards(),
                    "health": root_node.node.store.get_peer_health("weak-network-peer-b"),
                }
                if state["outbox"]["status"] != "delivered":
                    return None
                if not any(item["peer_id"] == "weak-network-peer-b" for item in state["peer_cards"]):
                    return None
                if int(state["health"]["delivery_successes"] or 0) < 1:
                    return None
                return state

            delivered_state = self._wait_until(
                weak_network_recovery_ready,
                timeout=8.0,
                interval=0.1,
                message="background recovery did not deliver outbox and sync peer card",
            )

            _, tasks = self._get(f"{recovery_node.base_url}/v1/tasks")
            delivered = [item for item in tasks["items"] if item["id"] == "weak-network-remote-1"]
            self.assertEqual(len(delivered), 1)

            task = root_node.node.store.get_task("weak-network-remote-1")
            outbox = root_node.node.store.list_outbox(limit=10)[0]
            health = root_node.node.store.get_peer_health("weak-network-peer-b")
            self.assertIsNotNone(task)
            self.assertEqual(task["delivery_status"], "remote-accepted")
            self.assertEqual(outbox["status"], "delivered")
            self.assertGreaterEqual(int(health["sync_successes"] or 0), 1)
            self.assertGreaterEqual(int(health["delivery_successes"] or 0), 1)
            self.assertEqual(root_node.node.store.outbox_backlog(recovery_node.base_url)["dead_letter"], 0)
        finally:
            root_node.stop()
            recovery_node.stop()

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

    def test_signed_operator_request_is_required_for_workflow_admin_endpoints(self) -> None:
        node = NodeHarness(
            node_id="workflow-auth-node",
            token="token-workflow-auth",
            db_path=str(Path(self.tempdir.name) / "workflow-auth.db"),
            capabilities=["planner", "worker", "reviewer"],
            signing_secret="workflow-governance-secret",
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="workflow-admin:ops-1",
                    shared_secret="workflow-operator-secret",
                    scopes=["workflow-admin"],
                )
            ],
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-workflow-auth",
                {"id": "root-workflow-auth", "kind": "plan", "role": "planner"},
            )

            denied_status, denied = self._post(
                f"{node.base_url}/v1/workflows/fanout",
                "token-workflow-auth",
                {
                    "parent_task_id": "root-workflow-auth",
                    "operator_id": "workflow-admin:ops-1",
                    "subtasks": [
                        {"id": "branch-a-auth", "kind": "code", "role": "worker", "branch": "feature/a"},
                        {"id": "branch-b-auth", "kind": "code", "role": "worker", "branch": "feature/b"},
                    ],
                },
            )
            self.assertEqual(denied_status, 401)
            self.assertEqual(denied["policy_receipt"]["reason_code"], "signed-request-required")

            fanout_status, fanout = self._signed_post(
                f"{node.base_url}/v1/workflows/fanout",
                "token-workflow-auth",
                {
                    "parent_task_id": "root-workflow-auth",
                    "operator_id": "workflow-admin:ops-1",
                    "reason": "spawn protected workflow branches",
                    "payload": {"ticket": "WF-101"},
                    "subtasks": [
                        {"id": "branch-a-auth", "kind": "code", "role": "worker", "branch": "feature/a"},
                        {"id": "branch-b-auth", "kind": "code", "role": "worker", "branch": "feature/b"},
                    ],
                },
                key_id="workflow-admin:ops-1",
                shared_secret="workflow-operator-secret",
            )
            self.assertEqual(fanout_status, 201)
            self.assertEqual(fanout["action"]["action_type"], "workflow-fanout")
            self.assertEqual(fanout["action"]["operator_id"], "workflow-admin:ops-1")
            self.assertEqual(fanout["action"]["receipt"]["auth_context"]["policy_tier"], "workflow-admin")
            self.assertEqual(fanout["action"]["receipt"]["auth_context"]["mode"], "signed-hmac")
            self.assertEqual(len(fanout["items"]), 2)
            fanout_verification = verify_document(
                fanout["action"]["receipt"],
                secret="workflow-governance-secret",
                expected_scope="governance-receipt",
                expected_key_id="workflow-auth-node",
            )
            self.assertTrue(fanout_verification["verified"])

            review_status, review_gate = self._signed_post(
                f"{node.base_url}/v1/workflows/review-gate",
                "token-workflow-auth",
                {
                    "workflow_id": "root-workflow-auth",
                    "operator_id": "workflow-admin:ops-1",
                    "reason": "add approval tasks",
                    "reviews": [
                        {"id": "review-a-auth", "kind": "review", "role": "reviewer", "payload": {"_review": {"target_task_id": "branch-a-auth"}}},
                        {"id": "review-b-auth", "kind": "review", "role": "reviewer", "payload": {"_review": {"target_task_id": "branch-b-auth"}}},
                    ],
                },
                key_id="workflow-admin:ops-1",
                shared_secret="workflow-operator-secret",
            )
            self.assertEqual(review_status, 201)
            self.assertEqual(review_gate["action"]["action_type"], "workflow-review-gate")
            self.assertEqual(review_gate["action"]["receipt"]["auth_context"]["policy_tier"], "workflow-admin")

            merge_status, merge = self._signed_post(
                f"{node.base_url}/v1/workflows/merge",
                "token-workflow-auth",
                {
                    "workflow_id": "root-workflow-auth",
                    "operator_id": "workflow-admin:ops-1",
                    "reason": "open protected merge task",
                    "parent_task_ids": ["branch-a-auth", "branch-b-auth"],
                    "protected_branches": ["feature/a", "feature/b"],
                    "required_approvals_per_branch": 1,
                    "task": {"id": "merge-auth", "kind": "merge", "role": "reviewer", "branch": "main"},
                },
                key_id="workflow-admin:ops-1",
                shared_secret="workflow-operator-secret",
            )
            self.assertEqual(merge_status, 201)
            self.assertEqual(merge["action"]["action_type"], "workflow-merge")
            self.assertEqual(merge["action"]["receipt"]["auth_context"]["policy_tier"], "workflow-admin")

            for task_id in ["branch-a-auth", "branch-b-auth"]:
                _, claim = self._post(
                    f"{node.base_url}/v1/tasks/claim",
                    "token-workflow-auth",
                    {"worker_id": f"{task_id}-worker", "worker_capabilities": ["worker"], "lease_seconds": 30},
                )
                self.assertEqual(claim["task"]["id"], task_id)
                self._post(
                    f"{node.base_url}/v1/tasks/ack",
                    "token-workflow-auth",
                    {
                        "task_id": task_id,
                        "worker_id": claim["task"]["locked_by"],
                        "lease_token": claim["task"]["lease_token"],
                        "success": True,
                        "result": {"done": task_id},
                    },
                )

            seen_reviews: set[str] = set()
            for reviewer_id in ["reviewer-auth-a", "reviewer-auth-b"]:
                _, claim = self._post(
                    f"{node.base_url}/v1/tasks/claim",
                    "token-workflow-auth",
                    {"worker_id": reviewer_id, "worker_capabilities": ["reviewer"], "lease_seconds": 30},
                )
                review_task_id = claim["task"]["id"]
                self.assertIn(review_task_id, {"review-a-auth", "review-b-auth"})
                self.assertNotIn(review_task_id, seen_reviews)
                seen_reviews.add(review_task_id)
                self._post(
                    f"{node.base_url}/v1/tasks/ack",
                    "token-workflow-auth",
                    {
                        "task_id": review_task_id,
                        "worker_id": claim["task"]["locked_by"],
                        "lease_token": claim["task"]["lease_token"],
                        "success": True,
                        "result": {"approved": True},
                    },
                )

            _, merge_claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-workflow-auth",
                {"worker_id": "merge-auth-reviewer", "worker_capabilities": ["reviewer"], "lease_seconds": 30},
            )
            self.assertEqual(merge_claim["task"]["id"], "merge-auth")
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-workflow-auth",
                {
                    "task_id": "merge-auth",
                    "worker_id": merge_claim["task"]["locked_by"],
                    "lease_token": merge_claim["task"]["lease_token"],
                    "success": True,
                    "result": {"merged": ["branch-a-auth", "branch-b-auth"]},
                },
            )

            finalize_status, finalized = self._signed_post(
                f"{node.base_url}/v1/workflows/finalize",
                "token-workflow-auth",
                {
                    "workflow_id": "root-workflow-auth",
                    "operator_id": "workflow-admin:ops-1",
                    "reason": "finalize approved workflow",
                    "payload": {"ticket": "WF-101"},
                },
                key_id="workflow-admin:ops-1",
                shared_secret="workflow-operator-secret",
            )
            self.assertEqual(finalize_status, 200)
            self.assertTrue(finalized["ok"])
            self.assertEqual(finalized["action"]["action_type"], "workflow-finalize")
            self.assertEqual(finalized["action"]["receipt"]["auth_context"]["policy_tier"], "workflow-admin")

            _, workflow_actions = self._get(f"{node.base_url}/v1/governance-actions?actor_id=root-workflow-auth")
            action_types = [item["action_type"] for item in workflow_actions["items"][:4]]
            self.assertEqual(
                action_types,
                ["workflow-finalize", "workflow-merge", "workflow-review-gate", "workflow-fanout"],
            )

            audits = node.node.store.list_operator_auth_audits(endpoint="/v1/workflows/fanout", limit=10)
            self.assertEqual([item["decision"] for item in audits[:2]], ["allowed", "denied"])
            self.assertEqual(audits[0]["key_id"], "workflow-admin:ops-1")
            self.assertEqual(audits[1]["payload"]["policy_receipt"]["reason_code"], "signed-request-required")
        finally:
            node.stop()

    def test_signed_operator_request_is_required_for_bridge_admin_endpoints(self) -> None:
        node = NodeHarness(
            node_id="bridge-auth-node",
            token="token-bridge-auth",
            db_path=str(Path(self.tempdir.name) / "bridge-auth.db"),
            capabilities=["worker", "reviewer"],
            signing_secret="bridge-governance-secret",
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="bridge-admin:ops-1",
                    shared_secret="bridge-operator-secret",
                    scopes=["bridge-admin"],
                )
            ],
        )
        node.start()
        try:
            denied_import_status, denied_import = self._post(
                f"{node.base_url}/v1/bridges/import",
                "token-bridge-auth",
                {
                    "protocol": "mcp",
                    "message": {
                        "id": "bridge-auth-req-1",
                        "method": "tools/call",
                        "params": {"name": "reviewer", "arguments": {"path": "README.md"}},
                        "sender": "bridge-client",
                    },
                    "task_overrides": {"id": "bridge-auth-task", "role": "worker"},
                },
            )
            self.assertEqual(denied_import_status, 401)
            self.assertEqual(denied_import["policy_receipt"]["reason_code"], "signed-request-required")

            import_status, imported = self._signed_post(
                f"{node.base_url}/v1/bridges/import",
                "token-bridge-auth",
                {
                    "protocol": "mcp",
                    "operator_id": "bridge-admin:ops-1",
                    "reason": "ingest bridge task under operator control",
                    "payload": {"ticket": "BR-101"},
                    "message": {
                        "id": "bridge-auth-req-1",
                        "method": "tools/call",
                        "params": {"name": "reviewer", "arguments": {"path": "README.md"}},
                        "sender": "bridge-client",
                    },
                    "task_overrides": {"id": "bridge-auth-task", "role": "worker"},
                },
                key_id="bridge-admin:ops-1",
                shared_secret="bridge-operator-secret",
            )
            self.assertEqual(import_status, 201)
            self.assertEqual(imported["task"]["id"], "bridge-auth-task")
            self.assertEqual(imported["action"]["action_type"], "bridge-import")
            self.assertEqual(imported["action"]["operator_id"], "bridge-admin:ops-1")
            self.assertEqual(imported["action"]["receipt"]["auth_context"]["policy_tier"], "bridge-admin")
            self.assertEqual(imported["action"]["receipt"]["auth_context"]["mode"], "signed-hmac")
            import_verification = verify_document(
                imported["action"]["receipt"],
                secret="bridge-governance-secret",
                expected_scope="governance-receipt",
                expected_key_id="bridge-auth-node",
            )
            self.assertTrue(import_verification["verified"])

            denied_export_status, denied_export = self._post(
                f"{node.base_url}/v1/bridges/export",
                "token-bridge-auth",
                {"protocol": "mcp", "task_id": "bridge-auth-task"},
            )
            self.assertEqual(denied_export_status, 401)
            self.assertEqual(denied_export["policy_receipt"]["reason_code"], "signed-request-required")

            export_status, exported = self._signed_post(
                f"{node.base_url}/v1/bridges/export",
                "token-bridge-auth",
                {
                    "protocol": "mcp",
                    "task_id": "bridge-auth-task",
                    "operator_id": "bridge-admin:ops-1",
                    "reason": "export bridge response under operator control",
                    "payload": {"ticket": "BR-101"},
                    "result": {"approved": True, "notes": "ok"},
                },
                key_id="bridge-admin:ops-1",
                shared_secret="bridge-operator-secret",
            )
            self.assertEqual(export_status, 200)
            self.assertEqual(exported["message"]["id"], "bridge-auth-req-1")
            self.assertEqual(exported["action"]["action_type"], "bridge-export")
            self.assertEqual(exported["action"]["receipt"]["auth_context"]["policy_tier"], "bridge-admin")
            self.assertEqual(exported["action"]["receipt"]["auth_context"]["mode"], "signed-hmac")

            _, task_actions = self._get(f"{node.base_url}/v1/governance-actions?actor_id=bridge-auth-task")
            action_types = [item["action_type"] for item in task_actions["items"][:2]]
            self.assertEqual(action_types, ["bridge-export", "bridge-import"])

            import_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/bridges/import", limit=10)
            self.assertEqual([item["decision"] for item in import_audits[:2]], ["allowed", "denied"])
            self.assertEqual(import_audits[0]["key_id"], "bridge-admin:ops-1")
            self.assertEqual(import_audits[1]["payload"]["policy_receipt"]["reason_code"], "signed-request-required")

            export_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/bridges/export", limit=10)
            self.assertEqual([item["decision"] for item in export_audits[:2]], ["allowed", "denied"])
        finally:
            node.stop()

    def test_signed_operator_request_is_required_for_read_only_preview_endpoints(self) -> None:
        key_b_old, pub_b_old = self._generate_identity(Path(self.tempdir.name) / "id_b_old_read_only_scope", "node-b")
        _, pub_b_new = self._generate_identity(Path(self.tempdir.name) / "id_b_new_read_only_scope", "node-b")
        node_b = NodeHarness(
            node_id="node-b",
            token="token-b",
            db_path=str(Path(self.tempdir.name) / "read-only-scope-b.db"),
            capabilities=["worker"],
            signing_secret="node-b-secret",
            identity_principal="node-b",
            identity_private_key_path=key_b_old,
            identity_public_key=pub_b_old,
            identity_public_keys=[pub_b_new],
        )
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:read-only-scope",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node_a = NodeHarness(
            node_id="read-only-auth-node",
            token="token-read-only-auth",
            db_path=str(Path(self.tempdir.name) / "read-only-scope-a.db"),
            capabilities=["planner", "worker", "reviewer"],
            signing_secret="read-only-node-secret",
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="read-only:observer-1",
                    shared_secret="read-only-operator-secret",
                    scopes=["read-only"],
                ),
                OperatorIdentityConfig(
                    key_id="settlement-admin:ops-1",
                    shared_secret="settlement-preview-secret",
                    scopes=["settlement-admin"],
                ),
            ],
            peers=[
                PeerConfig(
                    peer_id="node-b",
                    name="Node B",
                    url="http://127.0.0.1:1",
                    auth_token="token-b",
                    identity_principal="node-b",
                    identity_public_key=pub_b_old,
                )
            ],
            onchain=onchain,
        )
        node_a.config.peers[0].url = node_b.base_url
        node_b.start()
        node_a.start()
        try:
            sync_status, sync_payload = self._post(f"{node_a.base_url}/v1/peers/sync", "token-read-only-auth", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["identity_trust"]["pending_trust_public_keys"], [pub_b_new])

            self._post(
                f"{node_a.base_url}/v1/tasks",
                "token-read-only-auth",
                {
                    "id": "read-only-plan-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 952,
                },
            )
            _, claim = self._post(
                f"{node_a.base_url}/v1/tasks/claim",
                "token-read-only-auth",
                {"worker_id": "worker-read-only-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node_a.base_url}/v1/tasks/ack",
                "token-read-only-auth",
                {
                    "task_id": "read-only-plan-task-1",
                    "worker_id": "worker-read-only-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-read-only-1"},
                },
            )

            evaluate_payload = {
                "id": "read-only-eval-task",
                "kind": "review",
                "role": "reviewer",
                "required_capabilities": ["reviewer"],
            }

            denied_evaluate_status, denied_evaluate = self._post(
                f"{node_a.base_url}/v1/tasks/dispatch/evaluate",
                "token-read-only-auth",
                evaluate_payload,
            )
            self.assertEqual(denied_evaluate_status, 401)
            self.assertEqual(denied_evaluate["policy_receipt"]["reason_code"], "signed-request-required")

            denied_export_status, denied_export = self._post(
                f"{node_a.base_url}/v1/peers/identity-trust/export",
                "token-read-only-auth",
                {"peer_id": "node-b", "include_preview": True},
            )
            self.assertEqual(denied_export_status, 401)
            self.assertEqual(denied_export["policy_receipt"]["reason_code"], "signed-request-required")

            denied_plan_status, denied_plan = self._post(
                f"{node_a.base_url}/v1/onchain/settlement-rpc-plan",
                "token-read-only-auth",
                {"task_id": "read-only-plan-task-1", "resolve_live": False},
            )
            self.assertEqual(denied_plan_status, 401)
            self.assertEqual(denied_plan["policy_receipt"]["reason_code"], "signed-request-required")

            evaluate_status, evaluated = self._signed_post(
                f"{node_a.base_url}/v1/tasks/dispatch/evaluate",
                "token-read-only-auth",
                evaluate_payload,
                key_id="read-only:observer-1",
                shared_secret="read-only-operator-secret",
            )
            self.assertEqual(evaluate_status, 200)
            self.assertEqual(evaluated["task"]["id"], "read-only-eval-task")
            self.assertEqual(len(evaluated["candidates"]), 1)

            export_status, exported = self._signed_post(
                f"{node_a.base_url}/v1/peers/identity-trust/export",
                "token-read-only-auth",
                {"peer_id": "node-b", "include_preview": True},
                key_id="read-only:observer-1",
                shared_secret="read-only-operator-secret",
            )
            self.assertEqual(export_status, 200)
            self.assertTrue(exported["ok"])
            self.assertEqual(len(exported["items"]), 1)
            self.assertEqual(exported["items"][0]["peer_id"], "node-b")
            self.assertEqual(exported["items"][0]["suggested_actions"], ["apply-pending-trust"])

            plan_status, plan_payload = self._signed_post(
                f"{node_a.base_url}/v1/onchain/settlement-rpc-plan",
                "token-read-only-auth",
                {"task_id": "read-only-plan-task-1", "resolve_live": False},
                key_id="read-only:observer-1",
                shared_secret="read-only-operator-secret",
            )
            self.assertEqual(plan_status, 200)
            plan = plan_payload["plan"]
            self.assertEqual(plan["kind"], "evm-settlement-rpc-plan")
            self.assertFalse(plan["resolved_live"])
            plan_verification = verify_document(
                plan,
                secret="read-only-node-secret",
                expected_scope="onchain-settlement-rpc-plan",
                expected_key_id="read-only-auth-node",
            )
            self.assertTrue(plan_verification["verified"])

            inherited_status, inherited = self._signed_post(
                f"{node_a.base_url}/v1/tasks/dispatch/evaluate",
                "token-read-only-auth",
                evaluate_payload,
                key_id="settlement-admin:ops-1",
                shared_secret="settlement-preview-secret",
            )
            self.assertEqual(inherited_status, 200)
            self.assertEqual(len(inherited["candidates"]), 1)

            denied_write_status, denied_write = self._signed_post(
                f"{node_a.base_url}/v1/bridges/import",
                "token-read-only-auth",
                {
                    "protocol": "mcp",
                    "message": {
                        "id": "read-only-bridge-denied-1",
                        "method": "tools/call",
                        "params": {"name": "reviewer", "arguments": {"path": "README.md"}},
                        "sender": "bridge-client",
                    },
                    "task_overrides": {"id": "read-only-bridge-denied-task", "role": "worker"},
                },
                key_id="read-only:observer-1",
                shared_secret="read-only-operator-secret",
            )
            self.assertEqual(denied_write_status, 403)
            self.assertEqual(denied_write["policy_receipt"]["reason_code"], "scope-denied")

            evaluate_audits = node_a.node.store.list_operator_auth_audits(endpoint="/v1/tasks/dispatch/evaluate", limit=10)
            self.assertEqual([item["decision"] for item in evaluate_audits[:3]], ["allowed", "allowed", "denied"])
            self.assertEqual(
                {item["key_id"] for item in evaluate_audits[:2]},
                {"read-only:observer-1", "settlement-admin:ops-1"},
            )
            self.assertEqual(evaluate_audits[2]["payload"]["policy_receipt"]["reason_code"], "signed-request-required")

            export_audits = node_a.node.store.list_operator_auth_audits(endpoint="/v1/peers/identity-trust/export", limit=10)
            self.assertEqual([item["decision"] for item in export_audits[:2]], ["allowed", "denied"])
            self.assertEqual(export_audits[0]["key_id"], "read-only:observer-1")

            plan_audits = node_a.node.store.list_operator_auth_audits(endpoint="/v1/onchain/settlement-rpc-plan", limit=10)
            self.assertEqual([item["decision"] for item in plan_audits[:2]], ["allowed", "denied"])
            self.assertEqual(plan_audits[0]["key_id"], "read-only:observer-1")

            bridge_audits = node_a.node.store.list_operator_auth_audits(endpoint="/v1/bridges/import", limit=10)
            self.assertEqual(bridge_audits[0]["decision"], "denied")
            self.assertEqual(bridge_audits[0]["payload"]["policy_receipt"]["reason_code"], "scope-denied")
        finally:
            node_a.stop()
            node_b.stop()

    def test_signed_operator_request_is_required_for_read_only_replay_and_settlement_observability(self) -> None:
        call_count = {"raw": 0}

        def raw_tx_response(_payload: dict[str, object]) -> str:
            call_count["raw"] += 1
            return f"0xreadonlyobserve{call_count['raw']}"

        rpc = RpcHarness({"eth_sendRawTransaction": raw_tx_response})
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:read-only-observe",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="read-only-observe-node",
            token="token-read-only-observe",
            db_path=str(Path(self.tempdir.name) / "read-only-observe.db"),
            capabilities=["worker", "reviewer"],
            signing_secret="read-only-observe-secret",
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="read-only:observer-1",
                    shared_secret="read-only-observer-secret",
                    scopes=["read-only"],
                ),
                OperatorIdentityConfig(
                    key_id="settlement-admin:ops-1",
                    shared_secret="settlement-observer-secret",
                    scopes=["settlement-admin"],
                ),
                OperatorIdentityConfig(
                    key_id="trust-admin:ops-1",
                    shared_secret="trust-observer-secret",
                    scopes=["trust-admin"],
                ),
            ],
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-read-only-observe",
                {
                    "id": "read-only-observe-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 963,
                },
            )
            self._complete_onchain_task(
                node,
                "token-read-only-observe",
                "read-only-observe-task-1",
                "worker-read-only-observe-1",
            )

            dispute_status, dispute_payload = self._signed_post(
                f"{node.base_url}/v1/disputes",
                "token-read-only-observe",
                {
                    "task_id": "read-only-observe-task-1",
                    "challenger_id": "reviewer-read-only-1",
                    "actor_id": "worker-read-only-observe-1",
                    "actor_type": "worker",
                    "reason": "inspection-only replay found mismatch",
                    "evidence_hash": "read-only-evidence-1",
                    "severity": "high",
                    "operator_id": "trust-admin:ops-1",
                },
                key_id="trust-admin:ops-1",
                shared_secret="trust-observer-secret",
            )
            self.assertEqual(dispute_status, 201)
            dispute_id = dispute_payload["dispute"]["id"]

            queue_status, queued = self._signed_post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue",
                "token-read-only-observe",
                {
                    "task_id": "read-only-observe-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa"},
                        {"action": "challengeJob", "raw_transaction": "0xbbbb"},
                    ],
                    "rpc_url": rpc.url,
                    "delay_seconds": 30,
                },
                key_id="settlement-admin:ops-1",
                shared_secret="settlement-observer-secret",
            )
            self.assertEqual(queue_status, 201)
            queue_item = queued["item"]

            relay_status, relay_payload = self._signed_post(
                f"{node.base_url}/v1/onchain/settlement-relay",
                "token-read-only-observe",
                {
                    "task_id": "read-only-observe-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xcccc"},
                        {"action": "challengeJob", "raw_transaction": "0xdddd"},
                    ],
                },
                key_id="settlement-admin:ops-1",
                shared_secret="settlement-observer-secret",
            )
            self.assertEqual(relay_status, 200)
            relay = relay_payload["relay"]

            denied_replay_status, denied_replay = self._get_auth(
                f"{node.base_url}/v1/tasks/replay-inspect?task_id=read-only-observe-task-1",
                "token-read-only-observe",
            )
            self.assertEqual(denied_replay_status, 401)
            self.assertEqual(denied_replay["policy_receipt"]["reason_code"], "signed-request-required")

            denied_disputes_status, denied_disputes = self._get_auth(
                f"{node.base_url}/v1/disputes?task_id=read-only-observe-task-1&status=open",
                "token-read-only-observe",
            )
            self.assertEqual(denied_disputes_status, 401)
            self.assertEqual(denied_disputes["policy_receipt"]["reason_code"], "signed-request-required")

            denied_latest_status, denied_latest = self._get_auth(
                f"{node.base_url}/v1/onchain/settlement-relays/latest?task_id=read-only-observe-task-1",
                "token-read-only-observe",
            )
            self.assertEqual(denied_latest_status, 401)
            self.assertEqual(denied_latest["policy_receipt"]["reason_code"], "signed-request-required")

            preview_status, preview = self._signed_get(
                f"{node.base_url}/v1/onchain/settlement-preview?task_id=read-only-observe-task-1",
                "token-read-only-observe",
                key_id="read-only:observer-1",
                shared_secret="read-only-observer-secret",
            )
            self.assertEqual(preview_status, 200)
            self.assertEqual(preview["settlement"]["open_dispute_count"], 1)
            self.assertEqual(preview["settlement"]["recommended_resolution"], "challengeJob")

            ledger_status, ledger_payload = self._signed_get(
                f"{node.base_url}/v1/onchain/settlement-ledger?task_id=read-only-observe-task-1",
                "token-read-only-observe",
                key_id="read-only:observer-1",
                shared_secret="read-only-observer-secret",
            )
            self.assertEqual(ledger_status, 200)
            ledger_verification = verify_document(
                ledger_payload["ledger"],
                secret="read-only-observe-secret",
                expected_scope="onchain-settlement-ledger",
                expected_key_id="read-only-observe-node",
            )
            self.assertTrue(ledger_verification["verified"])

            disputes_status, disputes = self._signed_get(
                f"{node.base_url}/v1/disputes?task_id=read-only-observe-task-1&status=open",
                "token-read-only-observe",
                key_id="read-only:observer-1",
                shared_secret="read-only-observer-secret",
            )
            self.assertEqual(disputes_status, 200)
            self.assertEqual(len(disputes["items"]), 1)
            self.assertEqual(disputes["items"][0]["id"], dispute_id)

            replay_status, replay = self._signed_get(
                f"{node.base_url}/v1/tasks/replay-inspect?task_id=read-only-observe-task-1",
                "token-read-only-observe",
                key_id="read-only:observer-1",
                shared_secret="read-only-observer-secret",
            )
            self.assertEqual(replay_status, 200)
            self.assertEqual(replay["task"]["id"], "read-only-observe-task-1")
            self.assertEqual(len(replay["disputes"]), 1)
            self.assertEqual(replay["disputes"][0]["id"], dispute_id)
            self.assertEqual(len(replay["settlement_relays"]), 1)
            self.assertEqual(len(replay["settlement_relay_queue"]), 1)
            self.assertEqual(replay["latest_settlement_relay"]["id"], relay["relay_record_id"])
            self.assertEqual(replay["settlement_reconciliation"]["status"], "unknown")

            relay_history_status, relay_history = self._signed_get(
                f"{node.base_url}/v1/onchain/settlement-relays?task_id=read-only-observe-task-1",
                "token-read-only-observe",
                key_id="read-only:observer-1",
                shared_secret="read-only-observer-secret",
            )
            self.assertEqual(relay_history_status, 200)
            self.assertEqual(len(relay_history["items"]), 1)
            self.assertEqual(relay_history["items"][0]["id"], relay["relay_record_id"])

            queue_view_status, queue_view = self._signed_get(
                f"{node.base_url}/v1/onchain/settlement-relay-queue?task_id=read-only-observe-task-1",
                "token-read-only-observe",
                key_id="read-only:observer-1",
                shared_secret="read-only-observer-secret",
            )
            self.assertEqual(queue_view_status, 200)
            self.assertEqual(len(queue_view["items"]), 1)
            self.assertEqual(queue_view["items"][0]["id"], queue_item["id"])

            latest_status, latest = self._signed_get(
                f"{node.base_url}/v1/onchain/settlement-relays/latest?task_id=read-only-observe-task-1",
                "token-read-only-observe",
                key_id="read-only:observer-1",
                shared_secret="read-only-observer-secret",
            )
            self.assertEqual(latest_status, 200)
            self.assertEqual(latest["id"], relay["relay_record_id"])

            inherited_replay_status, inherited_replay = self._signed_get(
                f"{node.base_url}/v1/tasks/replay-inspect?task_id=read-only-observe-task-1",
                "token-read-only-observe",
                key_id="settlement-admin:ops-1",
                shared_secret="settlement-observer-secret",
            )
            self.assertEqual(inherited_replay_status, 200)
            self.assertEqual(inherited_replay["task"]["id"], "read-only-observe-task-1")

            denied_pause_status, denied_pause = self._signed_post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue/pause",
                "token-read-only-observe",
                {"queue_id": queue_item["id"]},
                key_id="read-only:observer-1",
                shared_secret="read-only-observer-secret",
            )
            self.assertEqual(denied_pause_status, 403)
            self.assertEqual(denied_pause["policy_receipt"]["reason_code"], "scope-denied")

            replay_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/tasks/replay-inspect", limit=10)
            self.assertEqual([item["decision"] for item in replay_audits[:3]], ["allowed", "allowed", "denied"])
            self.assertEqual(
                {item["key_id"] for item in replay_audits[:2]},
                {"read-only:observer-1", "settlement-admin:ops-1"},
            )

            latest_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/onchain/settlement-relays/latest", limit=10)
            self.assertEqual([item["decision"] for item in latest_audits[:2]], ["allowed", "denied"])
            self.assertEqual(latest_audits[0]["key_id"], "read-only:observer-1")
            self.assertEqual(latest_audits[1]["payload"]["policy_receipt"]["reason_code"], "signed-request-required")
        finally:
            node.stop()
            rpc.stop()

    def test_signed_operator_request_is_required_for_read_only_governance_observability(self) -> None:
        node = NodeHarness(
            node_id="read-only-governance-node",
            token="token-read-only-governance",
            db_path=str(Path(self.tempdir.name) / "read-only-governance.db"),
            capabilities=["worker"],
            signing_secret="read-only-governance-secret",
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="read-only:observer-1",
                    shared_secret="read-only-governance-observer-secret",
                    scopes=["read-only"],
                ),
                OperatorIdentityConfig(
                    key_id="trust-admin:ops-1",
                    shared_secret="trust-governance-secret",
                    scopes=["trust-admin"],
                ),
            ],
        )
        node.start()
        try:
            violation = node.node.store.record_policy_violation(
                actor_id="worker-governance-1",
                actor_type="worker",
                source="adapter-policy",
                reason="tool is not allowlisted",
                severity="medium",
                task_id="governance-observe-task-1",
                payload={"tool": "forbidden-tool"},
            )
            self.assertEqual(violation["actor_id"], "worker-governance-1")

            quarantine_status, quarantined = self._signed_post(
                f"{node.base_url}/v1/quarantines",
                "token-read-only-governance",
                {
                    "actor_id": "worker-governance-1",
                    "actor_type": "worker",
                    "operator_id": "trust-admin:ops-1",
                    "scope": "task-claim",
                    "reason": "manual governance hold for inspection",
                    "payload": {"ticket": "GOV-201"},
                },
                key_id="trust-admin:ops-1",
                shared_secret="trust-governance-secret",
            )
            self.assertEqual(quarantine_status, 200)
            self.assertTrue(quarantined["quarantined"])
            self.assertEqual(quarantined["action"]["operator_id"], "trust-admin:ops-1")

            denied_reputation_status, denied_reputation = self._get_auth(
                f"{node.base_url}/v1/reputation?actor_id=worker-governance-1",
                "token-read-only-governance",
            )
            self.assertEqual(denied_reputation_status, 401)
            self.assertEqual(denied_reputation["policy_receipt"]["reason_code"], "signed-request-required")

            denied_violations_status, denied_violations = self._get_auth(
                f"{node.base_url}/v1/violations?actor_id=worker-governance-1",
                "token-read-only-governance",
            )
            self.assertEqual(denied_violations_status, 401)
            self.assertEqual(denied_violations["policy_receipt"]["reason_code"], "signed-request-required")

            denied_quarantines_status, denied_quarantines = self._get_auth(
                f"{node.base_url}/v1/quarantines?actor_id=worker-governance-1",
                "token-read-only-governance",
            )
            self.assertEqual(denied_quarantines_status, 401)
            self.assertEqual(denied_quarantines["policy_receipt"]["reason_code"], "signed-request-required")

            denied_actions_status, denied_actions = self._get_auth(
                f"{node.base_url}/v1/governance-actions?actor_id=worker-governance-1",
                "token-read-only-governance",
            )
            self.assertEqual(denied_actions_status, 401)
            self.assertEqual(denied_actions["policy_receipt"]["reason_code"], "signed-request-required")

            reputation_status, reputation = self._signed_get(
                f"{node.base_url}/v1/reputation?actor_id=worker-governance-1",
                "token-read-only-governance",
                key_id="read-only:observer-1",
                shared_secret="read-only-governance-observer-secret",
            )
            self.assertEqual(reputation_status, 200)
            self.assertEqual(reputation["violations"], 1)
            self.assertEqual(reputation["score"], 85)
            self.assertTrue(reputation["quarantined"])

            violations_status, violations = self._signed_get(
                f"{node.base_url}/v1/violations?actor_id=worker-governance-1",
                "token-read-only-governance",
                key_id="read-only:observer-1",
                shared_secret="read-only-governance-observer-secret",
            )
            self.assertEqual(violations_status, 200)
            self.assertEqual(len(violations["items"]), 1)
            self.assertEqual(violations["items"][0]["reason"], "tool is not allowlisted")

            quarantines_status, quarantines = self._signed_get(
                f"{node.base_url}/v1/quarantines?actor_id=worker-governance-1",
                "token-read-only-governance",
                key_id="read-only:observer-1",
                shared_secret="read-only-governance-observer-secret",
            )
            self.assertEqual(quarantines_status, 200)
            self.assertEqual(len(quarantines["items"]), 1)
            self.assertTrue(quarantines["items"][0]["active"])

            actions_status, actions = self._signed_get(
                f"{node.base_url}/v1/governance-actions?actor_id=worker-governance-1",
                "token-read-only-governance",
                key_id="read-only:observer-1",
                shared_secret="read-only-governance-observer-secret",
            )
            self.assertEqual(actions_status, 200)
            self.assertEqual(len(actions["items"]), 1)
            self.assertEqual(actions["items"][0]["action_type"], "quarantine-set")
            self.assertEqual(actions["items"][0]["operator_id"], "trust-admin:ops-1")

            inherited_actions_status, inherited_actions = self._signed_get(
                f"{node.base_url}/v1/governance-actions?actor_id=worker-governance-1",
                "token-read-only-governance",
                key_id="trust-admin:ops-1",
                shared_secret="trust-governance-secret",
            )
            self.assertEqual(inherited_actions_status, 200)
            self.assertEqual(len(inherited_actions["items"]), 1)

            denied_release_status, denied_release = self._signed_post(
                f"{node.base_url}/v1/quarantines/release",
                "token-read-only-governance",
                {
                    "actor_id": "worker-governance-1",
                    "actor_type": "worker",
                    "reason": "observer cannot release quarantine",
                },
                key_id="read-only:observer-1",
                shared_secret="read-only-governance-observer-secret",
            )
            self.assertEqual(denied_release_status, 403)
            self.assertEqual(denied_release["policy_receipt"]["reason_code"], "scope-denied")

            reputation_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/reputation", limit=10)
            self.assertEqual([item["decision"] for item in reputation_audits[:2]], ["allowed", "denied"])
            self.assertEqual(reputation_audits[0]["key_id"], "read-only:observer-1")
            self.assertEqual(reputation_audits[1]["payload"]["policy_receipt"]["reason_code"], "signed-request-required")

            actions_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/governance-actions", limit=10)
            self.assertEqual([item["decision"] for item in actions_audits[:3]], ["allowed", "allowed", "denied"])
            self.assertEqual(
                {item["key_id"] for item in actions_audits[:2]},
                {"read-only:observer-1", "trust-admin:ops-1"},
            )

            release_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/quarantines/release", limit=10)
            self.assertEqual(release_audits[0]["decision"], "denied")
            self.assertEqual(release_audits[0]["payload"]["policy_receipt"]["reason_code"], "scope-denied")
        finally:
            node.stop()

    def test_signed_operator_request_is_required_for_read_only_operational_observability(self) -> None:
        bad_peer = PeerConfig(peer_id="ops-peer-bad", name="Ops Bad Peer", url="http://127.0.0.1:19999", auth_token="token-bad")
        node = NodeHarness(
            node_id="read-only-ops-node",
            token="token-read-only-ops",
            db_path=str(Path(self.tempdir.name) / "read-only-ops.db"),
            capabilities=["planner", "worker"],
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="read-only:observer-1",
                    shared_secret="read-only-ops-observer-secret",
                    scopes=["read-only"],
                ),
                OperatorIdentityConfig(
                    key_id="workflow-admin:ops-1",
                    shared_secret="workflow-ops-secret",
                    scopes=["workflow-admin"],
                ),
            ],
            peers=[bad_peer],
            local_dispatch_fallback=False,
            outbox_max_attempts=1,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-read-only-ops",
                {"id": "ops-audit-task-1", "kind": "generic", "role": "worker", "payload": {}},
            )
            self._complete_onchain_task(node, "token-read-only-ops", "ops-audit-task-1", "worker-read-only-ops-1")

            sync_status, sync_payload = self._post(f"{node.base_url}/v1/peers/sync", "token-read-only-ops", {})
            self.assertEqual(sync_status, 200)
            self.assertEqual(sync_payload["items"][0]["peer_id"], "ops-peer-bad")
            self.assertEqual(sync_payload["items"][0]["status"], "error")

            self._post(
                f"{node.base_url}/v1/tasks",
                "token-read-only-ops",
                {"id": "ops-root-workflow", "kind": "plan", "role": "planner", "payload": {}},
            )
            self._post(
                f"{node.base_url}/v1/tasks/dispatch",
                "token-read-only-ops",
                {
                    "id": "ops-remote-dead",
                    "kind": "code",
                    "deliver_to": "ops-peer-bad",
                    "required_capabilities": ["worker"],
                },
            )
            flush_status, flushed = self._post(f"{node.base_url}/v1/outbox/flush", "token-read-only-ops", {})
            self.assertEqual(flush_status, 200)
            self.assertEqual(flushed["flushed"], 0)

            denied_audits_status, denied_audits = self._get_auth(
                f"{node.base_url}/v1/audits?task_id=ops-audit-task-1",
                "token-read-only-ops",
            )
            self.assertEqual(denied_audits_status, 401)
            self.assertEqual(denied_audits["policy_receipt"]["reason_code"], "signed-request-required")

            denied_health_status, denied_health = self._get_auth(
                f"{node.base_url}/v1/peer-health?peer_id=ops-peer-bad",
                "token-read-only-ops",
            )
            self.assertEqual(denied_health_status, 401)
            self.assertEqual(denied_health["policy_receipt"]["reason_code"], "signed-request-required")

            denied_outbox_status, denied_outbox = self._get_auth(
                f"{node.base_url}/v1/outbox",
                "token-read-only-ops",
            )
            self.assertEqual(denied_outbox_status, 401)
            self.assertEqual(denied_outbox["policy_receipt"]["reason_code"], "signed-request-required")

            denied_dead_letter_status, denied_dead_letter = self._get_auth(
                f"{node.base_url}/v1/outbox/dead-letter",
                "token-read-only-ops",
            )
            self.assertEqual(denied_dead_letter_status, 401)
            self.assertEqual(denied_dead_letter["policy_receipt"]["reason_code"], "signed-request-required")

            audits_status, audits = self._signed_get(
                f"{node.base_url}/v1/audits?task_id=ops-audit-task-1",
                "token-read-only-ops",
                key_id="read-only:observer-1",
                shared_secret="read-only-ops-observer-secret",
            )
            self.assertEqual(audits_status, 200)
            self.assertEqual(len(audits["items"]), 1)
            self.assertEqual(audits["items"][0]["task_id"], "ops-audit-task-1")
            self.assertEqual(audits["items"][0]["status"], "completed")

            health_status, health = self._signed_get(
                f"{node.base_url}/v1/peer-health?peer_id=ops-peer-bad",
                "token-read-only-ops",
                key_id="read-only:observer-1",
                shared_secret="read-only-ops-observer-secret",
            )
            self.assertEqual(health_status, 200)
            self.assertGreaterEqual(int(health["sync_failures"] or 0), 1)
            self.assertGreaterEqual(int(health["delivery_failures"] or 0), 1)
            self.assertTrue(health["dispatch_blocked"]["cooldown"])

            outbox_status, outbox = self._signed_get(
                f"{node.base_url}/v1/outbox",
                "token-read-only-ops",
                key_id="read-only:observer-1",
                shared_secret="read-only-ops-observer-secret",
            )
            self.assertEqual(outbox_status, 200)
            self.assertEqual(len(outbox["items"]), 1)
            self.assertEqual(outbox["items"][0]["task_id"], "ops-remote-dead")
            self.assertEqual(outbox["items"][0]["status"], "dead-letter")

            dead_letter_status, dead_letter = self._signed_get(
                f"{node.base_url}/v1/outbox/dead-letter",
                "token-read-only-ops",
                key_id="read-only:observer-1",
                shared_secret="read-only-ops-observer-secret",
            )
            self.assertEqual(dead_letter_status, 200)
            self.assertEqual(len(dead_letter["items"]), 1)
            self.assertEqual(dead_letter["items"][0]["task_id"], "ops-remote-dead")
            self.assertEqual(dead_letter["items"][0]["status"], "dead-letter")

            inherited_outbox_status, inherited_outbox = self._signed_get(
                f"{node.base_url}/v1/outbox",
                "token-read-only-ops",
                key_id="workflow-admin:ops-1",
                shared_secret="workflow-ops-secret",
            )
            self.assertEqual(inherited_outbox_status, 200)
            self.assertEqual(len(inherited_outbox["items"]), 1)

            denied_fanout_status, denied_fanout = self._signed_post(
                f"{node.base_url}/v1/workflows/fanout",
                "token-read-only-ops",
                {
                    "parent_task_id": "ops-root-workflow",
                    "subtasks": [{"id": "ops-child-1", "kind": "code", "role": "worker"}],
                },
                key_id="read-only:observer-1",
                shared_secret="read-only-ops-observer-secret",
            )
            self.assertEqual(denied_fanout_status, 403)
            self.assertEqual(denied_fanout["policy_receipt"]["reason_code"], "scope-denied")

            audits_auth = node.node.store.list_operator_auth_audits(endpoint="/v1/audits", limit=10)
            self.assertEqual([item["decision"] for item in audits_auth[:2]], ["allowed", "denied"])
            self.assertEqual(audits_auth[0]["key_id"], "read-only:observer-1")
            self.assertEqual(audits_auth[1]["payload"]["policy_receipt"]["reason_code"], "signed-request-required")

            outbox_auth = node.node.store.list_operator_auth_audits(endpoint="/v1/outbox", limit=10)
            self.assertEqual([item["decision"] for item in outbox_auth[:3]], ["allowed", "allowed", "denied"])
            self.assertEqual(
                {item["key_id"] for item in outbox_auth[:2]},
                {"read-only:observer-1", "workflow-admin:ops-1"},
            )

            fanout_auth = node.node.store.list_operator_auth_audits(endpoint="/v1/workflows/fanout", limit=10)
            self.assertEqual(fanout_auth[0]["decision"], "denied")
            self.assertEqual(fanout_auth[0]["payload"]["policy_receipt"]["reason_code"], "scope-denied")
        finally:
            node.stop()

    def test_signed_operator_request_is_required_for_git_observability(self) -> None:
        repo_path = Path(self.tempdir.name) / "git-auth-repo"
        self._init_git_repo(repo_path)
        (repo_path / "README.txt").write_text("hello\nchange\n", encoding="utf-8")

        node = NodeHarness(
            node_id="read-only-git-node",
            token="token-read-only-git",
            db_path=str(Path(self.tempdir.name) / "read-only-git.db"),
            capabilities=["planner", "worker"],
            git_root=str(repo_path),
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="read-only:observer-1",
                    shared_secret="read-only-git-observer-secret",
                    scopes=["read-only"],
                ),
                OperatorIdentityConfig(
                    key_id="workflow-admin:ops-1",
                    shared_secret="workflow-git-secret",
                    scopes=["workflow-admin"],
                ),
            ],
        )
        node.start()
        try:
            denied_status_status, denied_status = self._get_auth(
                f"{node.base_url}/v1/git/status",
                "token-read-only-git",
            )
            self.assertEqual(denied_status_status, 401)
            self.assertEqual(denied_status["policy_receipt"]["reason_code"], "signed-request-required")

            denied_diff_status, denied_diff = self._get_auth(
                f"{node.base_url}/v1/git/diff?base_ref=HEAD&name_only=1",
                "token-read-only-git",
            )
            self.assertEqual(denied_diff_status, 401)
            self.assertEqual(denied_diff["policy_receipt"]["reason_code"], "signed-request-required")

            status_status, status_payload = self._signed_get(
                f"{node.base_url}/v1/git/status",
                "token-read-only-git",
                key_id="read-only:observer-1",
                shared_secret="read-only-git-observer-secret",
            )
            self.assertEqual(status_status, 200)
            self.assertTrue(status_payload["is_dirty"])
            tracked = (
                set(status_payload["staged_files"])
                | set(status_payload["unstaged_files"])
                | set(status_payload["untracked_files"])
            )
            self.assertIn("README.txt", tracked)

            diff_status, diff_payload = self._signed_get(
                f"{node.base_url}/v1/git/diff?base_ref=HEAD&name_only=1",
                "token-read-only-git",
                key_id="read-only:observer-1",
                shared_secret="read-only-git-observer-secret",
            )
            self.assertEqual(diff_status, 200)
            self.assertIn("README.txt", diff_payload["files"])

            inherited_status, inherited_payload = self._signed_get(
                f"{node.base_url}/v1/git/status",
                "token-read-only-git",
                key_id="workflow-admin:ops-1",
                shared_secret="workflow-git-secret",
            )
            self.assertEqual(inherited_status, 200)
            self.assertTrue(inherited_payload["is_dirty"])

            status_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/git/status", limit=10)
            self.assertEqual([item["decision"] for item in status_audits[:3]], ["allowed", "allowed", "denied"])
            self.assertEqual(
                {item["key_id"] for item in status_audits[:2]},
                {"read-only:observer-1", "workflow-admin:ops-1"},
            )
            self.assertEqual(status_audits[2]["payload"]["policy_receipt"]["reason_code"], "signed-request-required")

            diff_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/git/diff", limit=10)
            self.assertEqual([item["decision"] for item in diff_audits[:2]], ["allowed", "denied"])
            self.assertEqual(diff_audits[0]["key_id"], "read-only:observer-1")
            self.assertEqual(diff_audits[1]["payload"]["policy_receipt"]["reason_code"], "signed-request-required")
        finally:
            node.stop()

    def test_signed_operator_request_is_required_for_dispatch_preview_and_poaw_observability(self) -> None:
        node = NodeHarness(
            node_id="read-only-poaw-node",
            token="token-read-only-poaw",
            db_path=str(Path(self.tempdir.name) / "read-only-poaw.db"),
            capabilities=["planner", "worker", "reviewer"],
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="read-only:observer-1",
                    shared_secret="read-only-poaw-observer-secret",
                    scopes=["read-only"],
                ),
                OperatorIdentityConfig(
                    key_id="workflow-admin:ops-1",
                    shared_secret="workflow-poaw-secret",
                    scopes=["workflow-admin"],
                ),
            ],
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-read-only-poaw",
                {"id": "poaw-task-1", "kind": "generic", "role": "worker", "payload": {"goal": "observe"}},
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-read-only-poaw",
                {"worker_id": "worker-poaw-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-read-only-poaw",
                {
                    "task_id": "poaw-task-1",
                    "worker_id": "worker-poaw-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True},
                },
            )

            denied_preview_status, denied_preview = self._get_auth(
                f"{node.base_url}/v1/tasks/dispatch/preview?required_capabilities=worker",
                "token-read-only-poaw",
            )
            self.assertEqual(denied_preview_status, 401)
            self.assertEqual(denied_preview["policy_receipt"]["reason_code"], "signed-request-required")

            denied_events_status, denied_events = self._get_auth(
                f"{node.base_url}/v1/poaw/events?task_id=poaw-task-1",
                "token-read-only-poaw",
            )
            self.assertEqual(denied_events_status, 401)
            self.assertEqual(denied_events["policy_receipt"]["reason_code"], "signed-request-required")

            denied_summary_status, denied_summary = self._get_auth(
                f"{node.base_url}/v1/poaw/summary?task_id=poaw-task-1",
                "token-read-only-poaw",
            )
            self.assertEqual(denied_summary_status, 401)
            self.assertEqual(denied_summary["policy_receipt"]["reason_code"], "signed-request-required")

            preview_status, preview = self._signed_get(
                f"{node.base_url}/v1/tasks/dispatch/preview?required_capabilities=worker",
                "token-read-only-poaw",
                key_id="read-only:observer-1",
                shared_secret="read-only-poaw-observer-secret",
            )
            self.assertEqual(preview_status, 200)
            self.assertEqual(preview["required_capabilities"], ["worker"])
            self.assertGreaterEqual(len(preview["candidates"]), 1)

            events_status, events = self._signed_get(
                f"{node.base_url}/v1/poaw/events?task_id=poaw-task-1",
                "token-read-only-poaw",
                key_id="read-only:observer-1",
                shared_secret="read-only-poaw-observer-secret",
            )
            self.assertEqual(events_status, 200)
            self.assertGreaterEqual(len(events["items"]), 1)
            self.assertEqual(events["items"][0]["task_id"], "poaw-task-1")

            summary_status, summary = self._signed_get(
                f"{node.base_url}/v1/poaw/summary?task_id=poaw-task-1",
                "token-read-only-poaw",
                key_id="read-only:observer-1",
                shared_secret="read-only-poaw-observer-secret",
            )
            self.assertEqual(summary_status, 200)
            self.assertEqual(summary["task_id"], "poaw-task-1")
            self.assertGreaterEqual(int(summary["total_points"] or 0), 1)

            inherited_summary_status, inherited_summary = self._signed_get(
                f"{node.base_url}/v1/poaw/summary?task_id=poaw-task-1",
                "token-read-only-poaw",
                key_id="workflow-admin:ops-1",
                shared_secret="workflow-poaw-secret",
            )
            self.assertEqual(inherited_summary_status, 200)
            self.assertEqual(inherited_summary["task_id"], "poaw-task-1")

            preview_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/tasks/dispatch/preview", limit=10)
            self.assertEqual([item["decision"] for item in preview_audits[:2]], ["allowed", "denied"])
            self.assertEqual(preview_audits[0]["key_id"], "read-only:observer-1")
            self.assertEqual(preview_audits[1]["payload"]["policy_receipt"]["reason_code"], "signed-request-required")

            events_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/poaw/events", limit=10)
            self.assertEqual([item["decision"] for item in events_audits[:2]], ["allowed", "denied"])
            self.assertEqual(events_audits[0]["key_id"], "read-only:observer-1")
            self.assertEqual(events_audits[1]["payload"]["policy_receipt"]["reason_code"], "signed-request-required")

            summary_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/poaw/summary", limit=10)
            self.assertEqual([item["decision"] for item in summary_audits[:3]], ["allowed", "allowed", "denied"])
            self.assertEqual(
                {item["key_id"] for item in summary_audits[:2]},
                {"read-only:observer-1", "workflow-admin:ops-1"},
            )
            self.assertEqual(summary_audits[2]["payload"]["policy_receipt"]["reason_code"], "signed-request-required")
        finally:
            node.stop()

    def test_scoped_bearer_token_can_access_read_only_observability_on_loopback(self) -> None:
        node = NodeHarness(
            node_id="scoped-bearer-read-only-node",
            token="token-scoped-bearer-read-only",
            db_path=str(Path(self.tempdir.name) / "scoped-bearer-read-only.db"),
            capabilities=["planner", "worker"],
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="workflow-admin:ops-1",
                    shared_secret="workflow-admin-secret",
                    scopes=["workflow-admin"],
                ),
            ],
            scoped_bearer_tokens=[
                ScopedBearerTokenConfig(
                    token_id="bearer:observer-1",
                    token="read-only-bearer-token",
                    scopes=["read-only"],
                    source_restrictions=["loopback-only"],
                ),
            ],
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-scoped-bearer-read-only",
                {"id": "scoped-bearer-poaw-task", "kind": "generic", "role": "worker", "payload": {"goal": "observe"}},
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-scoped-bearer-read-only",
                {"worker_id": "worker-scoped-bearer", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-scoped-bearer-read-only",
                {
                    "task_id": "scoped-bearer-poaw-task",
                    "worker_id": "worker-scoped-bearer",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True},
                },
            )

            summary_status, summary = self._get_auth(
                f"{node.base_url}/v1/poaw/summary?task_id=scoped-bearer-poaw-task",
                "read-only-bearer-token",
            )
            self.assertEqual(summary_status, 200)
            self.assertEqual(summary["task_id"], "scoped-bearer-poaw-task")
            self.assertGreaterEqual(int(summary["total_points"] or 0), 1)

            preview_status, preview = self._get_auth(
                f"{node.base_url}/v1/tasks/dispatch/preview?required_capabilities=worker",
                "read-only-bearer-token",
            )
            self.assertEqual(preview_status, 200)
            self.assertEqual(preview["required_capabilities"], ["worker"])

            denied_fanout_status, denied_fanout = self._post(
                f"{node.base_url}/v1/workflows/fanout",
                "read-only-bearer-token",
                {"parent_task_id": "missing-parent", "subtasks": [{"id": "child-x", "kind": "code", "role": "worker"}]},
            )
            self.assertEqual(denied_fanout_status, 403)
            self.assertEqual(denied_fanout["policy_receipt"]["reason_code"], "scope-denied")

            summary_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/poaw/summary", limit=10)
            self.assertEqual(summary_audits[0]["decision"], "allowed")
            self.assertEqual(summary_audits[0]["key_id"], "bearer:observer-1")
            self.assertEqual(summary_audits[0]["auth_mode"], "scoped-bearer")
            self.assertTrue(summary_audits[0]["payload"]["downgraded"])

            fanout_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/workflows/fanout", limit=10)
            self.assertEqual(fanout_audits[0]["decision"], "denied")
            self.assertEqual(fanout_audits[0]["key_id"], "bearer:observer-1")
            self.assertEqual(fanout_audits[0]["payload"]["policy_receipt"]["reason_code"], "scope-denied")
        finally:
            node.stop()

    def test_scoped_bearer_token_can_access_matching_workflow_admin_scope_on_loopback(self) -> None:
        node = NodeHarness(
            node_id="scoped-bearer-workflow-node",
            token="token-scoped-bearer-workflow",
            db_path=str(Path(self.tempdir.name) / "scoped-bearer-workflow.db"),
            capabilities=["planner", "worker"],
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="workflow-admin:ops-1",
                    shared_secret="workflow-admin-secret",
                    scopes=["workflow-admin"],
                ),
            ],
            scoped_bearer_tokens=[
                ScopedBearerTokenConfig(
                    token_id="bearer:workflow-1",
                    token="workflow-admin-bearer-token",
                    scopes=["workflow-admin"],
                    source_restrictions=["loopback-only"],
                ),
            ],
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-scoped-bearer-workflow",
                {"id": "scoped-bearer-root", "kind": "plan", "role": "planner", "payload": {}},
            )

            fanout_status, fanout = self._post(
                f"{node.base_url}/v1/workflows/fanout",
                "workflow-admin-bearer-token",
                {
                    "parent_task_id": "scoped-bearer-root",
                    "subtasks": [{"id": "scoped-bearer-child", "kind": "code", "role": "worker"}],
                },
            )
            self.assertEqual(fanout_status, 201)
            self.assertEqual(fanout["action"]["action_type"], "workflow-fanout")
            self.assertEqual(fanout["action"]["operator_id"], "bearer:workflow-1")
            self.assertEqual(len(fanout["items"]), 1)
            self.assertEqual(fanout["items"][0]["id"], "scoped-bearer-child")

            denied_bridge_status, denied_bridge = self._post(
                f"{node.base_url}/v1/bridges/import",
                "workflow-admin-bearer-token",
                {
                    "protocol": "mcp",
                    "message": {
                        "id": "scoped-bearer-bridge-denied-1",
                        "method": "tools/call",
                        "params": {"name": "reviewer", "arguments": {"path": "README.md"}},
                        "sender": "bridge-client",
                    },
                    "task_overrides": {"id": "scoped-bearer-bridge-denied-task", "role": "worker"},
                },
            )
            self.assertEqual(denied_bridge_status, 403)
            self.assertEqual(denied_bridge["policy_receipt"]["reason_code"], "scope-denied")

            fanout_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/workflows/fanout", limit=10)
            self.assertEqual(fanout_audits[0]["decision"], "allowed")
            self.assertEqual(fanout_audits[0]["key_id"], "bearer:workflow-1")
            self.assertEqual(fanout_audits[0]["auth_mode"], "scoped-bearer")

            bridge_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/bridges/import", limit=10)
            self.assertEqual(bridge_audits[0]["decision"], "denied")
            self.assertEqual(bridge_audits[0]["key_id"], "bearer:workflow-1")
            self.assertEqual(bridge_audits[0]["payload"]["policy_receipt"]["reason_code"], "scope-denied")
        finally:
            node.stop()

    def test_shared_bearer_remains_accepted_for_local_admin_endpoints_on_loopback(self) -> None:
        repo_path = Path(self.tempdir.name) / "local-admin-shared-repo"
        self._init_git_repo(repo_path)
        (repo_path / "README.txt").write_text("hello\nchange\n", encoding="utf-8")

        node = NodeHarness(
            node_id="local-admin-shared-bearer-node",
            token="token-local-admin-shared",
            db_path=str(Path(self.tempdir.name) / "local-admin-shared.db"),
            capabilities=["planner", "worker"],
            git_root=str(repo_path),
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="read-only:observer-1",
                    shared_secret="read-only-shared-local-secret",
                    scopes=["read-only"],
                ),
            ],
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-local-admin-shared",
                {
                    "id": "local-admin-dead-task",
                    "kind": "generic",
                    "role": "worker",
                    "payload": {},
                    "max_attempts": 1,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-local-admin-shared",
                {"worker_id": "worker-local-admin-shared", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-local-admin-shared",
                {
                    "task_id": "local-admin-dead-task",
                    "worker_id": "worker-local-admin-shared",
                    "lease_token": claim["task"]["lease_token"],
                    "success": False,
                    "error_message": "failed once",
                    "requeue": True,
                },
            )

            branch_status, branch_payload = self._post(
                f"{node.base_url}/v1/git/branch",
                "token-local-admin-shared",
                {"name": "agentcoin/local-admin-shared", "from_ref": "HEAD", "checkout": False},
            )
            self.assertEqual(branch_status, 201)
            self.assertEqual(branch_payload["branch"], "agentcoin/local-admin-shared")

            requeue_status, requeue_payload = self._post(
                f"{node.base_url}/v1/tasks/requeue",
                "token-local-admin-shared",
                {"task_id": "local-admin-dead-task", "delay_seconds": 0},
            )
            self.assertEqual(requeue_status, 200)
            self.assertTrue(requeue_payload["ok"])

            flush_status, flush_payload = self._post(
                f"{node.base_url}/v1/outbox/flush",
                "token-local-admin-shared",
                {},
            )
            self.assertEqual(flush_status, 200)
            self.assertIn("flushed", flush_payload)

            branch_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/git/branch", limit=10)
            self.assertEqual(branch_audits[0]["decision"], "allowed")
            self.assertEqual(branch_audits[0]["auth_mode"], "bearer-downgrade")
            self.assertTrue(branch_audits[0]["payload"]["downgraded"])

            requeue_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/tasks/requeue", limit=10)
            self.assertEqual(requeue_audits[0]["decision"], "allowed")
            self.assertEqual(requeue_audits[0]["auth_mode"], "bearer-downgrade")
        finally:
            node.stop()

    def test_local_admin_scoped_bearer_controls_tier1_endpoints(self) -> None:
        repo_path = Path(self.tempdir.name) / "local-admin-scoped-repo"
        self._init_git_repo(repo_path)
        (repo_path / "README.txt").write_text("hello\nchange\n", encoding="utf-8")

        node = NodeHarness(
            node_id="local-admin-scoped-bearer-node",
            token="token-local-admin-scoped",
            db_path=str(Path(self.tempdir.name) / "local-admin-scoped.db"),
            capabilities=["planner", "worker"],
            git_root=str(repo_path),
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="read-only:observer-1",
                    shared_secret="read-only-local-admin-secret",
                    scopes=["read-only"],
                ),
            ],
            scoped_bearer_tokens=[
                ScopedBearerTokenConfig(
                    token_id="bearer:local-admin-1",
                    token="local-admin-bearer-token",
                    scopes=["local-admin"],
                    source_restrictions=["loopback-only"],
                ),
                ScopedBearerTokenConfig(
                    token_id="bearer:observer-1",
                    token="read-only-local-token",
                    scopes=["read-only"],
                    source_restrictions=["loopback-only"],
                ),
            ],
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-local-admin-scoped",
                {
                    "id": "local-admin-scope-task",
                    "kind": "generic",
                    "role": "worker",
                    "payload": {},
                    "max_attempts": 1,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-local-admin-scoped",
                {"worker_id": "worker-local-admin-scope", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-local-admin-scoped",
                {
                    "task_id": "local-admin-scope-task",
                    "worker_id": "worker-local-admin-scope",
                    "lease_token": claim["task"]["lease_token"],
                    "success": False,
                    "error_message": "failed once",
                    "requeue": True,
                },
            )

            denied_branch_status, denied_branch = self._post(
                f"{node.base_url}/v1/git/branch",
                "read-only-local-token",
                {"name": "agentcoin/local-admin-denied", "from_ref": "HEAD", "checkout": False},
            )
            self.assertEqual(denied_branch_status, 403)
            self.assertEqual(denied_branch["policy_receipt"]["reason_code"], "scope-denied")

            branch_status, branch_payload = self._post(
                f"{node.base_url}/v1/git/branch",
                "local-admin-bearer-token",
                {"name": "agentcoin/local-admin-allowed", "from_ref": "HEAD", "checkout": False},
            )
            self.assertEqual(branch_status, 201)
            self.assertEqual(branch_payload["branch"], "agentcoin/local-admin-allowed")

            attached_status, attached = self._post(
                f"{node.base_url}/v1/git/task-context",
                "local-admin-bearer-token",
                {"task_id": "local-admin-scope-task", "base_ref": "HEAD"},
            )
            self.assertEqual(attached_status, 200)
            self.assertTrue(attached["updated"])

            requeue_status, requeue_payload = self._post(
                f"{node.base_url}/v1/tasks/requeue",
                "local-admin-bearer-token",
                {"task_id": "local-admin-scope-task", "delay_seconds": 0},
            )
            self.assertEqual(requeue_status, 200)
            self.assertTrue(requeue_payload["ok"])

            branch_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/git/branch", limit=10)
            self.assertEqual([item["decision"] for item in branch_audits[:2]], ["allowed", "denied"])
            self.assertEqual(branch_audits[0]["key_id"], "bearer:local-admin-1")
            self.assertEqual(branch_audits[0]["auth_mode"], "scoped-bearer")
            self.assertEqual(branch_audits[1]["key_id"], "bearer:observer-1")
            self.assertEqual(branch_audits[1]["payload"]["policy_receipt"]["reason_code"], "scope-denied")

            task_context_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/git/task-context", limit=10)
            self.assertEqual(task_context_audits[0]["decision"], "allowed")
            self.assertEqual(task_context_audits[0]["key_id"], "bearer:local-admin-1")

            requeue_audits = node.node.store.list_operator_auth_audits(endpoint="/v1/tasks/requeue", limit=10)
            self.assertEqual(requeue_audits[0]["decision"], "allowed")
            self.assertEqual(requeue_audits[0]["key_id"], "bearer:local-admin-1")
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
        main_branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(["git", "checkout", "-b", "feature/a"], cwd=repo_path, check=True, capture_output=True, text=True)
        (repo_path / "feature_a.txt").write_text("feature a\n", encoding="utf-8")
        subprocess.run(["git", "add", "feature_a.txt"], cwd=repo_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "feature a"], cwd=repo_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "checkout", main_branch], cwd=repo_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "checkout", "-b", "feature/b"], cwd=repo_path, check=True, capture_output=True, text=True)
        (repo_path / "feature_b.txt").write_text("feature b\n", encoding="utf-8")
        subprocess.run(["git", "add", "feature_b.txt"], cwd=repo_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "feature b"], cwd=repo_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "checkout", main_branch], cwd=repo_path, check=True, capture_output=True, text=True)
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
                    "workflow_id": "git-wf-1",
                    "payload": {"goal": "use git context"},
                    "attach_git_context": True,
                    "git_base_ref": main_branch,
                    "git_target_ref": "feature/a",
                },
            )
            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            git_task = [item for item in tasks["items"] if item["id"] == "git-task-1"][0]
            self.assertEqual(git_task["payload"]["_git"]["repo_root"], str(repo_path.resolve()))
            self.assertTrue(git_task["payload"]["_git"]["commit_sha"])
            self.assertTrue(git_task["payload"]["_git"]["diff_hash"])
            self.assertEqual(git_task["payload"]["_git"]["base_ref"], main_branch)
            self.assertEqual(git_task["payload"]["_git"]["target_ref"], "feature/a")
            self.assertIn("feature_a.txt", git_task["payload"]["_git"]["changed_files"])

            _, attached = self._post(
                f"{node.base_url}/v1/git/task-context",
                "token-g",
                {"task_id": "git-task-1", "base_ref": main_branch, "target_ref": "feature/a"},
            )
            self.assertTrue(attached["updated"])
            self.assertEqual(attached["task_id"], "git-task-1")

            self._post(
                f"{node.base_url}/v1/tasks",
                "token-g",
                {
                    "id": "git-task-2",
                    "kind": "code",
                    "workflow_id": "git-wf-1",
                    "payload": {"goal": "use second git context"},
                    "attach_git_context": True,
                    "git_base_ref": main_branch,
                    "git_target_ref": "feature/b",
                },
            )

            self._post(
                f"{node.base_url}/v1/workflows/review-gate",
                "token-g",
                {
                    "workflow_id": "git-wf-1",
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
            self.assertEqual(review_tasks["git-review-human"]["payload"]["_review"]["base_ref"], main_branch)
            self.assertEqual(review_tasks["git-review-human"]["payload"]["_review"]["head_ref"], "feature/a")
            self.assertTrue(review_tasks["git-review-human"]["payload"]["_review"]["head_sha"])

            _, merge_created = self._post(
                f"{node.base_url}/v1/workflows/merge",
                "token-g",
                {
                    "workflow_id": "git-wf-1",
                    "parent_task_ids": ["git-task-1", "git-task-2"],
                    "attach_git_context": True,
                    "git_base_ref": "feature/a",
                    "git_target_ref": "feature/b",
                    "task": {
                        "id": "git-merge-1",
                        "kind": "merge",
                        "role": "reviewer",
                        "branch": main_branch,
                    },
                },
            )
            self.assertEqual(merge_created["task"]["payload"]["_git"]["mergeability"]["base_ref"], "feature/a")
            self.assertEqual(merge_created["task"]["payload"]["_git"]["mergeability"]["target_ref"], "feature/b")
            self.assertIn("proof_bundle", merge_created["task"]["payload"]["_git"])

            _, replay = self._get(f"{node.base_url}/v1/tasks/replay-inspect?task_id=git-task-1")
            self.assertEqual(replay["git_proof_bundle"]["task"]["git"]["target_ref"], "feature/a")
            self.assertEqual(len(replay["git_proof_bundle"]["related_reviews"]), 2)
            self.assertEqual(replay["git_proof_bundle"]["merge_tasks"][0]["task_id"], "git-merge-1")
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
            self.assertEqual(imported["task"]["payload"]["_bridge"]["schema_version"], "0.1")
            self.assertEqual(imported["task"]["payload"]["_bridge"]["tool_call"]["tool_name"], "reviewer")
            self.assertEqual(imported["task"]["payload"]["_bridge"]["tool_call"]["arguments"]["path"], "README.md")
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
            self.assertEqual(exported["message"]["result"]["structuredContent"]["result"]["approved"], True)
            self.assertEqual(exported["message"]["result"]["_agentcoin"]["bridge"]["schema_version"], "0.1")
            self.assertEqual(exported["message"]["result"]["isError"], False)

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
            self.assertEqual(a2a_imported["task"]["payload"]["_bridge"]["schema_version"], "0.1")
            self.assertEqual(a2a_imported["task"]["payload"]["_bridge"]["message_envelope"]["intent"], "summarize")
            self.assertEqual(a2a_imported["task"]["payload"]["_bridge"]["message_envelope"]["content"]["text"], "hello world")

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
            self.assertEqual(a2a_exported["message"]["intent"], "task.result")
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
                by_id["bridge-exec-mcp"]["result"]["bridge_execution"]["tool_call"]["tool_name"],
                "tool-runner",
            )
            self.assertEqual(
                by_id["bridge-exec-mcp"]["result"]["bridge_execution"]["tool_result"]["structured_content"]["handled_by"],
                "worker-bridge-1",
            )
            self.assertEqual(
                by_id["bridge-exec-a2a"]["result"]["bridge_execution"]["normalized_output"]["content"]["accepted_intent"],
                "summarize",
            )
            self.assertEqual(
                by_id["bridge-exec-a2a"]["result"]["bridge_execution"]["message_envelope"]["intent"],
                "summarize",
            )
            self.assertEqual(
                by_id["bridge-exec-a2a"]["result"]["bridge_execution"]["message_result"]["intent"],
                "task.result",
            )

            _, exported = self._post(
                f"{node.base_url}/v1/bridges/export",
                "token-bridge-worker",
                {"protocol": "mcp", "task_id": "bridge-exec-mcp"},
            )
            self.assertEqual(exported["message"]["result"]["structuredContent"]["result"]["adapter"]["protocol"], "mcp")
            self.assertEqual(exported["message"]["result"]["content"][0]["data"]["tool_name"], "tool-runner")

            _, exported_a2a = self._post(
                f"{node.base_url}/v1/bridges/export",
                "token-bridge-worker",
                {"protocol": "a2a", "task_id": "bridge-exec-a2a"},
            )
            self.assertEqual(exported_a2a["message"]["task"]["result"]["adapter"]["protocol"], "a2a")
            self.assertEqual(exported_a2a["message"]["intent"], "task.result")
            self.assertEqual(exported_a2a["message"]["content"]["accepted_intent"], "summarize")
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
            self.assertEqual(applied["action"]["receipt"]["@type"], "agentcoin:GovernanceActionReceipt")
            self.assertEqual(applied["action"]["receipt"]["target"]["kind"], "actor-quarantine")
            self.assertEqual(applied["action"]["receipt"]["mutation"]["scope"], "task-claim")
            self.assertEqual(applied["action"]["receipt"]["reason_codes"], ["manual-quarantine", "scope-task-claim"])
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
            self.assertEqual(released["action"]["receipt"]["@type"], "agentcoin:GovernanceActionReceipt")
            self.assertEqual(released["action"]["receipt"]["mutation"]["quarantined"], False)
            self.assertEqual(released["action"]["receipt"]["reason_codes"], ["manual-release"])
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
            self.assertEqual(stored["result"]["execution_receipt"]["@type"], "agentcoin:DeterministicExecutionReceipt")
            self.assertEqual(stored["result"]["execution_receipt"]["schema_version"], "0.1")
            receipt = stored["result"]["_onchain_receipt"]
            self.assertEqual(receipt["@type"], "agentcoin:OnchainResultReceipt")
            self.assertEqual(receipt["schema_version"], "0.1")
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

            _, ledger_payload = self._get(f"{node.base_url}/v1/onchain/settlement-ledger?task_id=settlement-task-1")
            ledger = ledger_payload["ledger"]
            self.assertEqual(ledger["@type"], "agentcoin:SettlementLedgerReceipt")
            self.assertEqual(ledger["schema_version"], "0.1")
            self.assertEqual(ledger["settlement_summary"]["recommended_resolution"], "completeJob")
            self.assertEqual(ledger["commit_projection"]["current_actions"], ["submitWork", "completeJob"])
            self.assertIn("PoAWScorebook", ledger["commit_projection"]["future_contracts"])
            self.assertIn("ReputationEventLedger", ledger["commit_projection"]["future_contracts"])
            ledger_verification = verify_document(
                ledger,
                secret="settlement-secret",
                expected_scope="onchain-settlement-ledger",
                expected_key_id="onchain-settlement-node",
            )
            self.assertTrue(ledger_verification["verified"])

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
            self.assertEqual(replay["onchain_settlement_ledger"]["settlement_summary"]["recommended_resolution"], "slashJob")
            self.assertEqual(replay["onchain_settlement_ledger"]["violation_summary"]["count"], 1)
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
            challenge_bond_required_wei=7000000000000000,
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
            self.assertEqual(dispute_payload["dispute"]["bond_amount_wei"], "7000000000000000")
            self.assertEqual(dispute_payload["dispute"]["bond_status"], "locked")
            self.assertEqual(dispute_payload["action"]["receipt"]["@type"], "agentcoin:GovernanceActionReceipt")
            self.assertEqual(dispute_payload["action"]["receipt"]["target"]["dispute_id"], dispute_payload["dispute"]["id"])
            self.assertEqual(
                dispute_payload["action"]["receipt"]["reason_codes"],
                ["dispute-opened", "severity-high", "bond-required"],
            )
            self.assertEqual(dispute_payload["dispute"]["challenge_evidence"]["@type"], "agentcoin:ChallengeEvidence")
            self.assertEqual(dispute_payload["dispute"]["challenge_evidence"]["evidence_hash"], "evidence-hash-1")
            self.assertEqual(dispute_payload["dispute"]["contract_alignment"]["escrow"]["action"], "challengeJob")
            self.assertEqual(dispute_payload["dispute"]["contract_alignment"]["escrow"]["job_id"], 88)
            self.assertFalse(dispute_payload["dispute"]["contract_alignment"]["bond"]["supported_now"])
            self.assertEqual(
                dispute_payload["dispute"]["contract_alignment"]["bond"]["future_contract"],
                "ChallengeManager",
            )
            self.assertEqual(
                dispute_payload["dispute"]["contract_alignment"]["bond"]["projected_action"],
                "lockChallengerBond",
            )

            _, disputes = self._get(f"{node.base_url}/v1/disputes?task_id=challenge-task-1&status=open")
            self.assertEqual(len(disputes["items"]), 1)
            self.assertEqual(disputes["items"][0]["challenger_id"], "reviewer-challenge-1")
            self.assertEqual(disputes["items"][0]["bond_amount_wei"], "7000000000000000")
            self.assertEqual(disputes["items"][0]["challenge_evidence"]["@type"], "agentcoin:ChallengeEvidence")
            self.assertEqual(disputes["items"][0]["contract_alignment"]["escrow"]["projected_job_status"], "Challenged")

            _, preview = self._get(f"{node.base_url}/v1/onchain/settlement-preview?task_id=challenge-task-1")
            settlement = preview["settlement"]
            self.assertEqual(settlement["recommended_sequence"], ["submitWork", "challengeJob"])
            self.assertEqual(settlement["recommended_resolution"], "challengeJob")
            self.assertEqual(settlement["open_dispute_count"], 1)
            self.assertEqual(settlement["intents"][1]["function"], "challengeJob")
            self.assertTrue(settlement["intents"][1]["args"]["evidenceHash"].startswith("0x"))
            self.assertEqual(len(settlement["intents"][1]["args"]["evidenceHash"]), 66)
            self.assertEqual(settlement["resolution_params"]["challenge_evidence"]["@type"], "agentcoin:ChallengeEvidence")

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
            self.assertEqual(resolved["dispute"]["bond_status"], "slashed")
            self.assertEqual(resolved["dispute"]["resolution"]["receipt"]["@type"], "agentcoin:GovernanceActionReceipt")
            self.assertEqual(
                resolved["dispute"]["resolution"]["receipt"]["reason_codes"],
                ["dispute-resolved", "resolution-dismissed", "operator-resolution"],
            )
            self.assertEqual(
                resolved["dispute"]["resolution"]["receipt"]["target"]["dispute_id"],
                disputes["items"][0]["id"],
            )
            self.assertEqual(resolved["dispute"]["contract_alignment"]["escrow"]["action"], "completeJob")
            self.assertEqual(
                resolved["dispute"]["contract_alignment"]["bond"]["projected_action"],
                "slashChallengerBond",
            )
            dismissal_verification = verify_document(
                resolved["dispute"]["resolution"]["receipt"],
                secret="challenge-secret",
                expected_scope="governance-receipt",
                expected_key_id="challenge-node",
            )
            self.assertTrue(dismissal_verification["verified"])

            _, preview_after_dismiss = self._get(f"{node.base_url}/v1/onchain/settlement-preview?task_id=challenge-task-1")
            self.assertEqual(preview_after_dismiss["settlement"]["recommended_resolution"], "completeJob")
            self.assertEqual(preview_after_dismiss["settlement"]["dismissed_dispute_count"], 1)

            dispute_status_2, dispute_payload_2 = self._post(
                f"{node.base_url}/v1/disputes",
                "token-challenge",
                {
                    "task_id": "challenge-task-1",
                    "challenger_id": "reviewer-challenge-2",
                    "actor_id": "worker-challenge-1",
                    "actor_type": "worker",
                    "reason": "re-run confirmed defect",
                    "evidence_hash": "evidence-hash-2",
                    "severity": "high",
                },
            )
            self.assertEqual(dispute_status_2, 201)
            resolve_status_2, resolved_2 = self._post(
                f"{node.base_url}/v1/disputes/resolve",
                "token-challenge",
                {
                    "dispute_id": dispute_payload_2["dispute"]["id"],
                    "resolution_status": "upheld",
                    "reason": "challenge upheld after deterministic replay",
                    "operator_id": "operator-challenge-2",
                },
            )
            self.assertEqual(resolve_status_2, 200)
            self.assertEqual(resolved_2["dispute"]["status"], "upheld")
            self.assertEqual(resolved_2["dispute"]["bond_status"], "awarded")
            self.assertEqual(
                resolved_2["dispute"]["resolution"]["receipt"]["reason_codes"],
                ["dispute-resolved", "resolution-upheld", "operator-resolution"],
            )
            self.assertEqual(resolved_2["dispute"]["contract_alignment"]["escrow"]["action"], "slashJob")
            self.assertEqual(
                resolved_2["dispute"]["contract_alignment"]["bond"]["projected_action"],
                "awardChallengerBond",
            )

            _, preview_after_upheld = self._get(f"{node.base_url}/v1/onchain/settlement-preview?task_id=challenge-task-1")
            self.assertEqual(preview_after_upheld["settlement"]["recommended_resolution"], "slashJob")
            self.assertEqual(preview_after_upheld["settlement"]["upheld_dispute_count"], 1)
            self.assertEqual(preview_after_upheld["settlement"]["intents"][1]["function"], "slashJob")
        finally:
            node.stop()

    def test_dispute_committee_votes_can_resolve_or_escalate(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:committee-worker",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="committee-node",
            token="token-committee",
            db_path=str(Path(self.tempdir.name) / "committee.db"),
            capabilities=["worker", "committee-member"],
            signing_secret="committee-secret",
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-committee",
                {
                    "id": "committee-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 89,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-committee",
                {"worker_id": "worker-committee-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-committee",
                {
                    "task_id": "committee-task-1",
                    "worker_id": "worker-committee-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-committee-1"},
                },
            )

            _, opened = self._post(
                f"{node.base_url}/v1/disputes",
                "token-committee",
                {
                    "task_id": "committee-task-1",
                    "challenger_id": "reviewer-committee-1",
                    "actor_id": "worker-committee-1",
                    "actor_type": "worker",
                    "reason": "committee review requested",
                    "evidence_hash": "committee-evidence-1",
                    "severity": "high",
                    "committee_quorum": 2,
                    "committee_deadline": "2030-01-01T00:00:00Z",
                },
            )
            dispute_id = opened["dispute"]["id"]
            self.assertEqual(opened["dispute"]["committee_quorum"], 2)
            self.assertEqual(opened["dispute"]["contract_alignment"]["committee"]["future_contract"], "ChallengeManager")
            self.assertEqual(opened["dispute"]["contract_alignment"]["committee"]["projected_action"], "collectCommitteeVotes")

            _, vote_one = self._post(
                f"{node.base_url}/v1/disputes/vote",
                "token-committee",
                {"dispute_id": dispute_id, "voter_id": "committee-a", "decision": "approve"},
            )
            self.assertEqual(vote_one["dispute"]["status"], "open")
            self.assertEqual(vote_one["dispute"]["committee_tally"]["approve"], 1)

            _, vote_two = self._post(
                f"{node.base_url}/v1/disputes/vote",
                "token-committee",
                {"dispute_id": dispute_id, "voter_id": "committee-b", "decision": "approve"},
            )
            self.assertEqual(vote_two["dispute"]["status"], "upheld")
            self.assertEqual(vote_two["dispute"]["resolution"]["operator_id"], "committee:committee-b")
            self.assertEqual(vote_two["dispute"]["resolution"]["receipt"]["@type"], "agentcoin:GovernanceActionReceipt")
            self.assertEqual(
                vote_two["dispute"]["resolution"]["receipt"]["reason_codes"],
                ["dispute-resolved", "resolution-upheld", "committee-resolution"],
            )
            self.assertEqual(vote_two["dispute"]["resolution"]["receipt"]["target"]["dispute_id"], dispute_id)
            self.assertEqual(vote_two["dispute"]["contract_alignment"]["committee"]["projected_action"], "finalizeCommitteeResolution")
            self.assertEqual(vote_two["dispute"]["contract_alignment"]["escrow"]["action"], "slashJob")
            committee_verification = verify_document(
                vote_two["dispute"]["resolution"]["receipt"],
                secret="committee-secret",
                expected_scope="governance-receipt",
                expected_key_id="committee-node",
            )
            self.assertTrue(committee_verification["verified"])

            _, preview = self._get(f"{node.base_url}/v1/onchain/settlement-preview?task_id=committee-task-1")
            self.assertEqual(preview["settlement"]["recommended_resolution"], "slashJob")

            _, opened_two = self._post(
                f"{node.base_url}/v1/disputes",
                "token-committee",
                {
                    "task_id": "committee-task-1",
                    "challenger_id": "reviewer-committee-2",
                    "actor_id": "worker-committee-1",
                    "actor_type": "worker",
                    "reason": "committee split vote",
                    "evidence_hash": "committee-evidence-2",
                    "severity": "medium",
                    "committee_quorum": 2,
                },
            )
            split_id = opened_two["dispute"]["id"]
            self._post(
                f"{node.base_url}/v1/disputes/vote",
                "token-committee",
                {"dispute_id": split_id, "voter_id": "committee-c", "decision": "approve"},
            )
            _, split_vote = self._post(
                f"{node.base_url}/v1/disputes/vote",
                "token-committee",
                {"dispute_id": split_id, "voter_id": "committee-d", "decision": "abstain"},
            )
            self.assertEqual(split_vote["dispute"]["status"], "escalated")

            _, replay = self._get(f"{node.base_url}/v1/tasks/replay-inspect?task_id=committee-task-1")
            escalated = [item for item in replay["disputes"] if item["id"] == split_id][0]
            self.assertEqual(escalated["committee_tally"]["abstain"], 1)
            self.assertEqual(escalated["contract_alignment"]["committee"]["projected_action"], "escalateDispute")
            self.assertEqual(escalated["contract_alignment"]["escrow"]["action"], "challengeJob")

            _, preview_escalated = self._get(f"{node.base_url}/v1/onchain/settlement-preview?task_id=committee-task-1")
            self.assertEqual(preview_escalated["settlement"]["recommended_resolution"], "challengeJob")
            self.assertEqual(preview_escalated["settlement"]["escalated_dispute_count"], 1)
        finally:
            node.stop()

    def test_onchain_settlement_rpc_plan_expands_recommended_sequence(self) -> None:
        rpc = RpcHarness(
            {
                "eth_getTransactionCount": "0xa",
                "eth_gasPrice": "0x12a05f200",
                "eth_estimateGas": "0x6000",
            }
        )
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:plan-worker",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-plan-node",
            token="token-settlement-plan",
            db_path=str(Path(self.tempdir.name) / "settlement-plan.db"),
            capabilities=["worker"],
            signing_secret="settlement-plan-secret",
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-plan",
                {
                    "id": "settlement-plan-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 91,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-settlement-plan",
                {"worker_id": "worker-plan-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-settlement-plan",
                {
                    "task_id": "settlement-plan-task-1",
                    "worker_id": "worker-plan-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-plan-1"},
                },
            )

            _, plan_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-rpc-plan",
                "token-settlement-plan",
                {
                    "task_id": "settlement-plan-task-1",
                    "resolve_live": True,
                },
            )
            plan = plan_payload["plan"]
            self.assertEqual(plan["kind"], "evm-settlement-rpc-plan")
            self.assertEqual(plan["recommended_resolution"], "completeJob")
            self.assertTrue(plan["resolved_live"])
            self.assertEqual([step["action"] for step in plan["steps"]], ["submitWork", "completeJob"])
            self.assertTrue(plan["settlement_ledger"]["ledger_id"].startswith("settlement-ledger:settlement-plan-task-1:"))
            self.assertEqual(plan["settlement_ledger"]["receipt_type"], "agentcoin:SettlementLedgerReceipt")
            self.assertEqual(plan["steps"][0]["rpc_payload"]["transaction"]["nonce"], "0xa")
            self.assertEqual(plan["steps"][1]["rpc_payload"]["transaction"]["gas"], "0x6000")
            verification = verify_document(
                plan,
                secret="settlement-plan-secret",
                expected_scope="onchain-settlement-rpc-plan",
                expected_key_id="settlement-plan-node",
            )
            self.assertTrue(verification["verified"])
        finally:
            node.stop()
            rpc.stop()

    def test_onchain_settlement_rpc_plan_tracks_challenge_sequence(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:challenge-plan-worker",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="challenge-plan-node",
            token="token-challenge-plan",
            db_path=str(Path(self.tempdir.name) / "challenge-plan.db"),
            capabilities=["worker"],
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-challenge-plan",
                {
                    "id": "challenge-plan-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 92,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-challenge-plan",
                {"worker_id": "worker-challenge-plan-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-challenge-plan",
                {
                    "task_id": "challenge-plan-task-1",
                    "worker_id": "worker-challenge-plan-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-challenge-plan-1"},
                },
            )
            self._post(
                f"{node.base_url}/v1/disputes",
                "token-challenge-plan",
                {
                    "task_id": "challenge-plan-task-1",
                    "challenger_id": "reviewer-open-1",
                    "actor_id": "worker-challenge-plan-1",
                    "reason": "challenge for settlement plan",
                    "evidence_hash": "challenge-plan-evidence",
                    "severity": "high",
                },
            )

            _, plan_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-rpc-plan",
                "token-challenge-plan",
                {"task_id": "challenge-plan-task-1"},
            )
            plan = plan_payload["plan"]
            self.assertFalse(plan["resolved_live"])
            self.assertEqual(plan["recommended_resolution"], "challengeJob")
            self.assertEqual([step["action"] for step in plan["steps"]], ["submitWork", "challengeJob"])
            self.assertTrue(plan["settlement_ledger"]["ledger_hash"])
            self.assertEqual(plan["steps"][1]["intent"]["function"], "challengeJob")
        finally:
            node.stop()

    def test_onchain_settlement_raw_bundle_wraps_signed_transactions(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:bundle-worker",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-bundle-node",
            token="token-settlement-bundle",
            db_path=str(Path(self.tempdir.name) / "settlement-bundle.db"),
            capabilities=["worker"],
            signing_secret="settlement-bundle-secret",
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-bundle",
                {
                    "id": "settlement-bundle-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 93,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-settlement-bundle",
                {"worker_id": "worker-bundle-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-settlement-bundle",
                {
                    "task_id": "settlement-bundle-task-1",
                    "worker_id": "worker-bundle-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-bundle-1"},
                },
            )

            _, bundle_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-raw-bundle",
                "token-settlement-bundle",
                {
                    "task_id": "settlement-bundle-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaabbbb", "signed_by": "wallet-1"},
                        {"action": "completeJob", "raw_transaction": "0xccccdddd", "signed_by": "wallet-1"},
                    ],
                },
            )
            bundle = bundle_payload["bundle"]
            self.assertEqual(bundle["kind"], "evm-settlement-raw-bundle")
            self.assertEqual(bundle["recommended_resolution"], "completeJob")
            self.assertTrue(bundle["settlement_ledger"]["ledger_hash"])
            self.assertEqual(bundle["step_count"], 2)
            self.assertEqual([step["action"] for step in bundle["steps"]], ["submitWork", "completeJob"])
            self.assertEqual(bundle["steps"][0]["raw_relay_payload"]["request"]["method"], "eth_sendRawTransaction")
            self.assertEqual(bundle["steps"][1]["raw_transaction"], "0xccccdddd")
            verification = verify_document(
                bundle,
                secret="settlement-bundle-secret",
                expected_scope="onchain-settlement-raw-bundle",
                expected_key_id="settlement-bundle-node",
            )
            self.assertTrue(verification["verified"])
        finally:
            node.stop()

    def test_onchain_settlement_relay_submits_bundle_sequence(self) -> None:
        call_count = {"raw": 0}

        def raw_tx_response(_payload: dict[str, object]) -> str:
            call_count["raw"] += 1
            return f"0xsettlement{call_count['raw']}"

        rpc = RpcHarness(
            {
                "eth_sendRawTransaction": raw_tx_response,
            }
        )
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:relay-worker",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-relay-node",
            token="token-settlement-relay",
            db_path=str(Path(self.tempdir.name) / "settlement-relay.db"),
            capabilities=["worker"],
            signing_secret="settlement-relay-secret",
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-relay",
                {
                    "id": "settlement-relay-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 94,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-settlement-relay",
                {"worker_id": "worker-relay-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-settlement-relay",
                {
                    "task_id": "settlement-relay-task-1",
                    "worker_id": "worker-relay-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-relay-1"},
                },
            )

            _, relay_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay",
                "token-settlement-relay",
                {
                    "task_id": "settlement-relay-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaabbbb"},
                        {"action": "completeJob", "raw_transaction": "0xccccdddd"},
                    ],
                },
            )
            relay = relay_payload["relay"]
            self.assertEqual(relay["kind"], "evm-settlement-relay")
            self.assertEqual(relay["@type"], "agentcoin:SettlementRelayReceipt")
            self.assertEqual(relay["schema_version"], "0.1")
            self.assertEqual(relay["recommended_resolution"], "completeJob")
            self.assertTrue(relay["settlement_ledger"]["ledger_hash"])
            self.assertEqual(relay["completed_steps"], 2)
            self.assertFalse(relay["stopped_on_error"])
            self.assertEqual(relay["final_status"], "completed")
            self.assertEqual(relay["last_successful_index"], 1)
            self.assertEqual(relay["next_index"], 2)
            self.assertEqual(relay["retry_count"], 0)
            self.assertEqual(relay["submitted_steps"][0]["tx_hash"], "0xsettlement1")
            self.assertEqual(relay["submitted_steps"][1]["tx_hash"], "0xsettlement2")
            self.assertTrue(relay["relay_record_id"])
            verification = verify_document(
                relay,
                secret="settlement-relay-secret",
                expected_scope="onchain-settlement-relay",
                expected_key_id="settlement-relay-node",
            )
            self.assertTrue(verification["verified"])
            self.assertEqual([call["method"] for call in rpc.calls], ["eth_sendRawTransaction", "eth_sendRawTransaction"])

            _, relay_history = self._get(f"{node.base_url}/v1/onchain/settlement-relays?task_id=settlement-relay-task-1")
            self.assertEqual(len(relay_history["items"]), 1)
            self.assertEqual(relay_history["items"][0]["completed_steps"], 2)
            self.assertEqual(relay_history["items"][0]["final_status"], "completed")
            self.assertEqual(
                relay_history["items"][0]["relay"]["settlement_ledger"]["ledger_id"],
                relay["settlement_ledger"]["ledger_id"],
            )
            self.assertEqual(relay_history["items"][0]["relay"]["recommended_resolution"], "completeJob")
            latest_status, latest_relay = self._get(
                f"{node.base_url}/v1/onchain/settlement-relays/latest?task_id=settlement-relay-task-1"
            )
            self.assertEqual(latest_status, 200)
            self.assertEqual(latest_relay["id"], relay["relay_record_id"])
            self.assertEqual(latest_relay["last_successful_index"], 1)

            _, replay = self._get(f"{node.base_url}/v1/tasks/replay-inspect?task_id=settlement-relay-task-1")
            self.assertEqual(len(replay["settlement_relays"]), 1)
            self.assertEqual(replay["settlement_relays"][0]["relay"]["completed_steps"], 2)
            self.assertEqual(replay["latest_settlement_relay"]["id"], relay["relay_record_id"])
        finally:
            node.stop()
            rpc.stop()

    def test_signed_operator_request_is_required_for_settlement_relay(self) -> None:
        call_count = {"raw": 0}

        def raw_tx_response(_payload: dict[str, object]) -> str:
            call_count["raw"] += 1
            return f"0xsettlementauth{call_count['raw']}"

        rpc = RpcHarness({"eth_sendRawTransaction": raw_tx_response})
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:relay-auth-worker",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-relay-node",
            token="token-settlement-relay",
            db_path=str(Path(self.tempdir.name) / "settlement-relay-auth.db"),
            capabilities=["worker"],
            signing_secret="settlement-relay-secret",
            operator_identities=[
                OperatorIdentityConfig(
                    key_id="settlement-admin:ops-1",
                    shared_secret="settlement-operator-secret",
                    scopes=["settlement-admin"],
                )
            ],
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-relay",
                {
                    "id": "settlement-relay-auth-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 941,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-settlement-relay",
                {"worker_id": "worker-relay-auth-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-settlement-relay",
                {
                    "task_id": "settlement-relay-auth-task-1",
                    "worker_id": "worker-relay-auth-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-relay-auth-1"},
                },
            )

            denied_status, denied = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay",
                "token-settlement-relay",
                {
                    "task_id": "settlement-relay-auth-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaabbbb"},
                        {"action": "completeJob", "raw_transaction": "0xccccdddd"},
                    ],
                },
            )
            self.assertEqual(denied_status, 401)
            self.assertEqual(denied["policy_receipt"]["reason_code"], "signed-request-required")

            signed_status, relay_payload = self._signed_post(
                f"{node.base_url}/v1/onchain/settlement-relay",
                "token-settlement-relay",
                {
                    "task_id": "settlement-relay-auth-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaabbbb"},
                        {"action": "completeJob", "raw_transaction": "0xccccdddd"},
                    ],
                },
                key_id="settlement-admin:ops-1",
                shared_secret="settlement-operator-secret",
            )
            self.assertEqual(signed_status, 200)
            relay = relay_payload["relay"]
            self.assertEqual(relay["operator_id"], "settlement-admin:ops-1")
            self.assertEqual(relay["auth_context"]["mode"], "signed-hmac")
            self.assertEqual(relay["auth_context"]["policy_tier"], "settlement-admin")
            self.assertEqual(relay["auth_context"]["key_id"], "settlement-admin:ops-1")
            verification = verify_document(
                relay,
                secret="settlement-relay-secret",
                expected_scope="onchain-settlement-relay",
                expected_key_id="settlement-relay-node",
            )
            self.assertTrue(verification["verified"])

            audits = node.node.store.list_operator_auth_audits(endpoint="/v1/onchain/settlement-relay", limit=10)
            self.assertEqual([item["decision"] for item in audits[:2]], ["allowed", "denied"])
            self.assertEqual(audits[0]["key_id"], "settlement-admin:ops-1")
            self.assertEqual(audits[0]["auth_mode"], "signed-hmac")
            self.assertEqual(audits[1]["payload"]["policy_receipt"]["reason_code"], "signed-request-required")
        finally:
            node.stop()
            rpc.stop()

    def test_onchain_settlement_relay_can_resume_from_failed_step(self) -> None:
        call_count = {"raw": 0}

        def raw_tx_response(_payload: dict[str, object]) -> str:
            call_count["raw"] += 1
            return f"0xresume{call_count['raw']}"

        rpc = RpcHarness({"eth_sendRawTransaction": raw_tx_response})
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:resume-worker",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-resume-node",
            token="token-settlement-resume",
            db_path=str(Path(self.tempdir.name) / "settlement-resume.db"),
            capabilities=["worker"],
            signing_secret="settlement-resume-secret",
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-resume",
                {
                    "id": "settlement-resume-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 95,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-settlement-resume",
                {"worker_id": "worker-resume-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-settlement-resume",
                {
                    "task_id": "settlement-resume-task-1",
                    "worker_id": "worker-resume-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-resume-1"},
                },
            )

            _, failed_relay_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay",
                "token-settlement-resume",
                {
                    "task_id": "settlement-resume-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0x1111", "rpc_url": rpc.url},
                        {"action": "completeJob", "raw_transaction": "0x2222", "rpc_url": "http://127.0.0.1:1"},
                    ],
                },
            )
            failed_relay = failed_relay_payload["relay"]
            self.assertEqual(failed_relay["completed_steps"], 1)
            self.assertTrue(failed_relay["stopped_on_error"])
            self.assertEqual(failed_relay["final_status"], "partial")
            self.assertEqual(failed_relay["last_successful_index"], 0)
            self.assertEqual(failed_relay["next_index"], 1)
            self.assertEqual(len(failed_relay["failures"]), 1)
            self.assertEqual(failed_relay["failure_category"], "network")

            _, resumed_relay_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay",
                "token-settlement-resume",
                {
                    "task_id": "settlement-resume-task-1",
                    "resume_from_index": 1,
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0x1111", "rpc_url": rpc.url},
                        {"action": "completeJob", "raw_transaction": "0x2222", "rpc_url": rpc.url},
                    ],
                },
            )
            resumed_relay = resumed_relay_payload["relay"]
            self.assertTrue(resumed_relay["resumed"])
            self.assertEqual(resumed_relay["resume_from_index"], 1)
            self.assertEqual(resumed_relay["completed_steps"], 1)
            self.assertFalse(resumed_relay["stopped_on_error"])
            self.assertEqual(resumed_relay["final_status"], "completed")
            self.assertEqual(resumed_relay["next_index"], 2)
            self.assertEqual(resumed_relay["submitted_steps"][0]["action"], "completeJob")
            verification = verify_document(
                resumed_relay,
                secret="settlement-resume-secret",
                expected_scope="onchain-settlement-relay",
                expected_key_id="settlement-resume-node",
            )
            self.assertTrue(verification["verified"])
        finally:
            node.stop()
            rpc.stop()

    def test_onchain_settlement_relay_replay_can_resume_from_latest_history(self) -> None:
        call_count = {"raw": 0}

        def raw_tx_response(_payload: dict[str, object]) -> str:
            call_count["raw"] += 1
            return f"0xreplay{call_count['raw']}"

        rpc = RpcHarness({"eth_sendRawTransaction": raw_tx_response})
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:replay-worker",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-replay-node",
            token="token-settlement-replay",
            db_path=str(Path(self.tempdir.name) / "settlement-replay.db"),
            capabilities=["worker"],
            signing_secret="settlement-replay-secret",
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-replay",
                {
                    "id": "settlement-replay-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 96,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-settlement-replay",
                {"worker_id": "worker-replay-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-settlement-replay",
                {
                    "task_id": "settlement-replay-task-1",
                    "worker_id": "worker-replay-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-replay-1"},
                },
            )

            _, failed_relay_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay",
                "token-settlement-replay",
                {
                    "task_id": "settlement-replay-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa", "rpc_url": rpc.url},
                        {"action": "completeJob", "raw_transaction": "0xbbbb", "rpc_url": "http://127.0.0.1:1"},
                    ],
                },
            )
            failed_relay = failed_relay_payload["relay"]
            self.assertTrue(failed_relay["relay_record_id"])
            self.assertEqual(failed_relay["next_index"], 1)

            _, replayed_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relays/replay",
                "token-settlement-replay",
                {
                    "relay_id": failed_relay["relay_record_id"],
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa", "rpc_url": rpc.url},
                        {"action": "completeJob", "raw_transaction": "0xbbbb", "rpc_url": rpc.url},
                    ],
                },
            )
            replayed = replayed_payload["relay"]
            self.assertTrue(replayed["resumed"])
            self.assertEqual(replayed["resume_from_index"], 1)
            self.assertEqual(replayed["retry_count"], 1)
            self.assertEqual(replayed["resumed_from_relay_id"], failed_relay["relay_record_id"])
            self.assertEqual(replayed["completed_steps"], 1)
            self.assertEqual(replayed["final_status"], "completed")

            _, latest = self._get(f"{node.base_url}/v1/onchain/settlement-relays/latest?task_id=settlement-replay-task-1")
            self.assertEqual(latest["id"], replayed["relay_record_id"])
            self.assertEqual(latest["retry_count"], 1)
            self.assertEqual(latest["resumed_from_relay_id"], failed_relay["relay_record_id"])

            _, history = self._get(f"{node.base_url}/v1/onchain/settlement-relays?task_id=settlement-replay-task-1")
            self.assertEqual(len(history["items"]), 2)
            self.assertEqual(history["items"][0]["retry_count"], 1)
            self.assertEqual(history["items"][1]["retry_count"], 0)
        finally:
            node.stop()
            rpc.stop()

    def test_onchain_settlement_relay_reconciliation_marks_confirmed_receipts(self) -> None:
        call_count = {"raw": 0}

        def raw_tx_response(_payload: dict[str, object]) -> str:
            call_count["raw"] += 1
            return f"0x{call_count['raw']:064x}"

        def receipt_response(payload: dict[str, object]) -> dict[str, object]:
            params = list(payload.get("params") or [])
            tx_hash = str(params[0] if params else "")
            return {"transactionHash": tx_hash, "status": "0x1", "blockNumber": "0x10"}

        rpc = RpcHarness(
            {
                "eth_sendRawTransaction": raw_tx_response,
                "eth_getTransactionReceipt": receipt_response,
            }
        )
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:relay-confirmed",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-confirmed-node",
            token="token-settlement-confirmed",
            db_path=str(Path(self.tempdir.name) / "settlement-confirmed.db"),
            capabilities=["worker"],
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-confirmed",
                {
                    "id": "settlement-confirmed-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 101,
                },
            )
            self._complete_onchain_task(
                node,
                "token-settlement-confirmed",
                "settlement-confirmed-task-1",
                "worker-settlement-confirmed",
            )

            _, relay_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay",
                "token-settlement-confirmed",
                {
                    "task_id": "settlement-confirmed-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa", "rpc_url": rpc.url},
                        {"action": "completeJob", "raw_transaction": "0xbbbb", "rpc_url": rpc.url},
                    ],
                },
            )
            relay = relay_payload["relay"]

            _, reconciled_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relays/reconcile",
                "token-settlement-confirmed",
                {"relay_id": relay["relay_record_id"]},
            )
            reconciled = reconciled_payload["item"]
            self.assertEqual(reconciled["reconciliation_status"], "confirmed")
            self.assertIsNotNone(reconciled["reconciliation_checked_at"])
            self.assertIsNotNone(reconciled["confirmed_at"])
            self.assertEqual(len(reconciled["chain_receipts"]), 2)
            self.assertTrue(all(item["status"] == "confirmed" for item in reconciled["chain_receipts"]))

            _, replay = self._get(f"{node.base_url}/v1/tasks/replay-inspect?task_id=settlement-confirmed-task-1")
            self.assertEqual(replay["settlement_reconciliation"]["status"], "confirmed")
            self.assertEqual(replay["latest_settlement_relay"]["reconciliation_status"], "confirmed")
            self.assertEqual(len(replay["latest_settlement_relay"]["chain_receipts"]), 2)

            receipt_calls = [item for item in rpc.calls if item.get("method") == "eth_getTransactionReceipt"]
            self.assertEqual(len(receipt_calls), 2)
        finally:
            node.stop()
            rpc.stop()

    def test_confirmed_final_settlement_reconciliation_auto_finalizes_workflow(self) -> None:
        call_count = {"raw": 0}

        def raw_tx_response(_payload: dict[str, object]) -> str:
            call_count["raw"] += 1
            return f"0x{call_count['raw']:064x}"

        def receipt_response(payload: dict[str, object]) -> dict[str, object]:
            params = list(payload.get("params") or [])
            tx_hash = str(params[0] if params else "")
            return {"transactionHash": tx_hash, "status": "0x1", "blockNumber": "0x22"}

        rpc = RpcHarness(
            {
                "eth_sendRawTransaction": raw_tx_response,
                "eth_getTransactionReceipt": receipt_response,
            }
        )
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:relay-auto-finalize",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-auto-finalize-node",
            token="token-settlement-auto-finalize",
            db_path=str(Path(self.tempdir.name) / "settlement-auto-finalize.db"),
            capabilities=["worker"],
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-auto-finalize",
                {
                    "id": "settlement-auto-finalize-task-1",
                    "kind": "code",
                    "role": "worker",
                    "workflow_id": "wf-settlement-auto-finalize",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 104,
                },
            )
            self._complete_onchain_task(
                node,
                "token-settlement-auto-finalize",
                "settlement-auto-finalize-task-1",
                "worker-settlement-auto-finalize",
            )

            _, summary_before = self._get(f"{node.base_url}/v1/workflows/summary?workflow_id=wf-settlement-auto-finalize")
            self.assertTrue(summary_before["finalizable"])
            self.assertIsNone(summary_before["persisted_state"])

            _, relay_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay",
                "token-settlement-auto-finalize",
                {
                    "task_id": "settlement-auto-finalize-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa", "rpc_url": rpc.url},
                        {"action": "completeJob", "raw_transaction": "0xbbbb", "rpc_url": rpc.url},
                    ],
                },
            )
            relay = relay_payload["relay"]

            _, reconciled_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relays/reconcile",
                "token-settlement-auto-finalize",
                {"relay_id": relay["relay_record_id"]},
            )
            reconciled = reconciled_payload["item"]
            self.assertEqual(reconciled["reconciliation_status"], "confirmed")
            self.assertTrue(reconciled["auto_finalize"]["attempted"])
            self.assertTrue(reconciled["auto_finalize"]["finalized"])
            self.assertEqual(reconciled["auto_finalize"]["workflow_id"], "wf-settlement-auto-finalize")
            self.assertEqual(reconciled["auto_finalize"]["recommended_resolution"], "completeJob")

            _, summary_after = self._get(f"{node.base_url}/v1/workflows/summary?workflow_id=wf-settlement-auto-finalize")
            self.assertIsNotNone(summary_after["persisted_state"])
            self.assertEqual(summary_after["persisted_state"]["status"], "completed")
            self.assertIsNotNone(summary_after["persisted_state"]["finalized_at"])
        finally:
            node.stop()
            rpc.stop()

    def test_confirmed_challenge_reconciliation_does_not_auto_finalize_workflow(self) -> None:
        call_count = {"raw": 0}

        def raw_tx_response(_payload: dict[str, object]) -> str:
            call_count["raw"] += 1
            return f"0x{call_count['raw']:064x}"

        def receipt_response(payload: dict[str, object]) -> dict[str, object]:
            params = list(payload.get("params") or [])
            tx_hash = str(params[0] if params else "")
            return {"transactionHash": tx_hash, "status": "0x1", "blockNumber": "0x23"}

        rpc = RpcHarness(
            {
                "eth_sendRawTransaction": raw_tx_response,
                "eth_getTransactionReceipt": receipt_response,
            }
        )
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:relay-no-auto-finalize",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-no-auto-finalize-node",
            token="token-settlement-no-auto-finalize",
            db_path=str(Path(self.tempdir.name) / "settlement-no-auto-finalize.db"),
            capabilities=["worker"],
            onchain=onchain,
            challenge_bond_required_wei=7000000000000000,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-no-auto-finalize",
                {
                    "id": "settlement-no-auto-finalize-task-1",
                    "kind": "code",
                    "role": "worker",
                    "workflow_id": "wf-settlement-no-auto-finalize",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 105,
                },
            )
            self._complete_onchain_task(
                node,
                "token-settlement-no-auto-finalize",
                "settlement-no-auto-finalize-task-1",
                "worker-settlement-no-auto-finalize",
            )
            self._post(
                f"{node.base_url}/v1/disputes",
                "token-settlement-no-auto-finalize",
                {
                    "task_id": "settlement-no-auto-finalize-task-1",
                    "challenger_id": "reviewer-settlement-no-auto-finalize",
                    "actor_id": "worker-settlement-no-auto-finalize",
                    "actor_type": "worker",
                    "reason": "deterministic mismatch",
                    "evidence_hash": "settlement-no-auto-finalize-evidence",
                    "severity": "high",
                },
            )

            _, preview = self._get(
                f"{node.base_url}/v1/onchain/settlement-preview?task_id=settlement-no-auto-finalize-task-1"
            )
            self.assertEqual(preview["settlement"]["recommended_resolution"], "challengeJob")

            _, summary_before = self._get(f"{node.base_url}/v1/workflows/summary?workflow_id=wf-settlement-no-auto-finalize")
            self.assertTrue(summary_before["finalizable"])
            self.assertIsNone(summary_before["persisted_state"])

            _, relay_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay",
                "token-settlement-no-auto-finalize",
                {
                    "task_id": "settlement-no-auto-finalize-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa", "rpc_url": rpc.url},
                        {"action": "challengeJob", "raw_transaction": "0xbbbb", "rpc_url": rpc.url},
                    ],
                },
            )
            relay = relay_payload["relay"]
            self.assertEqual(relay["recommended_resolution"], "challengeJob")

            _, reconciled_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relays/reconcile",
                "token-settlement-no-auto-finalize",
                {"relay_id": relay["relay_record_id"]},
            )
            reconciled = reconciled_payload["item"]
            self.assertEqual(reconciled["reconciliation_status"], "confirmed")
            self.assertFalse(reconciled["auto_finalize"]["attempted"])
            self.assertEqual(reconciled["auto_finalize"]["reason"], "resolution-not-final")
            self.assertEqual(reconciled["auto_finalize"]["recommended_resolution"], "challengeJob")

            _, summary_after = self._get(f"{node.base_url}/v1/workflows/summary?workflow_id=wf-settlement-no-auto-finalize")
            self.assertIsNone(summary_after["persisted_state"])
        finally:
            node.stop()
            rpc.stop()

    def test_onchain_settlement_relay_reconciliation_marks_reverted_receipts(self) -> None:
        call_count = {"raw": 0}

        def raw_tx_response(_payload: dict[str, object]) -> str:
            call_count["raw"] += 1
            return f"0x{call_count['raw']:064x}"

        def receipt_response(payload: dict[str, object]) -> dict[str, object]:
            params = list(payload.get("params") or [])
            tx_hash = str(params[0] if params else "")
            status = "0x1" if tx_hash.endswith("1") else "0x0"
            return {"transactionHash": tx_hash, "status": status, "blockNumber": "0x11"}

        rpc = RpcHarness(
            {
                "eth_sendRawTransaction": raw_tx_response,
                "eth_getTransactionReceipt": receipt_response,
            }
        )
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:relay-reverted",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-reverted-node",
            token="token-settlement-reverted",
            db_path=str(Path(self.tempdir.name) / "settlement-reverted.db"),
            capabilities=["worker"],
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-reverted",
                {
                    "id": "settlement-reverted-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 102,
                },
            )
            self._complete_onchain_task(
                node,
                "token-settlement-reverted",
                "settlement-reverted-task-1",
                "worker-settlement-reverted",
            )

            _, relay_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay",
                "token-settlement-reverted",
                {
                    "task_id": "settlement-reverted-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa", "rpc_url": rpc.url},
                        {"action": "completeJob", "raw_transaction": "0xbbbb", "rpc_url": rpc.url},
                    ],
                },
            )
            relay = relay_payload["relay"]

            _, reconciled_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relays/reconcile",
                "token-settlement-reverted",
                {"task_id": relay["task_id"]},
            )
            reconciled = reconciled_payload["item"]
            self.assertEqual(reconciled["id"], relay["relay_record_id"])
            self.assertEqual(reconciled["reconciliation_status"], "reverted")
            self.assertIsNotNone(reconciled["reconciliation_checked_at"])
            self.assertIsNone(reconciled["confirmed_at"])
            self.assertEqual(reconciled["chain_receipts"][1]["status"], "reverted")

            _, replay = self._get(f"{node.base_url}/v1/tasks/replay-inspect?task_id=settlement-reverted-task-1")
            self.assertEqual(replay["settlement_reconciliation"]["status"], "reverted")
        finally:
            node.stop()
            rpc.stop()

    def test_onchain_settlement_relay_reconciliation_marks_unknown_receipts(self) -> None:
        call_count = {"raw": 0}

        def raw_tx_response(_payload: dict[str, object]) -> str:
            call_count["raw"] += 1
            return f"0x{call_count['raw']:064x}"

        rpc = RpcHarness(
            {
                "eth_sendRawTransaction": raw_tx_response,
                "eth_getTransactionReceipt": None,
            }
        )
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:relay-unknown",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-unknown-node",
            token="token-settlement-unknown",
            db_path=str(Path(self.tempdir.name) / "settlement-unknown.db"),
            capabilities=["worker"],
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-unknown",
                {
                    "id": "settlement-unknown-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 103,
                },
            )
            self._complete_onchain_task(
                node,
                "token-settlement-unknown",
                "settlement-unknown-task-1",
                "worker-settlement-unknown",
            )

            _, relay_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay",
                "token-settlement-unknown",
                {
                    "task_id": "settlement-unknown-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa", "rpc_url": rpc.url},
                        {"action": "completeJob", "raw_transaction": "0xbbbb", "rpc_url": rpc.url},
                    ],
                },
            )
            relay = relay_payload["relay"]

            _, reconciled_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relays/reconcile",
                "token-settlement-unknown",
                {"relay_id": relay["relay_record_id"]},
            )
            reconciled = reconciled_payload["item"]
            self.assertEqual(reconciled["reconciliation_status"], "unknown")
            self.assertIsNotNone(reconciled["reconciliation_checked_at"])
            self.assertIsNone(reconciled["confirmed_at"])
            self.assertTrue(all(item["status"] == "unknown" for item in reconciled["chain_receipts"]))

            _, replay = self._get(f"{node.base_url}/v1/tasks/replay-inspect?task_id=settlement-unknown-task-1")
            self.assertEqual(replay["settlement_reconciliation"]["status"], "unknown")
        finally:
            node.stop()
            rpc.stop()

    def test_onchain_settlement_relay_queue_persists_items(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:queue-worker",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-queue-node",
            token="token-settlement-queue",
            db_path=str(Path(self.tempdir.name) / "settlement-queue.db"),
            capabilities=["worker"],
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-queue",
                {
                    "id": "settlement-queue-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 99,
                },
            )
            self._complete_onchain_task(node, "token-settlement-queue", "settlement-queue-task-1", "worker-settlement-queue")
            status, queued = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue",
                "token-settlement-queue",
                {
                    "task_id": "settlement-queue-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa"},
                        {"action": "completeJob", "raw_transaction": "0xbbbb"},
                    ],
                    "rpc_url": "https://bsc-testnet.example/rpc",
                    "max_attempts": 5,
                },
            )
            self.assertEqual(status, 201)
            item = queued["item"]
            self.assertEqual(item["task_id"], "settlement-queue-task-1")
            self.assertEqual(item["status"], "queued")
            self.assertEqual(item["max_attempts"], 5)
            self.assertEqual(item["payload"]["rpc_url"], "https://bsc-testnet.example/rpc")
            self.assertEqual(item["payload"]["raw_transactions"][0]["action"], "submitWork")

            _, queue_items = self._get(f"{node.base_url}/v1/onchain/settlement-relay-queue?task_id=settlement-queue-task-1")
            self.assertEqual(len(queue_items["items"]), 1)
            self.assertEqual(queue_items["items"][0]["id"], item["id"])

            _, health = self._get(f"{node.base_url}/healthz")
            self.assertEqual(health["stats"]["settlement_relay_queue"], 1)
            self.assertEqual(health["stats"]["settlement_relay_queue_queued"], 1)

            _, replay = self._get(f"{node.base_url}/v1/tasks/replay-inspect?task_id=settlement-queue-task-1")
            self.assertEqual(len(replay["settlement_relay_queue"]), 1)
            self.assertEqual(replay["settlement_relay_queue"][0]["id"], item["id"])
        finally:
            node.stop()

    def test_background_settlement_relay_worker_processes_queued_items(self) -> None:
        rpc = RpcHarness({"eth_sendRawTransaction": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:queue-worker-bg",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-worker-node",
            token="token-settlement-worker",
            db_path=str(Path(self.tempdir.name) / "settlement-worker.db"),
            capabilities=["worker"],
            onchain=onchain,
            settlement_relay_poll_seconds=0.1,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-worker",
                {
                    "id": "settlement-worker-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 42,
                },
            )
            self._complete_onchain_task(node, "token-settlement-worker", "settlement-worker-task-1", "worker-settlement-bg")
            _, queued = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue",
                "token-settlement-worker",
                {
                    "task_id": "settlement-worker-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa"},
                        {"action": "completeJob", "raw_transaction": "0xbbbb"},
                    ],
                    "rpc_url": rpc.url,
                },
            )
            item = queued["item"]

            completed = self._wait_for_queue_item_status(node, item["id"], status="completed", timeout=3.0)
            self.assertEqual(completed["attempts"], 1)
            self.assertIsNotNone(completed["last_relay_id"])
            self.assertIsNotNone(completed["completed_at"])
            self.assertEqual(len(rpc.calls), 2)

            _, relay_history = self._get(f"{node.base_url}/v1/onchain/settlement-relays?task_id=settlement-worker-task-1")
            self.assertEqual(len(relay_history["items"]), 1)
            self.assertEqual(relay_history["items"][0]["id"], completed["last_relay_id"])
            self.assertEqual(relay_history["items"][0]["final_status"], "completed")
        finally:
            node.stop()
            rpc.stop()

    def test_background_settlement_relay_worker_respects_next_attempt_at(self) -> None:
        rpc = RpcHarness({"eth_sendRawTransaction": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"})
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:queue-delay",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-delay-node",
            token="token-settlement-delay",
            db_path=str(Path(self.tempdir.name) / "settlement-delay.db"),
            capabilities=["worker"],
            onchain=onchain,
            settlement_relay_poll_seconds=0.1,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-delay",
                {
                    "id": "settlement-delay-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 43,
                },
            )
            self._complete_onchain_task(node, "token-settlement-delay", "settlement-delay-task-1", "worker-settlement-delay")
            _, queued = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue",
                "token-settlement-delay",
                {
                    "task_id": "settlement-delay-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa"},
                        {"action": "completeJob", "raw_transaction": "0xbbbb"},
                    ],
                    "rpc_url": rpc.url,
                    "delay_seconds": 2,
                },
            )
            item = queued["item"]

            time.sleep(0.3)
            pending = node.node.store.get_settlement_relay_queue_item(item["id"])
            assert pending is not None
            self.assertEqual(pending["status"], "queued")
            self.assertEqual(len(rpc.calls), 0)

            completed = self._wait_for_queue_item_status(node, item["id"], status="completed", timeout=3.0)
            self.assertEqual(completed["attempts"], 1)
            self.assertEqual(len(rpc.calls), 2)
        finally:
            node.stop()
            rpc.stop()

    def test_settlement_relay_queue_max_in_flight_blocks_extra_claims(self) -> None:
        rpc = RpcHarness({"eth_sendRawTransaction": "0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"})
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:queue-max-in-flight",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-max-in-flight-node",
            token="token-settlement-max-in-flight",
            db_path=str(Path(self.tempdir.name) / "settlement-max-in-flight.db"),
            capabilities=["worker"],
            onchain=onchain,
            settlement_relay_poll_seconds=0,
            settlement_relay_max_in_flight=1,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-max-in-flight",
                {
                    "id": "settlement-max-in-flight-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 47,
                },
            )
            self._complete_onchain_task(
                node,
                "token-settlement-max-in-flight",
                "settlement-max-in-flight-task-1",
                "worker-settlement-max-in-flight",
            )
            _, first_queued = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue",
                "token-settlement-max-in-flight",
                {
                    "task_id": "settlement-max-in-flight-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa"},
                        {"action": "completeJob", "raw_transaction": "0xbbbb"},
                    ],
                    "rpc_url": rpc.url,
                },
            )
            _, second_queued = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue",
                "token-settlement-max-in-flight",
                {
                    "task_id": "settlement-max-in-flight-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xcccc"},
                        {"action": "completeJob", "raw_transaction": "0xdddd"},
                    ],
                    "rpc_url": rpc.url,
                },
            )

            running = node.node.store.claim_next_settlement_relay_queue_item(max_in_flight=1)
            assert running is not None
            self.assertEqual(running["id"], first_queued["item"]["id"])
            blocked = node.node.store.claim_next_settlement_relay_queue_item(max_in_flight=1)
            self.assertIsNone(blocked)

            processed = node.node.process_settlement_relay_queue(max_items=1)
            self.assertEqual(processed, [])
            self.assertEqual(len(rpc.calls), 0)

            _, health = self._get(f"{node.base_url}/healthz")
            self.assertEqual(health["stats"]["settlement_relay_queue_running"], 1)
            self.assertEqual(health["stats"]["settlement_relay_queue_queued"], 1)

            node.node.store.complete_settlement_relay_queue_item(running["id"])
            processed = node.node.process_settlement_relay_queue(max_items=1)
            self.assertEqual(len(processed), 1)
            completed = node.node.store.get_settlement_relay_queue_item(second_queued["item"]["id"])
            assert completed is not None
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(len(rpc.calls), 2)
        finally:
            node.stop()
            rpc.stop()

    def test_background_settlement_relay_worker_retries_then_dead_letters(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="http://127.0.0.1:1",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:queue-retry",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-retry-node",
            token="token-settlement-retry",
            db_path=str(Path(self.tempdir.name) / "settlement-retry.db"),
            capabilities=["worker"],
            onchain=onchain,
            settlement_relay_poll_seconds=0.1,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-retry",
                {
                    "id": "settlement-retry-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 44,
                },
            )
            self._complete_onchain_task(node, "token-settlement-retry", "settlement-retry-task-1", "worker-settlement-retry")
            _, queued = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue",
                "token-settlement-retry",
                {
                    "task_id": "settlement-retry-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa"},
                        {"action": "completeJob", "raw_transaction": "0xbbbb"},
                    ],
                    "rpc_url": "http://127.0.0.1:1",
                    "timeout_seconds": 0.2,
                    "max_attempts": 2,
                },
            )
            item = queued["item"]

            retrying = self._wait_for_queue_item_status(node, item["id"], status="retrying", timeout=3.0)
            self.assertEqual(retrying["attempts"], 1)
            self.assertIsNotNone(retrying["last_relay_id"])
            self.assertIn("resume_from_index", retrying["payload"])

            dead_letter = self._wait_for_queue_item_status(node, item["id"], status="dead-letter", timeout=4.5)
            self.assertEqual(dead_letter["attempts"], 2)
            self.assertIsNotNone(dead_letter["completed_at"])
            self.assertIsNotNone(dead_letter["last_relay_id"])

            _, relay_history = self._get(f"{node.base_url}/v1/onchain/settlement-relays?task_id=settlement-retry-task-1")
            self.assertEqual(len(relay_history["items"]), 2)
            self.assertEqual(relay_history["items"][0]["retry_count"], 1)
        finally:
            node.stop()

    def test_operator_can_pause_and_resume_settlement_relay_queue_item(self) -> None:
        rpc = RpcHarness({"eth_sendRawTransaction": "0xpausequeue"})
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url=rpc.url,
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:queue-pause",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-pause-node",
            token="token-settlement-pause",
            db_path=str(Path(self.tempdir.name) / "settlement-pause.db"),
            capabilities=["worker"],
            onchain=onchain,
            settlement_relay_poll_seconds=0.1,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-pause",
                {
                    "id": "settlement-pause-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 45,
                },
            )
            self._complete_onchain_task(node, "token-settlement-pause", "settlement-pause-task-1", "worker-settlement-pause")
            _, queued = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue",
                "token-settlement-pause",
                {
                    "task_id": "settlement-pause-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa"},
                        {"action": "completeJob", "raw_transaction": "0xbbbb"},
                    ],
                    "rpc_url": rpc.url,
                    "delay_seconds": 2,
                },
            )
            item = queued["item"]

            _, paused_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue/pause",
                "token-settlement-pause",
                {"queue_id": item["id"]},
            )
            self.assertEqual(paused_payload["item"]["status"], "paused")

            time.sleep(0.6)
            paused = node.node.store.get_settlement_relay_queue_item(item["id"])
            assert paused is not None
            self.assertEqual(paused["status"], "paused")
            self.assertEqual(len(rpc.calls), 0)

            _, paused_list = self._get(f"{node.base_url}/v1/onchain/settlement-relay-queue?status=paused")
            self.assertEqual(len(paused_list["items"]), 1)
            self.assertEqual(paused_list["items"][0]["id"], item["id"])

            _, resumed_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue/resume",
                "token-settlement-pause",
                {"queue_id": item["id"], "delay_seconds": 0},
            )
            self.assertEqual(resumed_payload["item"]["status"], "queued")

            completed = self._wait_for_queue_item_status(node, item["id"], status="completed", timeout=3.0)
            self.assertEqual(completed["attempts"], 1)
            self.assertEqual(len(rpc.calls), 2)

            _, health = self._get(f"{node.base_url}/healthz")
            self.assertEqual(health["stats"]["settlement_relay_queue_paused"], 0)
            self.assertEqual(health["stats"]["settlement_relay_queue_completed"], 1)
        finally:
            node.stop()
            rpc.stop()

    def test_operator_can_requeue_dead_letter_settlement_relay_item(self) -> None:
        rpc = RpcHarness({"eth_sendRawTransaction": "0xrequeuequeue"})
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="http://127.0.0.1:1",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:queue-requeue",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-requeue-node",
            token="token-settlement-requeue",
            db_path=str(Path(self.tempdir.name) / "settlement-requeue.db"),
            capabilities=["worker"],
            onchain=onchain,
            settlement_relay_poll_seconds=0.1,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-requeue",
                {
                    "id": "settlement-requeue-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 46,
                },
            )
            self._complete_onchain_task(node, "token-settlement-requeue", "settlement-requeue-task-1", "worker-settlement-requeue")
            _, queued = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue",
                "token-settlement-requeue",
                {
                    "task_id": "settlement-requeue-task-1",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa"},
                        {"action": "completeJob", "raw_transaction": "0xbbbb"},
                    ],
                    "rpc_url": "http://127.0.0.1:1",
                    "timeout_seconds": 0.2,
                    "max_attempts": 1,
                },
            )
            item = queued["item"]

            dead_letter = self._wait_for_queue_item_status(node, item["id"], status="dead-letter", timeout=3.0)
            self.assertEqual(dead_letter["attempts"], 1)
            self.assertIsNotNone(dead_letter["last_relay_id"])

            _, requeued_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue/requeue",
                "token-settlement-requeue",
                {
                    "queue_id": item["id"],
                    "rpc_url": rpc.url,
                    "timeout_seconds": 10,
                    "max_attempts": 2,
                    "delay_seconds": 0,
                },
            )
            self.assertEqual(requeued_payload["item"]["status"], "queued")
            self.assertEqual(requeued_payload["item"]["attempts"], 0)
            self.assertEqual(requeued_payload["item"]["max_attempts"], 2)
            self.assertEqual(requeued_payload["item"]["payload"]["rpc_url"], rpc.url)

            completed = self._wait_for_queue_item_status(node, item["id"], status="completed", timeout=3.0)
            self.assertEqual(completed["attempts"], 1)
            self.assertIsNotNone(completed["last_relay_id"])
            self.assertEqual(len(rpc.calls), 2)

            _, relay_history = self._get(f"{node.base_url}/v1/onchain/settlement-relays?task_id=settlement-requeue-task-1")
            self.assertEqual(len(relay_history["items"]), 2)
            self.assertEqual(relay_history["items"][0]["final_status"], "completed")
            self.assertEqual(relay_history["items"][1]["final_status"], "failed")
        finally:
            node.stop()
            rpc.stop()

    def test_operator_can_cancel_and_delete_settlement_relay_queue_item(self) -> None:
        rpc = RpcHarness({"eth_sendRawTransaction": "0xcancelqueue"})
        rpc.start()
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="http://127.0.0.1:1",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:queue-cancel",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
        )
        node = NodeHarness(
            node_id="settlement-cancel-node",
            token="token-settlement-cancel",
            db_path=str(Path(self.tempdir.name) / "settlement-cancel.db"),
            capabilities=["worker"],
            onchain=onchain,
            settlement_relay_poll_seconds=0.1,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-settlement-cancel",
                {
                    "id": "settlement-cancel-task",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 47,
                },
            )
            self._complete_onchain_task(node, "token-settlement-cancel", "settlement-cancel-task", "worker-settlement-cancel")
            
            _, queued = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue",
                "token-settlement-cancel",
                {
                    "task_id": "settlement-cancel-task",
                    "raw_transactions": [
                        {"action": "submitWork", "raw_transaction": "0xaaaa"}
                    ],
                    "rpc_url": "http://127.0.0.1:1",
                    "timeout_seconds": 0.2,
                    "max_attempts": 1,
                    "delay_seconds": 30,
                },
            )
            item = queued["item"]

            # Cancel the item
            _, canceled_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue/cancel",
                "token-settlement-cancel",
                {"queue_id": item["id"]}
            )
            self.assertEqual(canceled_payload["item"]["status"], "dead-letter")
            self.assertEqual(canceled_payload["item"]["last_error"], "cancelled")

            # Delete the item
            _, delete_payload = self._post(
                f"{node.base_url}/v1/onchain/settlement-relay-queue/delete",
                "token-settlement-cancel",
                {"queue_id": item["id"]}
            )
            self.assertTrue(delete_payload["ok"])
            
            # Verify it's deleted
            status_code, items_payload = self._get_auth(
                f"{node.base_url}/v1/onchain/settlement-relay-queue?task_id=settlement-cancel-task",
                "token-settlement-cancel",
            )
            self.assertEqual(status_code, 200)
            self.assertEqual(len(items_payload["items"]), 0)

        finally:
            node.stop()
            rpc.stop()

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

    def test_runtime_adapter_claude_code_cli(self) -> None:
        node = NodeHarness(
            node_id="runtime-claude-code-node",
            token="token-claude-code",
            db_path=str(Path(self.tempdir.name) / "runtime-claude-code.db"),
            capabilities=["worker"],
            runtimes=["claude-code-cli"],
        )
        node.start()
        try:
            _, runtimes = self._get(f"{node.base_url}/v1/runtimes")
            runtime_names = {item["runtime"] for item in runtimes["items"]}
            self.assertIn("claude-code-cli", runtime_names)

            self._post(
                f"{node.base_url}/v1/tasks",
                "token-claude-code",
                {
                    "id": "runtime-claude-code-1",
                    "kind": "generic",
                    "role": "worker",
                    "payload": {"input": {"prompt": "hello claude code"}},
                },
            )
            bind_status, bound = self._post(
                f"{node.base_url}/v1/integrations/claude-code/bind",
                "token-claude-code",
                {
                    "task_id": "runtime-claude-code-1",
                    "command": [
                        sys.executable,
                        "-c",
                        (
                            "import json,sys;"
                            "prompt=sys.stdin.read().strip();"
                            "print(json.dumps({"
                            "'assistant_message': {'role': 'assistant', 'content': 'claude:' + prompt},"
                            "'provider': 'claude-code-cli'"
                            "}))"
                        ),
                    ],
                    "prompt": "hello claude code",
                    "prompt_transport": "stdin",
                    "timeout_seconds": 10,
                },
            )
            self.assertEqual(bind_status, 200)
            self.assertEqual(bound["provider"], "claude-code-cli")
            self.assertEqual(bound["runtime"]["runtime"], "claude-code-cli")

            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-claude-code",
                worker_id="worker-claude-code-1",
                capabilities=["worker"],
                lease_seconds=30,
                adapter_policy=AdapterPolicy(
                    allowed_runtime_kinds=["claude-code-cli"],
                    allow_subprocess=True,
                    allowed_commands=[sys.executable, Path(sys.executable).name],
                ),
            )
            self.assertTrue(worker.run_once())

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "runtime-claude-code-1"][0]
            self.assertEqual(task["result"]["adapter"]["protocol"], "claude-code-cli")
            self.assertEqual(task["result"]["runtime_execution"]["assistant_message"]["content"], "claude:hello claude code")
            self.assertEqual(task["result"]["runtime_execution"]["stdout_json"]["provider"], "claude-code-cli")
            self.assertEqual(task["result"]["runtime_execution"]["prompt_transport"], "stdin")
        finally:
            node.stop()

    def test_runtime_adapter_claude_http(self) -> None:
        gateway = ClaudeHttpHarness()
        gateway.start()
        node = NodeHarness(
            node_id="runtime-claude-http-node",
            token="token-claude-http",
            db_path=str(Path(self.tempdir.name) / "runtime-claude-http.db"),
            capabilities=["worker"],
            runtimes=["claude-http"],
        )
        node.start()
        try:
            _, runtimes = self._get(f"{node.base_url}/v1/runtimes")
            runtime_names = {item["runtime"] for item in runtimes["items"]}
            self.assertIn("claude-http", runtime_names)

            self._post(
                f"{node.base_url}/v1/tasks",
                "token-claude-http",
                {
                    "id": "runtime-claude-http-1",
                    "kind": "generic",
                    "role": "worker",
                    "payload": {"input": {"prompt": "hello remote claude"}},
                },
            )
            bind_status, bound = self._post(
                f"{node.base_url}/v1/integrations/claude-http/bind",
                "token-claude-http",
                {
                    "task_id": "runtime-claude-http-1",
                    "endpoint": gateway.url,
                    "model": "claude-3-7-sonnet-latest",
                    "auth_token": "anthropic-secret",
                    "system": "You are a coding assistant.",
                    "prompt": "hello remote claude",
                    "max_tokens": 256,
                    "timeout_seconds": 10,
                },
            )
            self.assertEqual(bind_status, 200)
            self.assertEqual(bound["provider"], "claude-http")
            self.assertEqual(bound["runtime"]["runtime"], "claude-http")

            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-claude-http",
                worker_id="worker-claude-http-1",
                capabilities=["worker"],
                lease_seconds=30,
                adapter_policy=AdapterPolicy(
                    allowed_runtime_kinds=["claude-http"],
                    allowed_http_hosts=["127.0.0.1"],
                ),
            )
            self.assertTrue(worker.run_once())

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "runtime-claude-http-1"][0]
            self.assertEqual(task["result"]["adapter"]["protocol"], "claude-http")
            self.assertEqual(task["result"]["runtime_execution"]["assistant_message"]["content"], "claude-http:hello remote claude")
            self.assertEqual(gateway.calls[0]["model"], "claude-3-7-sonnet-latest")
            self.assertEqual(gateway.calls[0]["system"], "You are a coding assistant.")
            headers = {str(key).lower(): value for key, value in gateway.headers[0].items()}
            self.assertEqual(headers["x-api-key"], "anthropic-secret")
            self.assertEqual(headers["anthropic-version"], "2023-06-01")
        finally:
            node.stop()
            gateway.stop()

    def test_runtime_adapter_claude_http_tool_use_blocks(self) -> None:
        gateway = ClaudeHttpHarness()
        gateway.start()
        node = NodeHarness(
            node_id="runtime-claude-http-tools-node",
            token="token-claude-http-tools",
            db_path=str(Path(self.tempdir.name) / "runtime-claude-http-tools.db"),
            capabilities=["worker"],
            runtimes=["claude-http"],
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-claude-http-tools",
                {
                    "id": "runtime-claude-http-tools-1",
                    "kind": "generic",
                    "role": "worker",
                    "payload": {"input": {"prompt": "lookup repository status"}},
                },
            )
            bind_status, bound = self._post(
                f"{node.base_url}/v1/integrations/claude-http/bind",
                "token-claude-http-tools",
                {
                    "task_id": "runtime-claude-http-tools-1",
                    "endpoint": gateway.url,
                    "model": "claude-3-7-sonnet-latest",
                    "auth_token": "anthropic-secret",
                    "prompt": "lookup repository status",
                    "tools": [
                        {
                            "name": "repo_status",
                            "description": "Inspect repository status",
                            "input_schema": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                            },
                        }
                    ],
                    "tool_choice": {"type": "tool", "name": "repo_status"},
                    "timeout_seconds": 10,
                },
            )
            self.assertEqual(bind_status, 200)
            self.assertEqual(bound["runtime"]["runtime"], "claude-http")

            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-claude-http-tools",
                worker_id="worker-claude-http-tools-1",
                capabilities=["worker"],
                lease_seconds=30,
                adapter_policy=AdapterPolicy(
                    allowed_runtime_kinds=["claude-http"],
                    allowed_http_hosts=["127.0.0.1"],
                ),
            )
            self.assertTrue(worker.run_once())

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "runtime-claude-http-tools-1"][0]
            self.assertEqual(task["result"]["adapter"]["protocol"], "claude-http")
            self.assertEqual(task["result"]["runtime_execution"]["tool_uses"][0]["name"], "repo_status")
            self.assertEqual(task["result"]["runtime_execution"]["tool_uses"][0]["input"]["echo"], "lookup repository status")
            self.assertEqual(gateway.calls[0]["tool_choice"]["name"], "repo_status")
            self.assertEqual(gateway.calls[0]["tools"][0]["name"], "repo_status")
            self.assertEqual(
                task["result"]["execution_receipt"]["artifacts"]["tool_uses"][0]["name"],
                "repo_status",
            )
        finally:
            node.stop()
            gateway.stop()

    def test_runtime_adapter_langgraph_http(self) -> None:
        langgraph = LangGraphHarness()
        langgraph.start()
        node = NodeHarness(
            node_id="runtime-langgraph-node",
            token="token-langgraph",
            db_path=str(Path(self.tempdir.name) / "runtime-langgraph.db"),
            capabilities=["worker"],
            runtimes=["langgraph-http"],
        )
        node.start()
        try:
            _, runtimes = self._get(f"{node.base_url}/v1/runtimes")
            runtime_names = {item["runtime"] for item in runtimes["items"]}
            self.assertIn("langgraph-http", runtime_names)
            descriptor = [item for item in runtimes["items"] if item["runtime"] == "langgraph-http"][0]
            self.assertTrue(descriptor["supports_http"])
            self.assertEqual(descriptor["output_modes"], ["run-state", "assistant-message", "json-object"])

            _, card = self._get(f"{node.base_url}/v1/card")
            self.assertIn("langgraph-http", card["runtime_capabilities"])

            self._post(
                f"{node.base_url}/v1/tasks",
                "token-langgraph",
                {
                    "id": "runtime-langgraph-1",
                    "kind": "generic",
                    "role": "worker",
                    "workflow_id": "wf-langgraph-1",
                    "payload": {"input": {"prompt": "hello graph"}},
                },
            )
            bind_status, bound = self._post(
                f"{node.base_url}/v1/runtimes/bind",
                "token-langgraph",
                {
                    "task_id": "runtime-langgraph-1",
                    "runtime": "langgraph-http",
                    "options": {
                        "endpoint": langgraph.url,
                        "assistant_id": "assistant-graph-1",
                        "config": {"recursion_limit": 5},
                        "timeout_seconds": 10,
                    },
                },
            )
            self.assertEqual(bind_status, 200)
            self.assertEqual(bound["runtime"]["runtime"], "langgraph-http")

            evaluate_status, evaluated = self._post(
                f"{node.base_url}/v1/tasks/dispatch/evaluate",
                "token-langgraph",
                {
                    "id": "runtime-langgraph-eval",
                    "kind": "generic",
                    "role": "worker",
                    "required_capabilities": ["worker"],
                    "payload": {
                        "_runtime": {
                            "runtime": "langgraph-http",
                        }
                    },
                },
            )
            self.assertEqual(evaluate_status, 200)
            self.assertEqual(evaluated["requirements"]["runtime"], "langgraph-http")
            self.assertEqual(evaluated["candidates"][0]["runtime_match"]["required"], "langgraph-http")
            self.assertTrue(evaluated["candidates"][0]["runtime_match"]["supported"])

            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-langgraph",
                worker_id="worker-langgraph-1",
                capabilities=["worker"],
                lease_seconds=30,
                adapter_policy=AdapterPolicy(
                    allowed_runtime_kinds=["langgraph-http"],
                    allowed_http_hosts=["127.0.0.1"],
                ),
            )
            self.assertTrue(worker.run_once())

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "runtime-langgraph-1"][0]
            self.assertEqual(task["result"]["adapter"]["protocol"], "langgraph-http")
            self.assertEqual(task["result"]["adapter"]["thread_id"], "wf-langgraph-1")
            self.assertEqual(task["result"]["runtime_execution"]["run_id"], "run-langgraph-1")
            self.assertEqual(task["result"]["runtime_execution"]["state"], "completed")
            self.assertEqual(task["result"]["runtime_execution"]["assistant_message"]["content"], 'langgraph:{"prompt": "hello graph"}')
            self.assertEqual(langgraph.calls[0]["thread_id"], "wf-langgraph-1")
            self.assertEqual(langgraph.calls[0]["assistant_id"], "assistant-graph-1")
            self.assertEqual(langgraph.calls[0]["config"]["recursion_limit"], 5)
            self.assertEqual(langgraph.calls[0]["input"], {"prompt": "hello graph"})
        finally:
            node.stop()
            langgraph.stop()

    def test_runtime_adapter_container_job_skeleton(self) -> None:
        workspace = Path(self.tempdir.name) / "container-workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        node = NodeHarness(
            node_id="runtime-container-node",
            token="token-container",
            db_path=str(Path(self.tempdir.name) / "runtime-container.db"),
            capabilities=["worker"],
            runtimes=["container-job"],
        )
        node.start()
        try:
            _, runtimes = self._get(f"{node.base_url}/v1/runtimes")
            runtime_names = {item["runtime"] for item in runtimes["items"]}
            self.assertIn("container-job", runtime_names)
            descriptor = [item for item in runtimes["items"] if item["runtime"] == "container-job"][0]
            self.assertTrue(descriptor["supports_local"])

            self._post(
                f"{node.base_url}/v1/tasks",
                "token-container",
                {
                    "id": "runtime-container-1",
                    "kind": "generic",
                    "role": "worker",
                    "payload": {"input": {"job": "build", "target": "api"}},
                },
            )
            bind_status, bound = self._post(
                f"{node.base_url}/v1/runtimes/bind",
                "token-container",
                {
                    "task_id": "runtime-container-1",
                    "runtime": "container-job",
                    "options": {
                        "image": "python:3.12-alpine",
                        "engine_command": [
                            sys.executable,
                            "-c",
                            (
                                "import json,os,pathlib;"
                                "task=json.loads(pathlib.Path(os.environ['AGENTCOIN_TASK_FILE']).read_text(encoding='utf-8'));"
                                "out={'task_id':task['id'],'image':os.environ.get('AGENTCOIN_IMAGE'),'worker_id':os.environ.get('AGENTCOIN_WORKER_ID')};"
                                "pathlib.Path(os.environ['AGENTCOIN_OUTPUT_FILE']).write_text(json.dumps(out),encoding='utf-8');"
                                "print(json.dumps({'status':'ok','task_id':task['id']}))"
                            ),
                        ],
                        "command": ["ignored-by-test-engine"],
                        "env": {"JOB_MODE": "ci"},
                        "timeout_seconds": 10,
                    },
                },
            )
            self.assertEqual(bind_status, 200)
            self.assertEqual(bound["runtime"]["runtime"], "container-job")

            evaluate_status, evaluated = self._post(
                f"{node.base_url}/v1/tasks/dispatch/evaluate",
                "token-container",
                {
                    "id": "runtime-container-eval",
                    "kind": "generic",
                    "role": "worker",
                    "required_capabilities": ["worker"],
                    "payload": {"_runtime": {"runtime": "container-job"}},
                },
            )
            self.assertEqual(evaluate_status, 200)
            self.assertEqual(evaluated["requirements"]["runtime"], "container-job")
            self.assertTrue(evaluated["candidates"][0]["runtime_match"]["supported"])

            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-container",
                worker_id="worker-container-1",
                capabilities=["worker"],
                lease_seconds=30,
                adapter_policy=AdapterPolicy(
                    allowed_runtime_kinds=["container-job"],
                    allow_subprocess=True,
                    allowed_commands=[sys.executable, Path(sys.executable).name],
                    workspace_root=str(workspace),
                ),
            )
            self.assertTrue(worker.run_once())

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "runtime-container-1"][0]
            execution = task["result"]["runtime_execution"]
            self.assertEqual(task["result"]["adapter"]["protocol"], "container-job")
            self.assertEqual(execution["image"], "python:3.12-alpine")
            self.assertEqual(execution["stdout_json"]["status"], "ok")
            self.assertEqual(execution["output_json"]["task_id"], "runtime-container-1")
            self.assertEqual(execution["output_json"]["image"], "python:3.12-alpine")
            self.assertEqual(execution["output_json"]["worker_id"], "worker-container-1")
            self.assertEqual(task["result"]["execution_receipt"]["artifacts"]["image"], "python:3.12-alpine")
        finally:
            node.stop()

    def test_runtime_adapter_openai_chat_for_openclaw_gateway(self) -> None:
        gateway = OpenAICompatHarness()
        gateway.start()
        node = NodeHarness(
            node_id="runtime-openai-node",
            token="token-openai",
            db_path=str(Path(self.tempdir.name) / "runtime-openai.db"),
            capabilities=["worker"],
            runtimes=["openai-chat"],
        )
        node.start()
        try:
            _, runtimes = self._get(f"{node.base_url}/v1/runtimes")
            runtime_names = {item["runtime"] for item in runtimes["items"]}
            self.assertIn("openai-chat", runtime_names)
            openai_runtime = [item for item in runtimes["items"] if item["runtime"] == "openai-chat"][0]
            self.assertTrue(openai_runtime["supports_structured_output"])
            self.assertTrue(openai_runtime["supports_json_schema"])

            _, card = self._get(f"{node.base_url}/v1/card")
            self.assertIn("runtime_capabilities", card)
            self.assertTrue(card["runtime_capabilities"]["openai-chat"]["supports_structured_output"])

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

    def test_runtime_adapter_openai_chat_supports_structured_output(self) -> None:
        gateway = OpenAICompatHarness()
        gateway.start()
        node = NodeHarness(
            node_id="runtime-openai-structured-node",
            token="token-openai-structured",
            db_path=str(Path(self.tempdir.name) / "runtime-openai-structured.db"),
            capabilities=["worker"],
            runtimes=["openai-chat"],
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-openai-structured",
                {
                    "id": "runtime-openai-structured-1",
                    "kind": "review",
                    "role": "reviewer",
                    "required_capabilities": ["reviewer"],
                    "payload": {"input": {"prompt": "review diff A"}},
                },
            )
            bind_status, bound = self._post(
                f"{node.base_url}/v1/runtimes/bind",
                "token-openai-structured",
                {
                    "task_id": "runtime-openai-structured-1",
                    "runtime": "openai-chat",
                    "options": {
                        "endpoint": gateway.url,
                        "model": "openclaw/gateway",
                        "prompt": "review diff A",
                        "auth_token": "gw-secret-token",
                        "structured_output": {
                            "name": "review_decision",
                            "strict": True,
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "decision": {"type": "string"},
                                    "summary": {"type": "string"},
                                },
                                "required": ["decision", "summary"],
                                "additionalProperties": False,
                            },
                        },
                        "timeout_seconds": 10,
                    },
                },
            )
            self.assertEqual(bind_status, 200)
            self.assertEqual(bound["runtime"]["runtime"], "openai-chat")

            evaluate_status, evaluated = self._post(
                f"{node.base_url}/v1/tasks/dispatch/evaluate",
                "token-openai-structured",
                {
                    "id": "runtime-openai-structured-eval",
                    "kind": "review",
                    "role": "reviewer",
                    "required_capabilities": ["worker"],
                    "payload": {
                        "_runtime": {
                            "runtime": "openai-chat",
                            "structured_output": {
                                "name": "review_decision",
                                "schema": {"type": "object"},
                            }
                        }
                    },
                },
            )
            self.assertEqual(evaluate_status, 200)
            self.assertTrue(evaluated["requirements"]["structured_output_required"])
            self.assertTrue(evaluated["requirements"]["json_schema_required"])
            self.assertEqual(evaluated["candidates"][0]["runtime_match"]["required"], "openai-chat")
            self.assertTrue(evaluated["candidates"][0]["runtime_match"]["structured_output_supported"])
            self.assertTrue(evaluated["candidates"][0]["runtime_match"]["json_schema_supported"])

            worker = WorkerLoop(
                node_url=node.base_url,
                token="token-openai-structured",
                worker_id="worker-openai-structured-1",
                capabilities=["worker", "reviewer"],
                lease_seconds=30,
                adapter_policy=AdapterPolicy(
                    allowed_runtime_kinds=["openai-chat"],
                    allowed_http_hosts=["127.0.0.1"],
                ),
            )
            self.assertTrue(worker.run_once())

            _, tasks = self._get(f"{node.base_url}/v1/tasks")
            task = [item for item in tasks["items"] if item["id"] == "runtime-openai-structured-1"][0]
            runtime_execution = task["result"]["runtime_execution"]
            self.assertEqual(runtime_execution["structured_output"]["decision"], "approve")
            self.assertEqual(runtime_execution["structured_output"]["summary"], "review diff A")
            self.assertEqual(gateway.calls[0]["response_format"]["type"], "json_schema")
            self.assertEqual(gateway.calls[0]["response_format"]["json_schema"]["name"], "review_decision")
            self.assertEqual(
                task["result"]["execution_receipt"]["artifacts"]["response_format"]["type"],
                "json_schema",
            )
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
            self.assertEqual(events["items"][1]["event_type"], "subjective-approve")

            _, summary = self._get(f"{node.base_url}/v1/poaw/summary?actor_id=worker-poaw-http&actor_type=worker")
            self.assertEqual(summary["event_count"], 2)
            self.assertEqual(summary["positive_points"], 14)
            self.assertEqual(summary["negative_points"], -15)
            self.assertEqual(summary["total_points"], -1)
            self.assertEqual(summary["poaw_policy_version"], "0.2")
            self.assertEqual(summary["reputation"]["violations"], 1)

            _, replay = self._get(f"{node.base_url}/v1/tasks/replay-inspect?task_id=poaw-task-1")
            self.assertEqual(replay["poaw_summary"]["event_count"], 2)
            self.assertEqual(len(replay["poaw_events"]), 2)
        finally:
            node.stop()

    def test_poaw_and_settlement_policies_are_configurable(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:policy-worker",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
            settlement_policy_version="0.2-test",
            settlement_complete_threshold=75,
            settlement_slash_negative_points_threshold=22,
        )
        node = NodeHarness(
            node_id="poaw-policy-node",
            token="token-poaw-policy",
            db_path=str(Path(self.tempdir.name) / "poaw-policy.db"),
            capabilities=["worker"],
            signing_secret="poaw-policy-secret",
            poaw_policy_version="0.3-test",
            poaw_score_weights={
                "worker_base": 20,
                "kind_code_bonus": 5,
                "workflow_bonus": 0,
                "required_capability_bonus_cap": 0,
                "approved_bonus": 0,
                "merged_bonus": 0,
            },
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-poaw-policy",
                {
                    "id": "poaw-policy-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 97,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-poaw-policy",
                {"worker_id": "worker-policy-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-poaw-policy",
                {
                    "task_id": "poaw-policy-task-1",
                    "worker_id": "worker-policy-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-policy-1"},
                },
            )

            _, summary = self._get(f"{node.base_url}/v1/poaw/summary?actor_id=worker-policy-1&actor_type=worker")
            self.assertEqual(summary["poaw_policy_version"], "0.3-test")
            self.assertEqual(summary["positive_points"], 25)
            self.assertEqual(summary["score_weights"]["worker_base"], 20)
            self.assertEqual(summary["score_weights"]["kind_code_bonus"], 5)

            _, preview = self._get(f"{node.base_url}/v1/onchain/settlement-preview?task_id=poaw-policy-task-1")
            settlement = preview["settlement"]
            self.assertEqual(settlement["settlement_policy"]["version"], "0.2-test")
            self.assertEqual(settlement["settlement_policy"]["complete_threshold"], 75)
            self.assertEqual(settlement["settlement_policy"]["challenge_negative_points_threshold"], 10)
            self.assertEqual(settlement["settlement_policy"]["network_trust_threshold"], 60)
            self.assertEqual(settlement["settlement_policy"]["slash_negative_points_threshold"], 22)
            self.assertEqual(settlement["score_breakdown"]["local_score"], 25)
            self.assertEqual(settlement["score_breakdown"]["network_trust_score"], 100)
        finally:
            node.stop()

    def test_settlement_preview_can_challenge_on_network_trust_threshold(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            did_registry_address="0x2222222222222222222222222222222222222222",
            staking_pool_address="0x3333333333333333333333333333333333333333",
            local_did="did:agentcoin:test:trust-worker",
            local_controller_address="0x4444444444444444444444444444444444444444",
            receipt_base_uri="ipfs://agentcoin-receipts",
            settlement_policy_version="0.2-trust",
            settlement_network_trust_threshold=120,
        )
        node = NodeHarness(
            node_id="settlement-trust-node",
            token="token-trust",
            db_path=str(Path(self.tempdir.name) / "settlement-trust.db"),
            capabilities=["worker"],
            signing_secret="trust-secret",
            onchain=onchain,
        )
        node.start()
        try:
            self._post(
                f"{node.base_url}/v1/tasks",
                "token-trust",
                {
                    "id": "settlement-trust-task-1",
                    "kind": "code",
                    "role": "worker",
                    "payload": {"x": 1},
                    "attach_onchain_context": True,
                    "onchain_job_id": 98,
                },
            )
            _, claim = self._post(
                f"{node.base_url}/v1/tasks/claim",
                "token-trust",
                {"worker_id": "worker-trust-1", "worker_capabilities": ["worker"], "lease_seconds": 30},
            )
            self._post(
                f"{node.base_url}/v1/tasks/ack",
                "token-trust",
                {
                    "task_id": "settlement-trust-task-1",
                    "worker_id": "worker-trust-1",
                    "lease_token": claim["task"]["lease_token"],
                    "success": True,
                    "result": {"done": True, "worker_id": "worker-trust-1"},
                },
            )

            _, preview = self._get(f"{node.base_url}/v1/onchain/settlement-preview?task_id=settlement-trust-task-1")
            settlement = preview["settlement"]
            self.assertEqual(settlement["recommended_resolution"], "challengeJob")
            self.assertEqual(settlement["settlement_policy"]["network_trust_threshold"], 120)
            self.assertEqual(settlement["score_breakdown"]["network_trust_score"], 100)
            self.assertTrue(settlement["resolution_params"]["evidence_hash"].startswith("0x"))
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
