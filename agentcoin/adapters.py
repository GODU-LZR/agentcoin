from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agentcoin.models import utc_now
from agentcoin.net import OutboundTransport
from agentcoin.receipts import (
    build_deterministic_execution_receipt,
    build_policy_receipt,
)


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
        result["policy_receipt"] = build_policy_receipt(
            protocol="agentcoin",
            decision="allowed",
            reason="no bridge policy applied",
            mode="generic",
        )
        result["execution_receipt"] = build_deterministic_execution_receipt(
            task,
            worker_id=worker_id,
            protocol="agentcoin",
            status="completed",
            outcome="generic-execution",
        )
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
        result["policy_receipt"] = build_policy_receipt(
            protocol=protocol,
            decision="rejected",
            reason=reason,
            mode="policy",
        )
        if extra:
            result["adapter"].update(extra)
            result["policy_receipt"].update(extra)
        result["execution_receipt"] = build_deterministic_execution_receipt(
            task,
            worker_id=worker_id,
            protocol=protocol,
            status="rejected",
            outcome="policy-rejected",
            artifacts=extra or {},
        )
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
        if runtime_kind == "langgraph-http":
            return self._execute_langgraph_http_runtime(task, runtime=runtime, worker_id=worker_id)
        if runtime_kind == "container-job":
            return self._execute_container_job_runtime(task, runtime=runtime, worker_id=worker_id)
        if runtime_kind == "openai-chat":
            return self._execute_openai_chat_runtime(task, runtime=runtime, worker_id=worker_id)
        if runtime_kind == "claude-http":
            return self._execute_claude_http_runtime(task, runtime=runtime, worker_id=worker_id)
        if runtime_kind == "ollama-chat":
            return self._execute_ollama_runtime(task, runtime=runtime, worker_id=worker_id)
        if runtime_kind == "claude-code-cli":
            return self._execute_claude_code_runtime(task, runtime=runtime, worker_id=worker_id)
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

    @staticmethod
    def _normalize_command(raw_command: Any, *, field_name: str) -> list[str]:
        if isinstance(raw_command, list):
            command = [str(item) for item in raw_command if str(item).strip()]
        elif isinstance(raw_command, str) and raw_command.strip():
            command = [raw_command.strip()]
        else:
            raise ValueError(f"{field_name} is required")
        if not command:
            raise ValueError(f"{field_name} is required")
        return command

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
        result["policy_receipt"] = build_policy_receipt(
            protocol="http-json",
            decision="allowed",
            reason="runtime endpoint allowlisted",
            mode="runtime-adapter",
            runtime="http-json",
            endpoint=endpoint,
        )
        result["runtime_execution"] = {
            "runtime": "http-json",
            "endpoint": endpoint,
            "method": method,
            "response": response,
        }
        result["execution_receipt"] = build_deterministic_execution_receipt(
            task,
            worker_id=worker_id,
            protocol="http-json",
            status="completed",
            outcome="runtime-call",
            artifacts={"endpoint": endpoint, "method": method},
        )
        return result

    @staticmethod
    def _langgraph_input(task: dict[str, Any], runtime: dict[str, Any]) -> Any:
        if "input" in runtime:
            return runtime.get("input")
        if "input" in task.get("payload", {}):
            return task.get("payload", {}).get("input")
        return dict(task.get("payload", {}))

    @staticmethod
    def _langgraph_thread_id(task: dict[str, Any], runtime: dict[str, Any]) -> str:
        return (
            str(runtime.get("thread_id") or "").strip()
            or str(task.get("workflow_id") or "").strip()
            or str(task.get("id") or "").strip()
        )

    @staticmethod
    def _extract_langgraph_assistant_message(response: dict[str, Any]) -> dict[str, Any] | None:
        messages = response.get("messages")
        if isinstance(messages, list):
            for item in reversed(messages):
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or item.get("type") or "").strip().lower()
                if role in {"assistant", "ai"}:
                    return dict(item)
        output = response.get("output")
        if isinstance(output, dict):
            return dict(output)
        return None

    def _execute_langgraph_http_runtime(self, task: dict[str, Any], *, runtime: dict[str, Any], worker_id: str) -> dict[str, Any]:
        endpoint = str(runtime.get("endpoint") or "").strip()
        if not endpoint:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:langgraph-http",
                reason="runtime.endpoint is required",
                extra={"runtime": "langgraph-http"},
            )
        if not self.policy.http_host_allowed(endpoint):
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:langgraph-http",
                reason="runtime endpoint host is not allowlisted",
                extra={"runtime": "langgraph-http", "endpoint": endpoint},
            )
        request_body: dict[str, Any] = {
            "thread_id": self._langgraph_thread_id(task, runtime),
            "input": self._langgraph_input(task, runtime),
            "task_id": task.get("id"),
            "workflow_id": task.get("workflow_id"),
            "worker_id": worker_id,
        }
        if "assistant_id" in runtime:
            request_body["assistant_id"] = runtime.get("assistant_id")
        if "config" in runtime:
            request_body["config"] = dict(runtime.get("config") or {})
        if "checkpoint" in runtime:
            request_body["checkpoint"] = runtime.get("checkpoint")
        headers = {"Content-Type": "application/json"}
        headers.update(dict(runtime.get("headers") or {}))
        auth_token = str(runtime.get("auth_token") or "").strip()
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        try:
            response = self.transport.request_json(
                endpoint,
                method="POST",
                payload=request_body,
                headers=headers,
                timeout=float(runtime.get("timeout_seconds") or 60),
            )
        except Exception as exc:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:langgraph-http",
                reason=str(exc),
                extra={"runtime": "langgraph-http", "endpoint": endpoint},
            )
        assistant_message = self._extract_langgraph_assistant_message(response)
        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "runtime-adapter",
            "protocol": "langgraph-http",
            "status": "completed",
            "endpoint": endpoint,
            "thread_id": request_body["thread_id"],
        }
        result["policy_receipt"] = build_policy_receipt(
            protocol="langgraph-http",
            decision="allowed",
            reason="runtime endpoint allowlisted",
            mode="runtime-adapter",
            runtime="langgraph-http",
            endpoint=endpoint,
            thread_id=request_body["thread_id"],
        )
        result["runtime_execution"] = {
            "runtime": "langgraph-http",
            "endpoint": endpoint,
            "request": request_body,
            "response": response,
            "assistant_message": assistant_message,
            "run_id": response.get("run_id"),
            "thread_id": response.get("thread_id") or request_body["thread_id"],
            "state": response.get("state"),
        }
        result["execution_receipt"] = build_deterministic_execution_receipt(
            task,
            worker_id=worker_id,
            protocol="langgraph-http",
            status="completed",
            outcome="runtime-graph-run",
            artifacts={
                "endpoint": endpoint,
                "thread_id": request_body["thread_id"],
                "run_id": response.get("run_id"),
                "assistant_id": request_body.get("assistant_id"),
            },
        )
        return result

    def _execute_container_job_runtime(self, task: dict[str, Any], *, runtime: dict[str, Any], worker_id: str) -> dict[str, Any]:
        if not self.policy.allow_subprocess:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:container-job",
                reason="subprocess execution is disabled",
                extra={"runtime": "container-job"},
            )
        image = str(runtime.get("image") or "").strip()
        try:
            engine_command = self._normalize_command(
                runtime.get("engine_command") or ["docker"],
                field_name="runtime.engine_command",
            )
            if not self.policy.command_allowed(engine_command[0]):
                raise ValueError(f"command is not allowlisted: {engine_command[0]}")
            user_command = self._normalize_command(runtime.get("command") or ["python", "-"], field_name="runtime.command")
        except ValueError as exc:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:container-job",
                reason=str(exc),
                extra={"runtime": "container-job", "image": image},
            )

        env_overrides = {str(key): str(value) for key, value in dict(runtime.get("env") or {}).items() if str(key).strip()}
        network_mode = str(runtime.get("network_mode") or "none").strip() or "none"
        task_mount_path = str(runtime.get("task_mount_path") or "/agentcoin/task.json").strip() or "/agentcoin/task.json"
        output_mount_path = str(runtime.get("output_mount_path") or "/agentcoin/output.json").strip() or "/agentcoin/output.json"
        read_only_rootfs = bool(runtime.get("read_only_rootfs", False))

        try:
            with tempfile.TemporaryDirectory(dir=self.policy.workspace_root or None) as tempdir:
                temp_path = Path(tempdir)
                task_file = temp_path / "task.json"
                runtime_file = temp_path / "runtime.json"
                output_file = temp_path / "output.json"
                task_file.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
                runtime_file.write_text(json.dumps(runtime, ensure_ascii=False), encoding="utf-8")

                env = {
                    "AGENTCOIN_TASK_FILE": str(task_file),
                    "AGENTCOIN_RUNTIME_FILE": str(runtime_file),
                    "AGENTCOIN_OUTPUT_FILE": str(output_file),
                    "AGENTCOIN_IMAGE": image,
                    "AGENTCOIN_WORKER_ID": worker_id,
                    "AGENTCOIN_TASK_MOUNT_PATH": task_mount_path,
                    "AGENTCOIN_OUTPUT_MOUNT_PATH": output_mount_path,
                    **env_overrides,
                }

                if runtime.get("engine_command"):
                    command = [*engine_command, *user_command]
                else:
                    if not image:
                        raise ValueError("runtime.image is required when engine_command is not provided")
                    command = [*engine_command, "run", "--rm", "--network", network_mode]
                    if read_only_rootfs:
                        command.append("--read-only")
                    for key, value in env.items():
                        command.extend(["-e", f"{key}={value}"])
                    command.extend(["-v", f"{task_file}:{task_mount_path}:ro", "-v", f"{output_file}:{output_mount_path}"])
                    if runtime.get("workdir"):
                        command.extend(["-w", str(runtime.get("workdir"))])
                    command.append(image)
                    command.extend(user_command)

                completed = subprocess.run(
                    command,
                    cwd=self._resolve_cwd(runtime.get("cwd")),
                    env={**os.environ, **env},
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

                output_json = None
                if output_file.exists() and output_file.read_text(encoding="utf-8").strip():
                    try:
                        output_json = json.loads(output_file.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        output_json = None
        except (ValueError, subprocess.TimeoutExpired) as exc:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:container-job",
                reason=str(exc),
                extra={"runtime": "container-job", "image": image},
            )

        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "runtime-adapter",
            "protocol": "container-job",
            "status": "completed",
            "image": image,
        }
        result["policy_receipt"] = build_policy_receipt(
            protocol="container-job",
            decision="allowed",
            reason="container job runner command allowlisted",
            mode="runtime-adapter",
            runtime="container-job",
            image=image,
            engine_command=engine_command,
        )
        result["runtime_execution"] = {
            "runtime": "container-job",
            "image": image,
            "engine_command": engine_command,
            "command": user_command,
            "returncode": completed.returncode,
            "stdout": stdout_text,
            "stderr": completed.stderr[:4000],
            "stdout_json": stdout_json,
            "output_json": output_json,
            "network_mode": network_mode,
        }
        result["execution_receipt"] = build_deterministic_execution_receipt(
            task,
            worker_id=worker_id,
            protocol="container-job",
            status="completed",
            outcome="runtime-container-job",
            artifacts={
                "image": image,
                "engine_command": engine_command,
                "command": user_command,
                "returncode": completed.returncode,
                "output_json": output_json,
                "stdout_json": stdout_json,
            },
        )
        return result

    @staticmethod
    def _normalize_ollama_messages(task: dict[str, Any], runtime: dict[str, Any]) -> list[dict[str, str]]:
        raw_messages = runtime.get("messages") or task.get("payload", {}).get("messages")
        if isinstance(raw_messages, list) and raw_messages:
            normalized: list[dict[str, str]] = []
            for item in raw_messages:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "user").strip() or "user"
                content = str(item.get("content") or "")
                normalized.append({"role": role, "content": content})
            if normalized:
                return normalized
        prompt = runtime.get("prompt")
        if prompt is None:
            prompt = task.get("payload", {}).get("input")
        if prompt is None:
            prompt = task.get("payload", {})
        if isinstance(prompt, str):
            content = prompt
        else:
            content = json.dumps(prompt, ensure_ascii=False)
        return [{"role": "user", "content": content}]

    @staticmethod
    def _normalize_openai_messages(task: dict[str, Any], runtime: dict[str, Any]) -> list[dict[str, Any]]:
        raw_messages = runtime.get("messages") or task.get("payload", {}).get("messages")
        if isinstance(raw_messages, list) and raw_messages:
            normalized: list[dict[str, Any]] = []
            for item in raw_messages:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "user").strip() or "user"
                content = item.get("content")
                if isinstance(content, (dict, list)):
                    normalized.append({"role": role, "content": content})
                else:
                    normalized.append({"role": role, "content": str(content or "")})
            if normalized:
                return normalized
        prompt = runtime.get("prompt")
        if prompt is None:
            prompt = task.get("payload", {}).get("input")
        if prompt is None:
            prompt = task.get("payload", {})
        if isinstance(prompt, str):
            content = prompt
        else:
            content = json.dumps(prompt, ensure_ascii=False)
        return [{"role": "user", "content": content}]

    @staticmethod
    def _normalize_claude_content_blocks(content: Any) -> list[dict[str, Any]]:
        if isinstance(content, list):
            blocks: list[dict[str, Any]] = []
            for item in content:
                if isinstance(item, dict):
                    blocks.append(dict(item))
                elif isinstance(item, str) and item.strip():
                    blocks.append({"type": "text", "text": item})
            return blocks
        if isinstance(content, dict):
            return [dict(content)]
        if isinstance(content, str) and content.strip():
            return [{"type": "text", "text": content}]
        return []

    @staticmethod
    def _normalize_claude_tool_results(tool_results: Any) -> list[dict[str, Any]]:
        if not isinstance(tool_results, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in tool_results:
            if not isinstance(item, dict):
                continue
            tool_use_id = str(item.get("tool_use_id") or "").strip()
            if not tool_use_id:
                continue
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
            }
            content_blocks = ExecutionAdapterRegistry._normalize_claude_content_blocks(item.get("content"))
            if content_blocks:
                block["content"] = content_blocks
            elif "content" in item:
                block["content"] = item.get("content")
            if "is_error" in item:
                block["is_error"] = bool(item.get("is_error"))
            normalized.append(block)
        return normalized

    @staticmethod
    def _normalize_claude_messages(task: dict[str, Any], runtime: dict[str, Any]) -> list[dict[str, Any]]:
        raw_messages = runtime.get("messages") or task.get("payload", {}).get("messages")
        if isinstance(raw_messages, list) and raw_messages:
            normalized: list[dict[str, Any]] = []
            for item in raw_messages:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "user").strip() or "user"
                content = item.get("content")
                if isinstance(content, (list, dict, str)):
                    normalized.append({"role": role, "content": ExecutionAdapterRegistry._normalize_claude_content_blocks(content) or content})
            if normalized:
                tool_result_blocks = ExecutionAdapterRegistry._normalize_claude_tool_results(runtime.get("tool_results"))
                if tool_result_blocks:
                    normalized.append({"role": "user", "content": tool_result_blocks})
                return normalized
        prompt = runtime.get("prompt")
        if prompt is None:
            prompt = task.get("payload", {}).get("input")
        if prompt is None:
            prompt = task.get("payload", {})
        prompt_content = prompt if isinstance(prompt, str) else json.dumps(prompt, ensure_ascii=False)
        messages = [{"role": "user", "content": ExecutionAdapterRegistry._normalize_claude_content_blocks(prompt_content)}]
        tool_result_blocks = ExecutionAdapterRegistry._normalize_claude_tool_results(runtime.get("tool_results"))
        if tool_result_blocks:
            messages.append({"role": "user", "content": tool_result_blocks})
        return messages

    @staticmethod
    def _extract_claude_assistant_message(response: dict[str, Any]) -> dict[str, Any]:
        content_blocks = list(response.get("content") or [])
        text_parts: list[str] = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            if str(block.get("type") or "").strip().lower() == "text":
                text = str(block.get("text") or "")
                if text:
                    text_parts.append(text)
        return {
            "role": str(response.get("role") or "assistant"),
            "content": "\n".join(text_parts).strip(),
            "content_blocks": content_blocks,
        }

    @staticmethod
    def _extract_claude_tool_uses(response: dict[str, Any]) -> list[dict[str, Any]]:
        content_blocks = list(response.get("content") or [])
        tool_uses: list[dict[str, Any]] = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            if str(block.get("type") or "").strip().lower() != "tool_use":
                continue
            tool_uses.append(
                {
                    "id": str(block.get("id") or "").strip() or None,
                    "name": str(block.get("name") or "").strip() or None,
                    "input": block.get("input"),
                }
            )
        return tool_uses

    def _execute_ollama_runtime(self, task: dict[str, Any], *, runtime: dict[str, Any], worker_id: str) -> dict[str, Any]:
        endpoint = str(runtime.get("endpoint") or "http://127.0.0.1:11434/api/chat").strip()
        if not self.policy.http_host_allowed(endpoint):
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:ollama-chat",
                reason="runtime endpoint host is not allowlisted",
                extra={"runtime": "ollama-chat", "endpoint": endpoint},
            )
        model = str(runtime.get("model") or "").strip()
        if not model:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:ollama-chat",
                reason="runtime.model is required",
                extra={"runtime": "ollama-chat", "endpoint": endpoint},
            )
        request_body = {
            "model": model,
            "messages": self._normalize_ollama_messages(task, runtime),
            "stream": False,
        }
        if "options" in runtime:
            request_body["options"] = dict(runtime.get("options") or {})
        if "format" in runtime:
            request_body["format"] = runtime.get("format")
        if "keep_alive" in runtime:
            request_body["keep_alive"] = runtime.get("keep_alive")
        headers = dict(runtime.get("headers") or {})
        try:
            response = self.transport.request_json(
                endpoint,
                method="POST",
                payload=request_body,
                headers=headers,
                timeout=float(runtime.get("timeout_seconds") or 60),
            )
        except Exception as exc:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:ollama-chat",
                reason=str(exc),
                extra={"runtime": "ollama-chat", "endpoint": endpoint, "model": model},
            )
        assistant_message = dict(response.get("message") or {})
        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "runtime-adapter",
            "protocol": "ollama-chat",
            "status": "completed",
            "endpoint": endpoint,
            "model": model,
        }
        result["policy_receipt"] = build_policy_receipt(
            protocol="ollama-chat",
            decision="allowed",
            reason="runtime endpoint allowlisted",
            mode="runtime-adapter",
            runtime="ollama-chat",
            endpoint=endpoint,
            model=model,
        )
        result["runtime_execution"] = {
            "runtime": "ollama-chat",
            "endpoint": endpoint,
            "request": request_body,
            "response": response,
            "assistant_message": assistant_message,
        }
        result["execution_receipt"] = build_deterministic_execution_receipt(
            task,
            worker_id=worker_id,
            protocol="ollama-chat",
            status="completed",
            outcome="runtime-chat",
            artifacts={"endpoint": endpoint, "model": model, "done": bool(response.get("done"))},
        )
        return result

    def _execute_openai_chat_runtime(self, task: dict[str, Any], *, runtime: dict[str, Any], worker_id: str) -> dict[str, Any]:
        endpoint = str(runtime.get("endpoint") or "").strip()
        if not endpoint:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:openai-chat",
                reason="runtime.endpoint is required",
                extra={"runtime": "openai-chat"},
            )
        if not self.policy.http_host_allowed(endpoint):
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:openai-chat",
                reason="runtime endpoint host is not allowlisted",
                extra={"runtime": "openai-chat", "endpoint": endpoint},
            )
        model = str(runtime.get("model") or "").strip()
        if not model:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:openai-chat",
                reason="runtime.model is required",
                extra={"runtime": "openai-chat", "endpoint": endpoint},
            )
        request_body: dict[str, Any] = {
            "model": model,
            "messages": self._normalize_openai_messages(task, runtime),
        }
        for optional_key in ("temperature", "top_p", "max_tokens", "presence_penalty", "frequency_penalty", "stream"):
            if optional_key in runtime:
                request_body[optional_key] = runtime.get(optional_key)
        structured_output = runtime.get("structured_output")
        response_format = runtime.get("response_format")
        if isinstance(structured_output, dict) and structured_output:
            json_schema = {
                "name": str(structured_output.get("name") or "agentcoin_output"),
                "strict": bool(structured_output.get("strict", True)),
                "schema": dict(structured_output.get("schema") or {}),
            }
            request_body["response_format"] = {
                "type": "json_schema",
                "json_schema": json_schema,
            }
        elif isinstance(response_format, dict) and response_format:
            request_body["response_format"] = response_format
        headers = {"Content-Type": "application/json"}
        headers.update(dict(runtime.get("headers") or {}))
        auth_token = str(runtime.get("auth_token") or "").strip()
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        try:
            response = self.transport.request_json(
                endpoint,
                method="POST",
                payload=request_body,
                headers=headers,
                timeout=float(runtime.get("timeout_seconds") or 60),
            )
        except Exception as exc:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:openai-chat",
                reason=str(exc),
                extra={"runtime": "openai-chat", "endpoint": endpoint, "model": model},
            )
        choices = list(response.get("choices") or [])
        first_choice = dict(choices[0] or {}) if choices else {}
        assistant_message = dict(first_choice.get("message") or {})
        parsed_output = assistant_message.get("parsed")
        if parsed_output is None:
            content = assistant_message.get("content")
            if isinstance(content, str) and content.strip():
                try:
                    parsed_output = json.loads(content)
                except json.JSONDecodeError:
                    parsed_output = None
        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "runtime-adapter",
            "protocol": "openai-chat",
            "status": "completed",
            "endpoint": endpoint,
            "model": model,
        }
        result["policy_receipt"] = build_policy_receipt(
            protocol="openai-chat",
            decision="allowed",
            reason="runtime endpoint allowlisted",
            mode="runtime-adapter",
            runtime="openai-chat",
            endpoint=endpoint,
            model=model,
        )
        result["runtime_execution"] = {
            "runtime": "openai-chat",
            "endpoint": endpoint,
            "request": {key: value for key, value in request_body.items() if key != "messages"} | {"messages": request_body["messages"]},
            "response": response,
            "assistant_message": assistant_message,
            "finish_reason": first_choice.get("finish_reason"),
        }
        if parsed_output is not None:
            result["runtime_execution"]["structured_output"] = parsed_output
        result["execution_receipt"] = build_deterministic_execution_receipt(
            task,
            worker_id=worker_id,
            protocol="openai-chat",
            status="completed",
            outcome="runtime-chat",
            artifacts={
                "endpoint": endpoint,
                "model": model,
                "response_id": response.get("id"),
                "structured_output": parsed_output,
                "response_format": request_body.get("response_format"),
            },
        )
        return result

    def _execute_claude_http_runtime(self, task: dict[str, Any], *, runtime: dict[str, Any], worker_id: str) -> dict[str, Any]:
        endpoint = str(runtime.get("endpoint") or "").strip()
        if not endpoint:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:claude-http",
                reason="runtime.endpoint is required",
                extra={"runtime": "claude-http"},
            )
        if not self.policy.http_host_allowed(endpoint):
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:claude-http",
                reason="runtime endpoint host is not allowlisted",
                extra={"runtime": "claude-http", "endpoint": endpoint},
            )
        model = str(runtime.get("model") or "").strip()
        if not model:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:claude-http",
                reason="runtime.model is required",
                extra={"runtime": "claude-http", "endpoint": endpoint},
            )
        request_body: dict[str, Any] = {
            "model": model,
            "messages": self._normalize_claude_messages(task, runtime),
            "max_tokens": int(runtime.get("max_tokens") or 1024),
        }
        system_prompt = runtime.get("system")
        if isinstance(system_prompt, str) and system_prompt.strip():
            request_body["system"] = system_prompt.strip()
        for optional_key in ("temperature", "top_p", "stream", "metadata"):
            if optional_key in runtime:
                request_body[optional_key] = runtime.get(optional_key)
        if "stop_sequences" in runtime:
            request_body["stop_sequences"] = list(runtime.get("stop_sequences") or [])
        if "tools" in runtime:
            request_body["tools"] = list(runtime.get("tools") or [])
        if "tool_choice" in runtime:
            request_body["tool_choice"] = runtime.get("tool_choice")
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": str(runtime.get("anthropic_version") or "2023-06-01"),
        }
        headers.update(dict(runtime.get("headers") or {}))
        auth_token = str(runtime.get("auth_token") or "").strip()
        if auth_token:
            headers["x-api-key"] = auth_token
        try:
            response = self.transport.request_json(
                endpoint,
                method="POST",
                payload=request_body,
                headers=headers,
                timeout=float(runtime.get("timeout_seconds") or 60),
            )
        except Exception as exc:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:claude-http",
                reason=str(exc),
                extra={"runtime": "claude-http", "endpoint": endpoint, "model": model},
            )
        assistant_message = self._extract_claude_assistant_message(response)
        tool_uses = self._extract_claude_tool_uses(response)
        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "runtime-adapter",
            "protocol": "claude-http",
            "status": "completed",
            "endpoint": endpoint,
            "model": model,
        }
        result["policy_receipt"] = build_policy_receipt(
            protocol="claude-http",
            decision="allowed",
            reason="runtime endpoint allowlisted",
            mode="runtime-adapter",
            runtime="claude-http",
            endpoint=endpoint,
            model=model,
        )
        result["runtime_execution"] = {
            "runtime": "claude-http",
            "endpoint": endpoint,
            "request": request_body,
            "response": response,
            "assistant_message": assistant_message,
            "stop_reason": response.get("stop_reason"),
            "usage": response.get("usage"),
        }
        if tool_uses:
            result["runtime_execution"]["tool_uses"] = tool_uses
        result["execution_receipt"] = build_deterministic_execution_receipt(
            task,
            worker_id=worker_id,
            protocol="claude-http",
            status="completed",
            outcome="runtime-chat",
            artifacts={
                "endpoint": endpoint,
                "model": model,
                "response_id": response.get("id"),
                "stop_reason": response.get("stop_reason"),
                "tool_uses": tool_uses,
            },
        )
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
        result["policy_receipt"] = build_policy_receipt(
            protocol="cli-json",
            decision="allowed",
            reason="command allowlisted",
            mode="runtime-adapter",
            runtime="cli-json",
            command=execution["command"],
        )
        result["runtime_execution"] = {
            "runtime": "cli-json",
            "command": execution["command"],
            "returncode": execution["returncode"],
            "stdout": execution["stdout"],
            "stderr": execution["stderr"],
            "stdout_json": execution["stdout_json"],
        }
        result["execution_receipt"] = build_deterministic_execution_receipt(
            task,
            worker_id=worker_id,
            protocol="cli-json",
            status="completed",
            outcome="subprocess-json",
            artifacts={"command": execution["command"], "returncode": execution["returncode"]},
        )
        return result

    @staticmethod
    def _prompt_text_from_task(task: dict[str, Any], runtime: dict[str, Any]) -> str:
        prompt = runtime.get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            return prompt.strip()
        payload = dict(task.get("payload") or {})
        task_input = payload.get("input")
        if isinstance(task_input, str) and task_input.strip():
            return task_input.strip()
        if isinstance(task_input, dict):
            for key in ("prompt", "content", "text", "query", "instruction"):
                value = task_input.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        messages = runtime.get("messages") or payload.get("messages")
        if isinstance(messages, list):
            texts: list[str] = []
            for item in messages:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, str) and content.strip():
                    texts.append(content.strip())
            if texts:
                return "\n\n".join(texts)
        return json.dumps(payload or task, ensure_ascii=False)

    def _execute_claude_code_runtime(self, task: dict[str, Any], *, runtime: dict[str, Any], worker_id: str) -> dict[str, Any]:
        raw_command = runtime.get("command")
        executable_path = str(runtime.get("executable_path") or "").strip()
        if raw_command is None and executable_path:
            raw_command = [executable_path]
        try:
            command = self._normalize_command(raw_command, field_name="runtime.command or runtime.executable_path")
        except ValueError as exc:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:claude-code-cli",
                reason=str(exc),
                extra={"runtime": "claude-code-cli"},
            )
        executable = command[0]
        if not self.policy.allow_subprocess:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:claude-code-cli",
                reason="subprocess execution is disabled",
                extra={"runtime": "claude-code-cli", "command": command},
            )
        if not self.policy.command_allowed(executable):
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:claude-code-cli",
                reason=f"command is not allowlisted: {executable}",
                extra={"runtime": "claude-code-cli", "command": command},
            )
        prompt_text = self._prompt_text_from_task(task, runtime)
        prompt_transport = str(runtime.get("prompt_transport") or "stdin").strip().lower() or "stdin"
        prompt_flag = str(runtime.get("prompt_flag") or "").strip()
        raw_args = runtime.get("args")
        if isinstance(raw_args, list):
            args = [str(item) for item in raw_args if str(item).strip()]
        elif isinstance(raw_args, str) and raw_args.strip():
            args = [raw_args.strip()]
        else:
            args = []
        final_command = list(command) + list(args)
        stdin_text: str | None = None
        if prompt_transport == "stdin":
            stdin_text = prompt_text
        elif prompt_transport == "argv":
            if prompt_flag:
                final_command.extend([prompt_flag, prompt_text])
            else:
                final_command.append(prompt_text)
        else:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:claude-code-cli",
                reason="runtime.prompt_transport must be stdin or argv",
                extra={"runtime": "claude-code-cli", "command": final_command},
            )
        env = os.environ.copy()
        env.update({str(key): str(value) for key, value in dict(runtime.get("env") or {}).items()})
        try:
            completed = subprocess.run(
                final_command,
                cwd=self._resolve_cwd(runtime.get("cwd")),
                input=stdin_text,
                capture_output=True,
                text=True,
                timeout=int(runtime.get("timeout_seconds") or self.policy.subprocess_timeout_seconds),
                check=False,
                env=env,
            )
        except (ValueError, subprocess.TimeoutExpired) as exc:
            return self._rejected_result(
                task,
                worker_id=worker_id,
                protocol="runtime:claude-code-cli",
                reason=str(exc),
                extra={"runtime": "claude-code-cli", "command": final_command},
            )
        stdout_text = str(completed.stdout or "")[:4000]
        stderr_text = str(completed.stderr or "")[:4000]
        stdout_json = None
        if stdout_text.strip():
            try:
                stdout_json = json.loads(stdout_text)
            except json.JSONDecodeError:
                stdout_json = None
        assistant_message = None
        if isinstance(stdout_json, dict):
            if isinstance(stdout_json.get("assistant_message"), dict):
                assistant_message = dict(stdout_json.get("assistant_message") or {})
            elif isinstance(stdout_json.get("content"), str):
                assistant_message = {"role": "assistant", "content": str(stdout_json.get("content") or "")}
        if assistant_message is None:
            assistant_message = {"role": "assistant", "content": stdout_text.strip()}
        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "runtime-adapter",
            "protocol": "claude-code-cli",
            "status": "completed",
            "command": final_command,
        }
        result["policy_receipt"] = build_policy_receipt(
            protocol="claude-code-cli",
            decision="allowed",
            reason="command allowlisted",
            mode="runtime-adapter",
            runtime="claude-code-cli",
            command=final_command,
        )
        result["runtime_execution"] = {
            "runtime": "claude-code-cli",
            "command": final_command,
            "prompt_transport": prompt_transport,
            "prompt_flag": prompt_flag or None,
            "returncode": completed.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "stdout_json": stdout_json,
            "assistant_message": assistant_message,
        }
        result["execution_receipt"] = build_deterministic_execution_receipt(
            task,
            worker_id=worker_id,
            protocol="claude-code-cli",
            status="completed",
            outcome="runtime-cli-prompt",
            artifacts={
                "command": final_command,
                "prompt_transport": prompt_transport,
                "returncode": completed.returncode,
            },
        )
        return result

    def _execute_mcp(self, task: dict[str, Any], *, bridge: dict[str, Any], worker_id: str) -> dict[str, Any]:
        payload = dict(task.get("payload", {}))
        method = str(bridge.get("method") or "")
        tool_call = dict(bridge.get("tool_call") or {})
        tool_name = str(tool_call.get("tool_name") or bridge.get("tool_name") or payload.get("tool_name") or "")
        arguments = dict(tool_call.get("arguments") or payload.get("arguments") or {})
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
        result["policy_receipt"] = build_policy_receipt(
            protocol="mcp",
            decision="allowed",
            reason="tool is allowlisted",
            mode="bridge-skeleton",
            tool_name=tool_name,
            allow_subprocess=self.policy.allow_subprocess,
        )
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
        tool_call = {
            "schema_version": "0.1",
            "request_id": bridge.get("request_id"),
            "method": method,
            "tool_name": tool_name,
            "arguments": arguments,
            "content": payload.get("content"),
        }
        tool_result = {
            "schema_version": "0.1",
            "tool_name": tool_name,
            "is_error": False,
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
            ],
            "structured_content": {
                "tool_name": tool_name,
                "arguments": arguments,
                "handled_by": worker_id,
                "status": "accepted",
                "execution": execution,
            },
        }
        result["bridge_execution"] = {
            "protocol": "mcp",
            "schema_version": "0.1",
            "request_id": bridge.get("request_id"),
            "method": method,
            "tool_name": tool_name,
            "arguments": arguments,
            "accepted": True,
            "tool_call": tool_call,
            "tool_result": tool_result,
            "normalized_output": {
                "content": list(tool_result["content"]),
            },
        }
        result["execution_receipt"] = build_deterministic_execution_receipt(
            task,
            worker_id=worker_id,
            protocol="mcp",
            status="completed",
            outcome="bridge-tool-call",
            artifacts={"tool_name": tool_name, "method": method},
            subprocess=execution,
        )
        return result

    def _execute_a2a(self, task: dict[str, Any], *, bridge: dict[str, Any], worker_id: str) -> dict[str, Any]:
        payload = dict(task.get("payload", {}))
        message_envelope = dict(bridge.get("message_envelope") or {})
        content = payload.get("content")
        metadata = payload.get("metadata") or {}
        intent = str(message_envelope.get("intent") or bridge.get("intent") or "")
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
        result["policy_receipt"] = build_policy_receipt(
            protocol="a2a",
            decision="allowed",
            reason="intent is allowlisted",
            mode="bridge-skeleton",
            intent=intent,
        )
        result["bridge_execution"] = {
            "protocol": "a2a",
            "schema_version": "0.1",
            "message_id": bridge.get("message_id") or task["id"],
            "conversation_id": bridge.get("conversation_id") or task.get("workflow_id"),
            "intent": intent,
            "accepted": True,
            "message_envelope": {
                "schema_version": "0.1",
                "message_id": message_envelope.get("message_id") or bridge.get("message_id") or task["id"],
                "conversation_id": message_envelope.get("conversation_id") or bridge.get("conversation_id") or task.get("workflow_id"),
                "sender": message_envelope.get("sender") or task.get("sender"),
                "intent": intent,
                "in_reply_to": message_envelope.get("in_reply_to") or bridge.get("in_reply_to"),
                "content": content,
                "metadata": metadata,
            },
            "message_result": {
                "schema_version": "0.1",
                "message_id": bridge.get("message_id") or task["id"],
                "conversation_id": bridge.get("conversation_id") or task.get("workflow_id"),
                "sender": task.get("sender"),
                "intent": "task.result",
                "in_reply_to": message_envelope.get("message_id") or bridge.get("message_id"),
                "content": {
                    "accepted_intent": intent,
                    "handled_by": worker_id,
                    "content": content,
                    "metadata": metadata,
                },
                "task": {
                    "id": task["id"],
                    "status": task.get("status"),
                    "kind": task.get("kind"),
                },
            },
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
        result["execution_receipt"] = build_deterministic_execution_receipt(
            task,
            worker_id=worker_id,
            protocol="a2a",
            status="completed",
            outcome="bridge-message",
            artifacts={"intent": intent, "message_id": bridge.get("message_id") or task["id"]},
        )
        return result
