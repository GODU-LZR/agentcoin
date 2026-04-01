from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentcoin.models import utc_now


@dataclass(slots=True)
class AdapterPolicy:
    allowed_mcp_tools: list[str] = field(default_factory=list)
    allowed_a2a_intents: list[str] = field(default_factory=list)
    allow_subprocess: bool = False
    allowed_commands: list[str] = field(default_factory=list)
    subprocess_timeout_seconds: int = 10
    workspace_root: str | None = None

    def tool_allowed(self, tool_name: str) -> bool:
        if not self.allowed_mcp_tools:
            return True
        return tool_name in set(self.allowed_mcp_tools)

    def intent_allowed(self, intent: str) -> bool:
        if not self.allowed_a2a_intents:
            return True
        return intent in set(self.allowed_a2a_intents)

    def command_allowed(self, executable: str) -> bool:
        if not self.allowed_commands:
            return False
        normalized = {item.casefold() for item in self.allowed_commands}
        executable_name = Path(executable).name.casefold()
        return executable.casefold() in normalized or executable_name in normalized


class ExecutionAdapterRegistry:
    def __init__(self, policy: AdapterPolicy | None = None) -> None:
        self.policy = policy or AdapterPolicy()

    def execute(self, task: dict[str, Any], *, worker_id: str) -> dict[str, Any]:
        bridge = dict(task.get("payload", {}).get("_bridge") or {})
        protocol = str(bridge.get("protocol") or "").strip().lower()
        if protocol == "mcp":
            return self._execute_mcp(task, bridge=bridge, worker_id=worker_id)
        if protocol == "a2a":
            return self._execute_a2a(task, bridge=bridge, worker_id=worker_id)
        return self._execute_generic(task, worker_id=worker_id)

    @staticmethod
    def _base_result(task: dict[str, Any], *, worker_id: str) -> dict[str, Any]:
        return {
            "worker_id": worker_id,
            "handled_kind": task["kind"],
            "handled_at": utc_now(),
            "workflow_id": task.get("workflow_id"),
            "branch": task.get("branch"),
            "revision": task.get("revision"),
            "echo": task.get("payload", {}),
        }

    def _execute_generic(self, task: dict[str, Any], *, worker_id: str) -> dict[str, Any]:
        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "generic",
            "protocol": "agentcoin",
            "status": "completed",
        }
        result["policy_receipt"] = {
            "mode": "generic",
            "protocol": "agentcoin",
            "decision": "allowed",
            "reason": "no bridge policy applied",
        }
        return result

    def _rejected_result(
        self,
        task: dict[str, Any],
        *,
        worker_id: str,
        protocol: str,
        reason: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "policy",
            "protocol": protocol,
            "status": "rejected",
            "reason": reason,
        }
        result["policy_receipt"] = {
            "mode": "policy",
            "protocol": protocol,
            "decision": "rejected",
            "reason": reason,
        }
        if extra:
            result["adapter"].update(extra)
            result["policy_receipt"].update(extra)
        return result

    def _resolve_cwd(self, requested_cwd: str | None) -> str | None:
        if not requested_cwd:
            return self.policy.workspace_root
        requested = Path(requested_cwd)
        if not requested.is_absolute():
            base = Path(self.policy.workspace_root or os.getcwd())
            requested = base / requested
        requested = requested.resolve()
        if self.policy.workspace_root:
            workspace_root = Path(self.policy.workspace_root).resolve()
            try:
                requested.relative_to(workspace_root)
            except ValueError as exc:
                raise ValueError("requested cwd escapes workspace_root") from exc
        return str(requested)

    def _run_subprocess(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.policy.allow_subprocess:
            raise ValueError("subprocess execution is disabled")
        raw_command = arguments.get("command")
        if isinstance(raw_command, list):
            command = [str(item) for item in raw_command if str(item).strip()]
        elif isinstance(raw_command, str) and raw_command.strip():
            command = [raw_command.strip()]
        else:
            raise ValueError("arguments.command is required for local-command")
        executable = command[0]
        if not self.policy.command_allowed(executable):
            raise ValueError(f"command is not allowlisted: {executable}")

        completed = subprocess.run(
            command,
            cwd=self._resolve_cwd(arguments.get("cwd")),
            capture_output=True,
            text=True,
            timeout=self.policy.subprocess_timeout_seconds,
            check=False,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout[:4000],
            "stderr": completed.stderr[:4000],
        }

    def _execute_mcp(self, task: dict[str, Any], *, bridge: dict[str, Any], worker_id: str) -> dict[str, Any]:
        payload = dict(task.get("payload", {}))
        method = str(bridge.get("method") or "")
        tool_name = str(bridge.get("tool_name") or payload.get("tool_name") or "")
        arguments = payload.get("arguments") or {}
        if tool_name and not self.policy.tool_allowed(tool_name):
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="mcp",
                reason="tool is not allowlisted",
                extra={"tool_name": tool_name},
            )
        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "bridge-skeleton",
            "protocol": "mcp",
            "status": "completed",
        }
        result["policy_receipt"] = {
            "mode": "bridge-skeleton",
            "protocol": "mcp",
            "decision": "allowed",
            "tool_name": tool_name,
            "allow_subprocess": self.policy.allow_subprocess,
        }
        execution = None
        if tool_name == "local-command":
            try:
                execution = self._run_subprocess(arguments)
            except (ValueError, subprocess.TimeoutExpired) as exc:
                return self._rejected_result(
                    task,
                    worker_id=worker_id,
                    protocol="mcp",
                    reason=str(exc),
                    extra={"tool_name": tool_name},
                )
        result["bridge_execution"] = {
            "protocol": "mcp",
            "request_id": bridge.get("request_id"),
            "method": method,
            "tool_name": tool_name,
            "arguments": arguments,
            "accepted": True,
            "normalized_output": {
                "content": [
                    {
                        "type": "json",
                        "data": {
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "handled_by": worker_id,
                            "status": "accepted",
                            "execution": execution,
                        },
                    }
                ]
            },
        }
        result["execution_receipt"] = {
            "protocol": "mcp",
            "tool_name": tool_name,
            "method": method,
            "subprocess": execution,
        }
        return result

    def _execute_a2a(self, task: dict[str, Any], *, bridge: dict[str, Any], worker_id: str) -> dict[str, Any]:
        payload = dict(task.get("payload", {}))
        content = payload.get("content")
        metadata = payload.get("metadata") or {}
        intent = str(bridge.get("intent") or "")
        if intent and not self.policy.intent_allowed(intent):
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="a2a",
                reason="intent is not allowlisted",
                extra={"intent": intent},
            )
        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "bridge-skeleton",
            "protocol": "a2a",
            "status": "completed",
        }
        result["policy_receipt"] = {
            "mode": "bridge-skeleton",
            "protocol": "a2a",
            "decision": "allowed",
            "intent": intent,
        }
        result["bridge_execution"] = {
            "protocol": "a2a",
            "message_id": bridge.get("message_id") or task["id"],
            "conversation_id": bridge.get("conversation_id") or task.get("workflow_id"),
            "intent": intent,
            "accepted": True,
            "normalized_output": {
                "intent": "task.result",
                "content": {
                    "accepted_intent": intent,
                    "handled_by": worker_id,
                    "content": content,
                    "metadata": metadata,
                },
            },
        }
        result["execution_receipt"] = {
            "protocol": "a2a",
            "intent": intent,
            "message_id": bridge.get("message_id") or task["id"],
        }
        return result
