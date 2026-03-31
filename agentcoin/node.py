from __future__ import annotations

import json
import logging
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request
from urllib.parse import urlparse

from agentcoin.config import NodeConfig
from agentcoin.models import TaskEnvelope
from agentcoin.store import NodeStore

LOG = logging.getLogger("agentcoin.node")


class AgentCoinNode:
    def __init__(self, config: NodeConfig) -> None:
        self.config = config
        self.store = NodeStore(config.database_path)
        self._server = ThreadingHTTPServer((config.host, config.port), self._build_handler())
        self._sync_stop = threading.Event()
        self._sync_thread = threading.Thread(target=self._sync_loop, name="agentcoin-outbox", daemon=True)

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        node = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "AgentCoin/0.1"

            def _json_response(self, status: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    return {}
                if length > node.config.max_body_bytes:
                    raise ValueError("request body too large")
                raw = self.rfile.read(length)
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))

            def _require_auth(self) -> bool:
                configured = node.config.auth_token.strip()
                if not configured:
                    return True
                header = self.headers.get("Authorization", "")
                if header == f"Bearer {configured}":
                    return True
                self._json_response(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return False

            def do_GET(self) -> None:
                if self.path == "/healthz":
                    self._json_response(
                        HTTPStatus.OK,
                        {
                            "status": "ok",
                            "node_id": node.config.node_id,
                            "stats": node.store.stats(),
                        },
                    )
                    return
                if self.path == "/v1/card":
                    self._json_response(HTTPStatus.OK, node.config.card.to_dict())
                    return
                if self.path == "/v1/tasks":
                    self._json_response(HTTPStatus.OK, {"items": node.store.list_tasks()})
                    return
                if self.path == "/v1/outbox":
                    self._json_response(HTTPStatus.OK, {"items": node.store.get_pending_outbox()})
                    return
                self._json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})

            def do_POST(self) -> None:
                try:
                    if self.path == "/v1/tasks":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        task = TaskEnvelope.from_dict(payload)
                        node.store.add_task(task)
                        if task.deliver_to:
                            node.store.queue_outbox(task.id, task.deliver_to, node.config.auth_token, task.to_dict())
                        self._json_response(HTTPStatus.CREATED, {"task": task.to_dict()})
                        return
                    if self.path == "/v1/inbox":
                        if not self._require_auth():
                            return
                        payload = self._read_json()
                        sender = str(payload.get("sender") or "peer")
                        message_id = node.store.receive_inbox(sender, payload)
                        node.store.add_task(TaskEnvelope.from_dict(payload))
                        self._json_response(HTTPStatus.CREATED, {"message_id": message_id})
                        return
                    if self.path == "/v1/outbox/flush":
                        if not self._require_auth():
                            return
                        flushed = node.flush_outbox()
                        self._json_response(HTTPStatus.OK, {"flushed": flushed, "stats": node.store.stats()})
                        return
                    self._json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})
                except ValueError as exc:
                    self._json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except json.JSONDecodeError:
                    self._json_response(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})

            def log_message(self, format: str, *args: object) -> None:
                LOG.info("%s - %s", self.address_string(), format % args)

        return Handler

    def flush_outbox(self) -> int:
        delivered = 0
        for item in self.store.get_pending_outbox():
            try:
                parsed = urlparse(item["target_url"])
                if parsed.scheme not in {"http", "https"}:
                    raise ValueError("unsupported target_url scheme")
                body = item["payload_json"].encode("utf-8")
                headers = {"Content-Type": "application/json"}
                if item["auth_token"]:
                    headers["Authorization"] = f"Bearer {item['auth_token']}"
                req = request.Request(
                    item["target_url"],
                    data=body,
                    headers=headers,
                    method="POST",
                )
                with request.urlopen(req, timeout=5) as resp:
                    if resp.status >= 300:
                        raise ValueError(f"peer returned status {resp.status}")
                self.store.mark_outbox_delivered(item["id"])
                delivered += 1
            except (error.URLError, TimeoutError, ValueError) as exc:
                self.store.mark_outbox_failed(item["id"], int(item["attempts"]) + 1, str(exc))
        return delivered

    def _sync_loop(self) -> None:
        while not self._sync_stop.wait(self.config.sync_interval_seconds):
            self.flush_outbox()

    def serve_forever(self) -> None:
        LOG.info("starting AgentCoin node on %s:%s", self.config.host, self.config.port)
        self._sync_thread.start()
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            LOG.info("received shutdown signal")
        finally:
            self._sync_stop.set()
            self._server.server_close()

    def shutdown(self) -> None:
        self._sync_stop.set()
        self._server.shutdown()
        self._server.server_close()
