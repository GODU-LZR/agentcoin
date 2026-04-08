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
    def _iso_timestamp_sort_key(value: Any) -> str:
        return str(value or "").replace("Z", "+00:00")

    @staticmethod
    def _summarize_latest_server_frame(frames: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not frames:
            return None
        latest = dict(frames[-1])
        parsed = latest.get("parsed")
        if isinstance(parsed, dict):
            latest["parsed"] = dict(parsed)
        return latest

    @staticmethod
    def _frame_for_request_id(frames: list[dict[str, Any]], request_id: str | None) -> dict[str, Any] | None:
        normalized_request_id = str(request_id or "").strip()
        if not normalized_request_id:
            return None
        for frame in reversed(frames):
            parsed = frame.get("parsed")
            if not isinstance(parsed, dict):
                continue
            if str(parsed.get("id") or "").strip() != normalized_request_id:
                continue
            matched = dict(frame)
            matched_parsed = matched.get("parsed")
            if isinstance(matched_parsed, dict):
                matched["parsed"] = dict(matched_parsed)
            return matched
        return None

    @staticmethod
    def _notification_frames_for_method(
        frames: list[dict[str, Any]],
        method_name: str,
        *,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_method_name = str(method_name or "").strip()
        normalized_session_id = str(session_id or "").strip()
        if not normalized_method_name:
            return []
        matches: list[dict[str, Any]] = []
        for frame in frames:
            parsed = frame.get("parsed")
            if not isinstance(parsed, dict):
                continue
            if str(parsed.get("method") or "").strip() != normalized_method_name:
                continue
            if normalized_session_id:
                params = parsed.get("params")
                if not isinstance(params, dict):
                    continue
                if str(params.get("sessionId") or params.get("session_id") or "").strip() != normalized_session_id:
                    continue
            matched = dict(frame)
            matched_parsed = matched.get("parsed")
            if isinstance(matched_parsed, dict):
                matched["parsed"] = dict(matched_parsed)
            matches.append(matched)
        return matches

    @staticmethod
    def _normalize_listed_sessions(frame: dict[str, Any] | None) -> tuple[list[dict[str, Any]], str | None]:
        if not isinstance(frame, dict):
            return [], None
        parsed = frame.get("parsed")
        if not isinstance(parsed, dict):
            return [], None
        result = parsed.get("result")
        if not isinstance(result, dict):
            return [], None
        sessions: list[dict[str, Any]] = []
        for item in list(result.get("sessions") or []):
            if not isinstance(item, dict):
                continue
            session_id = str(item.get("sessionId") or item.get("session_id") or "").strip()
            if not session_id:
                continue
            normalized_item = dict(item)
            normalized_item["sessionId"] = session_id
            cwd = str(item.get("cwd") or "").strip()
            if cwd:
                normalized_item["cwd"] = cwd
            title = str(item.get("title") or "").strip()
            if title:
                normalized_item["title"] = title
            updated_at = str(item.get("updatedAt") or item.get("updated_at") or "").strip()
            if updated_at:
                normalized_item["updatedAt"] = updated_at
            sessions.append(normalized_item)
        next_cursor = str(result.get("nextCursor") or result.get("next_cursor") or "").strip() or None
        return sessions, next_cursor

    @staticmethod
    def _normalize_acp_protocol_version(protocol_version: Any) -> int | float:
        if isinstance(protocol_version, bool):
            raise ValueError("protocol_version must be numeric")
        if isinstance(protocol_version, (int, float)):
            return protocol_version
        normalized = str(protocol_version or "").strip()
        if not normalized:
            return 1
        if normalized.lower() == "0.1-preview":
            return 1
        try:
            return int(normalized)
        except ValueError:
            pass
        try:
            return float(normalized)
        except ValueError as exc:
            raise ValueError("protocol_version must be numeric or a supported ACP preview alias") from exc

    @staticmethod
    def _turns_with_responses(
        turns: list[dict[str, Any]],
        frames: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        hydrated: list[dict[str, Any]] = []
        for turn in turns:
            turn_copy = dict(turn)
            request = dict(turn_copy.get("request") or {})
            request_id = str(request.get("id") or "").strip()
            response_frame = LocalAgentManager._frame_for_request_id(frames, request_id)
            if response_frame:
                turn_copy["response_frame"] = response_frame
                turn_copy["response_captured"] = True
                if not turn_copy.get("response_received_at"):
                    turn_copy["response_received_at"] = response_frame.get("received_at")
            else:
                turn_copy["response_captured"] = False
            hydrated.append(turn_copy)
        return hydrated

    @staticmethod
    def _session_summary(
        record: dict[str, Any],
        turns: list[dict[str, Any]],
        frames: list[dict[str, Any]],
    ) -> dict[str, Any]:
        active_turn: dict[str, Any] | None = None
        pending_request_ids: list[str] = []
        response_turns: list[dict[str, Any]] = []
        for turn in turns:
            request = dict(turn.get("request") or {})
            request_id = str(request.get("id") or "").strip()
            if request_id and not bool(turn.get("response_captured")):
                pending_request_ids.append(request_id)
            if bool(turn.get("response_captured")):
                response_turns.append(turn)
        for turn in reversed(turns):
            if not bool(turn.get("response_captured")):
                active_turn = turn
                break
        if active_turn is None and turns:
            active_turn = turns[-1]
        latest_server_frame = LocalAgentManager._summarize_latest_server_frame(frames)
        latest_server_frame_id = None
        if isinstance(latest_server_frame, dict):
            parsed = latest_server_frame.get("parsed")
            if isinstance(parsed, dict):
                latest_server_frame_id = str(parsed.get("id") or "").strip() or None
        last_response_received_at = None
        if response_turns:
            response_turn = response_turns[-1]
            last_response_received_at = response_turn.get("response_received_at")
        elif latest_server_frame:
            last_response_received_at = latest_server_frame.get("received_at")
        active_request = dict((active_turn or {}).get("request") or {})
        active_task_ref = dict((active_turn or {}).get("task_ref") or {})
        return {
            "turn_count": len(turns),
            "active_turn_id": (active_turn or {}).get("turn_id"),
            "active_phase": (active_turn or {}).get("phase"),
            "active_request_id": str(active_request.get("id") or "").strip() or None,
            "active_task_id": str(active_task_ref.get("task_id") or "").strip() or None,
            "active_response_captured": bool((active_turn or {}).get("response_captured")),
            "pending_request_ids": pending_request_ids,
            "latest_server_frame_id": latest_server_frame_id,
            "latest_server_frame_received_at": (latest_server_frame or {}).get("received_at"),
            "last_response_received_at": last_response_received_at,
            "handshake_state": str(record.get("handshake_state") or ""),
            "protocol_state": str(record.get("protocol_state") or ""),
            "status": str(record.get("status") or ""),
        }

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
        if str(record.get("status") or "") == "closed":
            turns = list(record.get("turns") or [])
            record["summary"] = self._session_summary(record, turns, [])
            return dict(record)
        registration = self._refresh_status(str(record.get("registration_id") or ""))
        if not registration:
            self._acp_sessions.pop(session_id, None)
            return None
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
        turns = self._turns_with_responses(list(record.get("turns") or []), frames)
        if turns:
            record["turns"] = turns
        initialize_response_frame = self._frame_for_request_id(frames, record.get("initialize_request_id"))
        if initialize_response_frame:
            record["initialize_response_frame"] = initialize_response_frame
            if bool(record.get("initialize_sent")):
                record["handshake_state"] = "initialize-response-captured"
                record["protocol_state"] = "server-response-captured"
                record["initialize_response_captured"] = True
                record["initialize_response_received_at"] = initialize_response_frame.get("received_at")
        session_list_response_frame = self._frame_for_request_id(frames, record.get("session_list_request_id"))
        if session_list_response_frame:
            record["session_list_response_frame"] = session_list_response_frame
            listed_sessions, next_cursor = self._normalize_listed_sessions(session_list_response_frame)
            record["listed_server_sessions"] = listed_sessions
            record["session_list_next_cursor"] = next_cursor
            if bool(record.get("session_list_sent")):
                record["protocol_state"] = "session-list-response-captured"
                record["session_list_response_captured"] = True
                record["session_list_response_received_at"] = session_list_response_frame.get("received_at")
        elif bool(record.get("session_list_sent")) and str(record.get("session_list_request_id") or "").strip():
            record.pop("session_list_response_frame", None)
            record["session_list_response_captured"] = False
            record["session_list_response_received_at"] = None
            record["protocol_state"] = "session-list-response-pending"
        session_load_response_frame = self._frame_for_request_id(frames, record.get("session_load_request_id"))
        if session_load_response_frame:
            record["session_load_response_frame"] = session_load_response_frame
            if bool(record.get("session_load_sent")):
                record["protocol_state"] = "session-load-response-captured"
                record["session_load_response_captured"] = True
                record["session_load_response_received_at"] = session_load_response_frame.get("received_at")
        elif bool(record.get("session_load_sent")) and str(record.get("session_load_request_id") or "").strip():
            record.pop("session_load_response_frame", None)
            record["session_load_response_captured"] = False
            record["session_load_response_received_at"] = None
            record["protocol_state"] = "session-load-response-pending"
        loaded_server_session_id = str(record.get("loaded_server_session_id") or "").strip()
        if loaded_server_session_id:
            loaded_session_updates = self._notification_frames_for_method(
                frames,
                "session/update",
                session_id=loaded_server_session_id,
            )
            task_frame_start = max(0, int(record.get("task_request_frame_start") or 0))
            task_response_frame = self._frame_for_request_id(frames, record.get("task_request_id"))
            task_response_received_at = ""
            if task_response_frame:
                task_response_received_at = str(task_response_frame.get("received_at") or "")
            relevant_updates: list[dict[str, Any]] = []
            for update_frame in loaded_session_updates:
                parsed_update = update_frame.get("parsed")
                if not isinstance(parsed_update, dict):
                    continue
                received_at = str(update_frame.get("received_at") or "")
                if task_frame_start and self._iso_timestamp_sort_key(received_at) < self._iso_timestamp_sort_key(
                    record.get("task_request_sent_at")
                ):
                    continue
                if task_response_received_at and self._iso_timestamp_sort_key(received_at) > self._iso_timestamp_sort_key(
                    task_response_received_at
                ):
                    continue
                relevant_updates.append(update_frame)
            if not relevant_updates:
                relevant_updates = loaded_session_updates
            record["loaded_session_update_count"] = len(relevant_updates)
            if relevant_updates:
                record["latest_loaded_session_update"] = relevant_updates[-1]
        task_response_frame = self._frame_for_request_id(frames, record.get("task_request_id"))
        if task_response_frame:
            record["task_response_frame"] = task_response_frame
            if bool(record.get("task_request_sent")):
                record["protocol_state"] = "task-response-captured"
                record["task_response_captured"] = True
                record["latest_task_response_frame"] = task_response_frame
                record["task_response_received_at"] = task_response_frame.get("received_at")
        elif bool(record.get("task_request_sent")) and str(record.get("task_request_id") or "").strip():
            record.pop("task_response_frame", None)
            record.pop("latest_task_response_frame", None)
            record["task_response_captured"] = False
            record["task_response_received_at"] = None
            record["protocol_state"] = "task-response-pending"
        record["summary"] = self._session_summary(record, list(record.get("turns") or []), frames)
        return dict(record)

    def _build_acp_initialize_intent(
        self,
        session_id: str,
        *,
        protocol_version: Any,
        client_capabilities: dict[str, Any] | None = None,
        client_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client_capabilities = dict(client_capabilities or {})
        normalized_protocol_version = self._normalize_acp_protocol_version(protocol_version)
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
                "protocolVersion": normalized_protocol_version,
                "clientCapabilities": client_capabilities,
                "clientInfo": normalized_client_info,
            },
        }
        return {
            "kind": "agentcoin-acp-initialize-intent",
            "session_id": session_id,
            "transport": "stdio",
            "wire_format": "ndjson-json-candidate",
            "protocol_version": normalized_protocol_version,
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
        protocol_version: Any = 1,
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
        stored["initialize_request_id"] = str(intent.get("request", {}).get("id") or "")
        stored["last_client_frame"] = dict(intent.get("request") or {})
        stored["updated_at"] = utc_now()
        turns = list(stored.get("turns") or [])
        turns.append(
            {
                "turn_id": str(uuid4()),
                "phase": "initialize",
                "request": dict(intent.get("request") or {}),
                "request_sent": bool(dispatch),
                "requested_at": utc_now(),
            }
        )
        stored["turns"] = turns
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
        stored["summary"] = self._session_summary(stored, list(stored.get("turns") or []), [])
        return {"session": dict(stored), "initialize_intent": intent, "dispatched": bool(dispatch)}

    def _build_acp_session_list_intent(
        self,
        session_id: str,
        *,
        cwd: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        request_id = str(uuid4())
        params: dict[str, Any] = {}
        normalized_cwd = str(cwd or "").strip()
        normalized_cursor = str(cursor or "").strip()
        if normalized_cwd:
            params["cwd"] = normalized_cwd
        if normalized_cursor:
            params["cursor"] = normalized_cursor
        request = {
            "id": request_id,
            "method": "session/list",
            "params": params,
        }
        return {
            "kind": "agentcoin-acp-session-list-intent",
            "session_id": session_id,
            "transport": "stdio",
            "wire_format": "ndjson-json-candidate",
            "request": request,
            "filters": {
                "cwd": normalized_cwd or None,
                "cursor": normalized_cursor or None,
            },
            "notes": [
                "AgentCoin requests ACP session discovery over stdio using the session/list method.",
                "Returned session metadata is captured and surfaced in the local ACP workspace.",
            ],
            "generated_at": utc_now(),
        }

    def prepare_acp_session_list(
        self,
        session_id: str,
        *,
        cwd: str | None = None,
        cursor: str | None = None,
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
        intent = self._build_acp_session_list_intent(session_id, cwd=cwd, cursor=cursor)
        stored = self._acp_sessions[session_id]
        stored["last_session_list_intent"] = intent
        stored["session_list_request_id"] = str(intent.get("request", {}).get("id") or "")
        stored["last_client_frame"] = dict(intent.get("request") or {})
        stored["updated_at"] = utc_now()
        turns = list(stored.get("turns") or [])
        turns.append(
            {
                "turn_id": str(uuid4()),
                "phase": "session-list",
                "request": dict(intent.get("request") or {}),
                "request_sent": bool(dispatch),
                "requested_at": utc_now(),
            }
        )
        stored["turns"] = turns
        if dispatch:
            encoded = json.dumps(intent["request"], ensure_ascii=False, separators=(",", ":")) + "\n"
            process.stdin.write(encoded)
            process.stdin.flush()
            stored["session_list_sent"] = True
            stored["session_list_sent_at"] = utc_now()
            stored["protocol_state"] = "session-list-response-pending"
        else:
            stored["session_list_sent"] = False
            stored["protocol_state"] = "session-list-dispatch-pending"
        stored["summary"] = self._session_summary(stored, list(stored.get("turns") or []), [])
        return {"session": dict(stored), "session_list_intent": intent, "dispatched": bool(dispatch)}

    def _build_acp_session_load_intent(
        self,
        session_id: str,
        *,
        server_session_id: str,
        cwd: str,
        mcp_servers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        request_id = str(uuid4())
        request = {
            "id": request_id,
            "method": "session/load",
            "params": {
                "sessionId": server_session_id,
                "cwd": cwd,
                "mcpServers": [dict(item) for item in list(mcp_servers or []) if isinstance(item, dict)],
            },
        }
        return {
            "kind": "agentcoin-acp-session-load-intent",
            "session_id": session_id,
            "server_session_id": server_session_id,
            "transport": "stdio",
            "wire_format": "ndjson-json-candidate",
            "request": request,
            "notes": [
                "AgentCoin resumes a remote ACP session using the session/load method.",
                "Conversation replay is captured from session/update notifications on the same server session id.",
            ],
            "generated_at": utc_now(),
        }

    def prepare_acp_session_load(
        self,
        session_id: str,
        *,
        server_session_id: str,
        cwd: str,
        mcp_servers: list[dict[str, Any]] | None = None,
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
        normalized_server_session_id = str(server_session_id or "").strip()
        if not normalized_server_session_id:
            raise ValueError("server_session_id is required")
        normalized_cwd = str(cwd or "").strip()
        if not normalized_cwd:
            raise ValueError("cwd is required")
        intent = self._build_acp_session_load_intent(
            session_id,
            server_session_id=normalized_server_session_id,
            cwd=normalized_cwd,
            mcp_servers=mcp_servers,
        )
        stored = self._acp_sessions[session_id]
        stored["last_session_load_intent"] = intent
        stored["session_load_request_id"] = str(intent.get("request", {}).get("id") or "")
        stored["loaded_server_session_id"] = normalized_server_session_id
        stored["last_client_frame"] = dict(intent.get("request") or {})
        stored.pop("session_load_response_frame", None)
        stored["session_load_response_captured"] = False
        stored["session_load_response_received_at"] = None
        stored["loaded_session_update_count"] = 0
        stored.pop("latest_loaded_session_update", None)
        stored["updated_at"] = utc_now()
        turns = list(stored.get("turns") or [])
        turns.append(
            {
                "turn_id": str(uuid4()),
                "phase": "session-load",
                "request": dict(intent.get("request") or {}),
                "request_sent": bool(dispatch),
                "server_session_id": normalized_server_session_id,
                "requested_at": utc_now(),
            }
        )
        stored["turns"] = turns
        if dispatch:
            encoded = json.dumps(intent["request"], ensure_ascii=False, separators=(",", ":")) + "\n"
            process.stdin.write(encoded)
            process.stdin.flush()
            stored["session_load_sent"] = True
            stored["session_load_sent_at"] = utc_now()
            stored["protocol_state"] = "session-load-response-pending"
        else:
            stored["session_load_sent"] = False
            stored["protocol_state"] = "session-load-dispatch-pending"
        stored["summary"] = self._session_summary(stored, list(stored.get("turns") or []), [])
        return {"session": dict(stored), "session_load_intent": intent, "dispatched": bool(dispatch)}

    def _build_acp_task_request_intent(
        self,
        session_id: str,
        *,
        server_session_id: str,
        prompt_text: str,
        task_ref: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_id = str(uuid4())
        request = {
            "id": request_id,
            "method": "session/prompt",
            "params": {
                "sessionId": server_session_id,
                "prompt": [{"type": "text", "text": prompt_text}],
            },
        }
        return {
            "kind": "agentcoin-acp-task-request-intent",
            "session_id": session_id,
            "server_session_id": server_session_id,
            "transport": "stdio",
            "wire_format": "ndjson-json-candidate",
            "task_ref": dict(task_ref or {}),
            "request": request,
            "mapping": {
                "agentcoin_kind": str((task_ref or {}).get("kind") or ""),
                "agentcoin_role": str((task_ref or {}).get("role") or ""),
                "agentcoin_task_id": str((task_ref or {}).get("task_id") or ""),
                "prompt_text_source": "task",
            },
            "notes": [
                "AgentCoin maps a local task into an ACP session/prompt request candidate.",
                "This is still a thin ACP prompt bridge and does not yet implement client-side ACP tool or permission handlers.",
            ],
            "generated_at": utc_now(),
        }

    def prepare_acp_task_request(
        self,
        session_id: str,
        *,
        server_session_id: str,
        prompt_text: str,
        task_ref: dict[str, Any] | None = None,
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
        normalized_server_session_id = str(server_session_id or "").strip()
        if not normalized_server_session_id:
            raise ValueError("server_session_id is required")
        normalized_prompt_text = str(prompt_text or "").strip()
        if not normalized_prompt_text:
            raise ValueError("prompt_text is required")
        stored = self._acp_sessions[session_id]
        loaded_server_session_id = str(stored.get("loaded_server_session_id") or "").strip()
        if (
            loaded_server_session_id
            and normalized_server_session_id == loaded_server_session_id
            and bool(stored.get("session_load_sent"))
            and not bool(stored.get("session_load_response_captured"))
        ):
            raise ValueError("acp session/load response is still pending for this server_session_id")
        intent = self._build_acp_task_request_intent(
            session_id,
            server_session_id=normalized_server_session_id,
            prompt_text=normalized_prompt_text,
            task_ref=task_ref,
        )
        stored["last_task_request_intent"] = intent
        stored["task_request_id"] = str(intent.get("request", {}).get("id") or "")
        stored["last_client_frame"] = dict(intent.get("request") or {})
        stored["task_request_frame_start"] = len(self._captured_frames_for_registration(registration_id))
        stored.pop("task_response_frame", None)
        stored.pop("latest_task_response_frame", None)
        stored["task_response_captured"] = False
        stored["task_response_received_at"] = None
        stored["updated_at"] = utc_now()
        turns = list(stored.get("turns") or [])
        turns.append(
            {
                "turn_id": str(uuid4()),
                "phase": "task-request",
                "request": dict(intent.get("request") or {}),
                "request_sent": bool(dispatch),
                "task_ref": dict(task_ref or {}),
                "requested_at": utc_now(),
            }
        )
        stored["turns"] = turns
        if dispatch:
            encoded = json.dumps(intent["request"], ensure_ascii=False, separators=(",", ":")) + "\n"
            process.stdin.write(encoded)
            process.stdin.flush()
            stored["task_request_sent"] = True
            stored["task_request_sent_at"] = utc_now()
            stored["protocol_state"] = "task-response-pending"
        else:
            stored["task_request_sent"] = False
            stored["protocol_state"] = "task-request-dispatch-pending"
        stored["summary"] = self._session_summary(stored, list(stored.get("turns") or []), [])
        return {"session": dict(stored), "task_request_intent": intent, "dispatched": bool(dispatch)}

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
            "initialize_response_frame": self._frame_for_request_id(frames, (refreshed or session).get("initialize_request_id")),
            "task_response_frame": self._frame_for_request_id(frames, (refreshed or session).get("task_request_id")),
            "turns": list((refreshed or session).get("turns") or []),
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
                return {
                    "session": existing,
                    "reused_existing_session": True,
                }
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
            "attachable_today": bool(registration.get("attachable_today")),
            "turns": [],
            "notes": [
                "ACP process transport is ready for initialize, session/list, session/load, and session/prompt dispatch.",
                "AgentCoin still lacks client-side ACP tool, file-system, terminal, and permission handlers.",
            ],
            "opened_at": utc_now(),
            "updated_at": utc_now(),
        }
        session["summary"] = self._session_summary(session, [], [])
        self._acp_sessions[session_id] = session
        return {
            "session": dict(session),
            "reused_existing_session": False,
        }

    def close_acp_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_acp_session(session_id)
        if not session:
            raise ValueError("acp session not found")
        stored = self._acp_sessions.pop(str(session.get("session_id") or ""))
        stored["status"] = "closed"
        stored["handshake_state"] = "closed"
        stored["updated_at"] = utc_now()
        stored["closed_at"] = utc_now()
        stored["summary"] = self._session_summary(stored, list(stored.get("turns") or []), [])
        return dict(stored)

    def shutdown(self) -> None:
        self._acp_sessions.clear()
        for registration_id in list(self._processes.keys()):
            try:
                self.stop_registration(registration_id)
            except Exception:
                continue
