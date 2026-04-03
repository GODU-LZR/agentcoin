from __future__ import annotations

import json
import subprocess
import threading
from typing import Any
from uuid import uuid4

from agentcoin.models import utc_now


class LocalAgentManager:
    def __init__(self) -> None:
        self._registrations: dict[str, dict[str, Any]] = {}
        self._processes: dict[str, subprocess.Popen[Any]] = {}
        self._acp_sessions: dict[str, dict[str, Any]] = {}
        self._acp_stdout_threads: dict[str, threading.Thread] = {}
        self._acp_stdout_frames: dict[str, list[dict[str, Any]]] = {}
        self._acp_lock = threading.Lock()

    def _capture_acp_stdout(self, registration_id: str, process: subprocess.Popen[Any]) -> None:
        stream = process.stdout
        if stream is None:
            return
        try:
            while True:
                line = stream.readline()
                if not line:
                    break
                raw = str(line).strip()
                if not raw:
                    continue
                frame: dict[str, Any] = {
                    "received_at": utc_now(),
                    "raw": raw,
                    "parsed": None,
                    "parse_error": None,
                }
                try:
                    frame["parsed"] = json.loads(raw)
                except json.JSONDecodeError as exc:
                    frame["parse_error"] = str(exc)
                with self._acp_lock:
                    self._acp_stdout_frames.setdefault(registration_id, []).append(frame)
        finally:
            with self._acp_lock:
                self._acp_stdout_threads.pop(registration_id, None)

    def _captured_frames_for_registration(self, registration_id: str) -> list[dict[str, Any]]:
        with self._acp_lock:
            return [dict(item) for item in self._acp_stdout_frames.get(registration_id, [])]

    @staticmethod
    def _summarize_latest_server_frame(frames: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not frames:
            return None
        latest = dict(frames[-1])
        parsed = latest.get("parsed")
        if isinstance(parsed, dict):
            latest["parsed"] = dict(parsed)
        return latest

    def _update_session_states_for_registration(self, registration_id: str, process_state: str) -> None:
        for record in self._acp_sessions.values():
            if str(record.get("registration_id") or "") != registration_id:
                continue
            record["process_state"] = process_state
            record["updated_at"] = utc_now()
            if process_state == "running":
                record["status"] = "open"
                record["handshake_state"] = "transport-ready"
                continue
            record["status"] = "stale"
            record["handshake_state"] = "transport-lost"

    def _refresh_status(self, registration_id: str) -> dict[str, Any] | None:
        record = self._registrations.get(registration_id)
        if not record:
            return None
        process = self._processes.get(registration_id)
        if process is None:
            return dict(record)
        return_code = process.poll()
        if return_code is None:
            record["status"] = "running"
            record["pid"] = int(process.pid or 0)
            self._update_session_states_for_registration(registration_id, "running")
            return dict(record)
        record["status"] = "exited" if int(return_code) == 0 else "failed"
        record["pid"] = None
        record["last_exit_code"] = int(return_code)
        record["stopped_at"] = utc_now()
        self._processes.pop(registration_id, None)
        self._update_session_states_for_registration(registration_id, record["status"])
        return dict(record)

    def list_registrations(self) -> list[dict[str, Any]]:
        for registration_id in list(self._registrations.keys()):
            self._refresh_status(registration_id)
        return [dict(item) for item in self._registrations.values()]

    def get_registration(self, registration_id: str) -> dict[str, Any] | None:
        return self._refresh_status(registration_id)

    def list_acp_sessions(self) -> list[dict[str, Any]]:
        active_sessions: list[dict[str, Any]] = []
        for session_id in list(self._acp_sessions.keys()):
            session = self.get_acp_session(session_id)
            if session:
                active_sessions.append(session)
        return active_sessions

    def get_acp_session(self, session_id: str) -> dict[str, Any] | None:
        record = self._acp_sessions.get(session_id)
        if not record:
            return None
        registration = self._refresh_status(str(record.get("registration_id") or ""))
        if not registration:
            self._acp_sessions.pop(session_id, None)
            return None
        if str(record.get("status") or "") == "closed":
            return dict(record)
        if str(registration.get("status") or "") != "running":
            record["status"] = "stale"
            record["process_state"] = str(registration.get("status") or "")
            record["handshake_state"] = "transport-lost"
            record["updated_at"] = utc_now()
        else:
            record["status"] = "open"
            record["process_state"] = "running"
            record["updated_at"] = utc_now()
            record["pid"] = registration.get("pid")
        frames = self._captured_frames_for_registration(str(record.get("registration_id") or ""))
        record["server_frames_seen"] = len(frames)
        latest_frame = self._summarize_latest_server_frame(frames)
        if latest_frame:
            record["latest_server_frame"] = latest_frame
            if bool(record.get("initialize_sent")):
                record["handshake_state"] = "initialize-response-captured"
                record["protocol_state"] = "server-response-captured"
                record["initialize_response_captured"] = True
                if not record.get("initialize_response_received_at"):
                    record["initialize_response_received_at"] = latest_frame.get("received_at")
        return dict(record)

    def _build_acp_initialize_intent(
        self,
        session_id: str,
        *,
        protocol_version: str,
        client_capabilities: dict[str, Any] | None = None,
        client_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client_capabilities = dict(client_capabilities or {})
        normalized_client_info = {
            "name": str((client_info or {}).get("name") or "agentcoin").strip() or "agentcoin",
            "title": str((client_info or {}).get("title") or "AgentCoin Local ACP Bridge").strip() or "AgentCoin Local ACP Bridge",
            "version": str((client_info or {}).get("version") or "0.1").strip() or "0.1",
        }
        request_id = str(uuid4())
        request = {
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "clientCapabilities": client_capabilities,
                "clientInfo": normalized_client_info,
            },
        }
        return {
            "kind": "agentcoin-acp-initialize-intent",
            "session_id": session_id,
            "transport": "stdio",
            "wire_format": "ndjson-json-candidate",
            "protocol_version": protocol_version,
            "client_capabilities": client_capabilities,
            "client_info": normalized_client_info,
            "request": request,
            "notes": [
                "AgentCoin currently emits a best-effort initialize frame candidate over NDJSON stdio.",
                "This is an ACP handshake skeleton and does not yet parse or validate a server response.",
            ],
            "generated_at": utc_now(),
        }

    def prepare_acp_initialize(
        self,
        session_id: str,
        *,
        protocol_version: str = "0.1-preview",
        client_capabilities: dict[str, Any] | None = None,
        client_info: dict[str, Any] | None = None,
        dispatch: bool = False,
    ) -> dict[str, Any]:
        session = self.get_acp_session(session_id)
        if not session:
            raise ValueError("acp session not found")
        if str(session.get("status") or "") != "open":
            raise ValueError("acp session is not open")
        registration_id = str(session.get("registration_id") or "")
        process = self._processes.get(registration_id)
        if process is None or process.stdin is None:
            raise ValueError("acp session transport is not writable")
        intent = self._build_acp_initialize_intent(
            session_id,
            protocol_version=protocol_version,
            client_capabilities=client_capabilities,
            client_info=client_info,
        )
        stored = self._acp_sessions[session_id]
        stored["initialize_intent"] = intent
        stored["last_client_frame"] = dict(intent.get("request") or {})
        stored["updated_at"] = utc_now()
        if dispatch:
            encoded = json.dumps(intent["request"], ensure_ascii=False, separators=(",", ":")) + "\n"
            process.stdin.write(encoded)
            process.stdin.flush()
            stored["initialize_sent"] = True
            stored["initialize_sent_at"] = utc_now()
            stored["handshake_state"] = "initialize-sent"
            stored["protocol_state"] = "server-capabilities-pending"
        else:
            stored["initialize_sent"] = False
            stored["handshake_state"] = "initialize-prepared"
            stored["protocol_state"] = "initialize-dispatch-pending"
        return {"session": dict(stored), "initialize_intent": intent, "dispatched": bool(dispatch)}

    def poll_acp_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_acp_session(session_id)
        if not session:
            raise ValueError("acp session not found")
        registration_id = str(session.get("registration_id") or "")
        frames = self._captured_frames_for_registration(registration_id)
        refreshed = self.get_acp_session(session_id)
        return {
            "session": refreshed or session,
            "captured_frames": frames,
            "latest_server_frame": self._summarize_latest_server_frame(frames),
        }

    def register_discovered_agent(
        self,
        discovered_item: dict[str, Any],
        *,
        registration_id: str | None = None,
    ) -> dict[str, Any]:
        discovered_id = str(discovered_item.get("id") or "").strip()
        if not discovered_id:
            raise ValueError("discovered agent id is required")
        launch_hint = list(discovered_item.get("agentcoin_compatibility", {}).get("launch_hint") or [])
        record = {
            "registration_id": registration_id or f"local-{discovered_id}",
            "discovered_id": discovered_id,
            "title": str(discovered_item.get("title") or discovered_id),
            "family": str(discovered_item.get("family") or ""),
            "type": str(discovered_item.get("type") or ""),
            "publisher": str(discovered_item.get("publisher") or ""),
            "protocols": list(discovered_item.get("protocols") or []),
            "preferred_integration": str(discovered_item.get("agentcoin_compatibility", {}).get("preferred_integration") or ""),
            "integration_candidates": list(discovered_item.get("agentcoin_compatibility", {}).get("integration_candidates") or []),
            "attachable_today": bool(discovered_item.get("agentcoin_compatibility", {}).get("attachable_today")),
            "launch_command": launch_hint,
            "launch_cwd": str(discovered_item.get("cwd") or "").strip() or None,
            "launch_env": dict(discovered_item.get("env") or {}),
            "status": "registered",
            "pid": None,
            "registered_at": utc_now(),
            "started_at": None,
            "stopped_at": None,
            "last_error": None,
            "last_exit_code": None,
            "discovered_item": dict(discovered_item),
        }
        self._registrations[record["registration_id"]] = record
        return dict(record)

    def start_registration(self, registration_id: str) -> dict[str, Any]:
        record = self._refresh_status(registration_id)
        if not record:
            raise ValueError("local agent registration not found")
        if record["status"] == "running":
            return record
        command = [str(item).strip() for item in list(record.get("launch_command") or []) if str(item).strip()]
        if not command:
            raise ValueError("local agent registration does not include a launch command")
        cwd = str(record.get("launch_cwd") or "").strip() or None
        env = dict(record.get("launch_env") or {})
        protocols = {str(item).strip().lower() for item in list(record.get("protocols") or []) if str(item).strip()}
        stdio_enabled = "acp" in protocols
        process = subprocess.Popen(
            command,
            cwd=cwd or None,
            env={**env} if env else None,
            stdout=subprocess.PIPE if stdio_enabled else subprocess.DEVNULL,
            stderr=subprocess.PIPE if stdio_enabled else subprocess.DEVNULL,
            stdin=subprocess.PIPE if stdio_enabled else subprocess.DEVNULL,
            shell=False,
            text=stdio_enabled,
        )
        stored = self._registrations[registration_id]
        stored["status"] = "running"
        stored["pid"] = int(process.pid or 0)
        stored["started_at"] = utc_now()
        stored["stopped_at"] = None
        stored["last_error"] = None
        stored["last_exit_code"] = None
        stored["transport"] = "stdio" if stdio_enabled else "subprocess"
        self._processes[registration_id] = process
        if stdio_enabled:
            with self._acp_lock:
                self._acp_stdout_frames[registration_id] = []
            thread = threading.Thread(
                target=self._capture_acp_stdout,
                args=(registration_id, process),
                name=f"agentcoin-acp-{registration_id}",
                daemon=True,
            )
            self._acp_stdout_threads[registration_id] = thread
            thread.start()
        self._update_session_states_for_registration(registration_id, "running")
        return dict(stored)

    def stop_registration(self, registration_id: str) -> dict[str, Any]:
        record = self._refresh_status(registration_id)
        if not record:
            raise ValueError("local agent registration not found")
        process = self._processes.get(registration_id)
        if process is None:
            stored = self._registrations[registration_id]
            stored["status"] = "stopped"
            stored["pid"] = None
            stored["stopped_at"] = utc_now()
            return dict(stored)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        stored = self._registrations[registration_id]
        stored["status"] = "stopped"
        stored["pid"] = None
        stored["stopped_at"] = utc_now()
        stored["last_exit_code"] = int(process.returncode or 0)
        self._processes.pop(registration_id, None)
        for stream_name in ("stdin", "stdout", "stderr"):
            stream = getattr(process, stream_name, None)
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:
                continue
        reader = self._acp_stdout_threads.pop(registration_id, None)
        if reader and reader.is_alive():
            reader.join(timeout=1)
        self._update_session_states_for_registration(registration_id, "stopped")
        return dict(stored)

    def open_acp_session(self, registration_id: str) -> dict[str, Any]:
        registration = self._refresh_status(registration_id)
        if not registration:
            raise ValueError("local agent registration not found")
        protocols = {str(item).strip().lower() for item in list(registration.get("protocols") or []) if str(item).strip()}
        if "acp" not in protocols:
            raise ValueError("local agent registration does not support acp")
        for existing_id in list(self._acp_sessions.keys()):
            existing = self.get_acp_session(existing_id)
            if not existing:
                continue
            if str(existing.get("registration_id") or "") != registration_id:
                continue
            if str(existing.get("status") or "") == "open":
                return existing
            self._acp_sessions.pop(existing_id, None)
        if str(registration.get("status") or "") != "running":
            registration = self.start_registration(registration_id)
        session_id = str(uuid4())
        session = {
            "session_id": session_id,
            "registration_id": registration_id,
            "protocol": "acp",
            "transport": "stdio",
            "status": "open",
            "process_state": str(registration.get("status") or ""),
            "pid": registration.get("pid"),
            "handshake_state": "transport-ready",
            "protocol_state": "initialize-pending",
            "initialize_sent": False,
            "attachable_today": False,
            "notes": [
                "ACP process transport is ready, but AgentCoin has not yet exchanged ACP protocol messages.",
                "This session is a transport and lifecycle skeleton, not a full ACP bridge.",
            ],
            "opened_at": utc_now(),
            "updated_at": utc_now(),
        }
        self._acp_sessions[session_id] = session
        return dict(session)

    def close_acp_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_acp_session(session_id)
        if not session:
            raise ValueError("acp session not found")
        stored = self._acp_sessions.pop(str(session.get("session_id") or ""))
        stored["status"] = "closed"
        stored["handshake_state"] = "closed"
        stored["updated_at"] = utc_now()
        stored["closed_at"] = utc_now()
        return dict(stored)

    def shutdown(self) -> None:
        self._acp_sessions.clear()
        for registration_id in list(self._processes.keys()):
            try:
                self.stop_registration(registration_id)
            except Exception:
                continue
