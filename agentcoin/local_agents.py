from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agentcoin.models import utc_now


class LocalAgentManager:
    def __init__(self) -> None:
        self._registrations: dict[str, dict[str, Any]] = {}
        self._processes: dict[str, subprocess.Popen[Any]] = {}

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
            return dict(record)
        record["status"] = "exited" if int(return_code) == 0 else "failed"
        record["pid"] = None
        record["last_exit_code"] = int(return_code)
        record["stopped_at"] = utc_now()
        self._processes.pop(registration_id, None)
        return dict(record)

    def list_registrations(self) -> list[dict[str, Any]]:
        for registration_id in list(self._registrations.keys()):
            self._refresh_status(registration_id)
        return [dict(item) for item in self._registrations.values()]

    def get_registration(self, registration_id: str) -> dict[str, Any] | None:
        return self._refresh_status(registration_id)

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
        process = subprocess.Popen(
            command,
            cwd=cwd or None,
            env={**env} if env else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            shell=False,
        )
        stored = self._registrations[registration_id]
        stored["status"] = "running"
        stored["pid"] = int(process.pid or 0)
        stored["started_at"] = utc_now()
        stored["stopped_at"] = None
        stored["last_error"] = None
        stored["last_exit_code"] = None
        self._processes[registration_id] = process
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
        return dict(stored)

    def shutdown(self) -> None:
        for registration_id in list(self._processes.keys()):
            try:
                self.stop_registration(registration_id)
            except Exception:
                continue
