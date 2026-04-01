from __future__ import annotations

import ipaddress
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agentcoin.models import utc_now
from agentcoin.net import OutboundTransport


@dataclass(slots=True)
class AdapterPolicy:
    allowed_mcp_tools: list[str] = field(default_factory=list)
    allowed_a2a_intents: list[str] = field(default_factory=list)
    allowed_runtime_kinds: list[str] = field(default_factory=list)
    allowed_http_hosts: list[str] = field(default_factory=list)
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

    def runtime_allowed(self, runtime: str) -> bool:
        if not self.allowed_runtime_kinds:
            return True
        return runtime in set(self.allowed_runtime_kinds)

    def http_host_allowed(self, endpoint: str) -> bool:
        parsed = urlparse(endpoint)
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            return False
        try:
            host_ip = ipaddress.ip_address(hostname)
        except ValueError:
            host_ip = None
        if host_ip and host_ip.is_loopback:
            return True
        if hostname == "localhost":
            return True
        if not self.allowed_http_hosts:
            return False
        for rule in self.allowed_http_hosts:
            candidate = str(rule or "").strip().lower()
            if not candidate:
                continue
            if host_ip is not None:
                try:
                    if host_ip in ipaddress.ip_network(candidate, strict=False):
                        return True
                except ValueError:
                    pass
            if hostname == candidate:
                return True
            if candidate.startswith("*.") and hostname.endswith(candidate[1:]):
                return True
            if candidate.startswith(".") and hostname.endswith(candidate):
                return True
        return False


class ExecutionAdapterRegistry:
    def __init__(self, policy: AdapterPolicy | None = None, *, transport: OutboundTransport | None = None) -> None:
        self.policy = policy or AdapterPolicy()
        self.transport = transport or OutboundTransport()

    def execute(self, task: dict[str, Any], *, worker_id: str) -> dict[str, Any]:
        runtime = dict(task.get("payload", {}).get("_runtime") or {})
        runtime_kind = str(runtime.get("runtime") or "").strip().lower()
        if runtime_kind:
            return self._execute_runtime(task, runtime=runtime, worker_id=worker_id)
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

    def _execute_runtime(self, task: dict[str, Any], *, runtime: dict[str, Any], worker_id: str) -> dict[str, Any]:
        runtime_kind = str(runtime.get("runtime") or "").strip().lower()
        if not self.policy.runtime_allowed(runtime_kind):
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol=f"runtime:{runtime_kind or 'unknown'}",
                reason="runtime adapter is not allowlisted",
                extra={"runtime": runtime_kind},
            )
        if runtime_kind == "http-json":
            return self._execute_http_runtime(task, runtime=runtime, worker_id=worker_id)
        if runtime_kind == "cli-json":
            return self._execute_cli_runtime(task, runtime=runtime, worker_id=worker_id)
        return self._rejected_result(
            task,
            worker_id=worker_id,
            protocol=f"runtime:{runtime_kind or 'unknown'}",
            reason="unsupported runtime adapter",
            extra={"runtime": runtime_kind},
        )

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

    def _run_json_subprocess(self, runtime: dict[str, Any], task: dict[str, Any], *, worker_id: str) -> dict[str, Any]:
        if not self.policy.allow_subprocess:
            raise ValueError("subprocess execution is disabled")
        raw_command = runtime.get("command")
        if isinstance(raw_command, list):
            command = [str(item) for item in raw_command if str(item).strip()]
        elif isinstance(raw_command, str) and raw_command.strip():
            command = [raw_command.strip()]
        else:
            raise ValueError("runtime.command is required for cli-json")
        executable = command[0]
        if not self.policy.command_allowed(executable):
            raise ValueError(f"command is not allowlisted: {executable}")
        stdin_payload = {
            "worker_id": worker_id,
            "task": task,
            "runtime": runtime,
        }
        completed = subprocess.run(
            command,
            cwd=self._resolve_cwd(runtime.get("cwd")),
            input=json.dumps(stdin_payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=int(runtime.get("timeout_seconds") or self.policy.subprocess_timeout_seconds),
            check=False,
        )
        stdout_text = completed.stdout[:4000]
        stdout_json = None
        if stdout_text.strip():
            try:
                stdout_json = json.loads(stdout_text)
            except json.JSONDecodeError:
                stdout_json = None
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": stdout_text,
            "stderr": completed.stderr[:4000],
            "stdout_json": stdout_json,
        }

    def _execute_http_runtime(self, task: dict[str, Any], *, runtime: dict[str, Any], worker_id: str) -> dict[str, Any]:
        endpoint = str(runtime.get("endpoint") or "").strip()
        if not endpoint:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:http-json",
                reason="runtime.endpoint is required",
                extra={"runtime": "http-json"},
            )
        if not self.policy.http_host_allowed(endpoint):
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:http-json",
                reason="runtime endpoint host is not allowlisted",
                extra={"runtime": "http-json", "endpoint": endpoint},
            )
        method = str(runtime.get("method") or "POST").strip().upper()
        if method != "POST":
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:http-json",
                reason="only POST is supported for http-json runtime",
                extra={"runtime": "http-json", "endpoint": endpoint},
            )
        request_body = {
            "worker_id": worker_id,
            "task": task,
            "runtime": runtime,
        }
        headers = dict(runtime.get("headers") or {})
        try:
            response = self.transport.request_json(
                endpoint,
                method=method,
                payload=request_body,
                headers=headers,
                timeout=float(runtime.get("timeout_seconds") or 15),
            )
        except Exception as exc:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:http-json",
                reason=str(exc),
                extra={"runtime": "http-json", "endpoint": endpoint},
            )
        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "runtime-adapter",
            "protocol": "http-json",
            "status": "completed",
            "endpoint": endpoint,
        }
        result["policy_receipt"] = {
            "mode": "runtime-adapter",
            "protocol": "http-json",
            "decision": "allowed",
            "runtime": "http-json",
            "endpoint": endpoint,
        }
        result["runtime_execution"] = {
            "runtime": "http-json",
            "endpoint": endpoint,
            "method": method,
            "response": response,
        }
        result["execution_receipt"] = {
            "protocol": "http-json",
            "endpoint": endpoint,
            "status": "completed",
        }
        return result

    def _execute_cli_runtime(self, task: dict[str, Any], *, runtime: dict[str, Any], worker_id: str) -> dict[str, Any]:
        try:
            execution = self._run_json_subprocess(runtime, task, worker_id=worker_id)
        except (ValueError, subprocess.TimeoutExpired) as exc:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:cli-json",
                reason=str(exc),
                extra={"runtime": "cli-json"},
            )
        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "runtime-adapter",
            "protocol": "cli-json",
            "status": "completed",
            "command": execution["command"],
        }
        result["policy_receipt"] = {
            "mode": "runtime-adapter",
            "protocol": "cli-json",
            "decision": "allowed",
            "runtime": "cli-json",
            "command": execution["command"],
        }
        result["runtime_execution"] = {
            "runtime": "cli-json",
            "command": execution["command"],
            "returncode": execution["returncode"],
            "stdout": execution["stdout"],
            "stderr": execution["stderr"],
            "stdout_json": execution["stdout_json"],
        }
        result["execution_receipt"] = {
            "protocol": "cli-json",
            "command": execution["command"],
            "returncode": execution["returncode"],
        }
        return result

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
