from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentcoin.models import utc_now


@dataclass(frozen=True, slots=True)
class RuntimeAdapterDescriptor:
    runtime: str
    version: str
    title: str
    description: str
    task_payload_key: str = "_runtime"
    bind_endpoint: str = "/v1/runtimes/bind"
    supports_structured_output: bool = False
    supports_http: bool = False
    supports_local: bool = False
    supports_json_schema: bool = False
    input_modes: list[str] = field(default_factory=list)
    output_modes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "task_payload_key": self.task_payload_key,
            "bind_endpoint": self.bind_endpoint,
            "supports_structured_output": self.supports_structured_output,
            "supports_http": self.supports_http,
            "supports_local": self.supports_local,
            "supports_json_schema": self.supports_json_schema,
            "input_modes": list(self.input_modes),
            "output_modes": list(self.output_modes),
        }


class RuntimeRegistry:
    def __init__(self) -> None:
        self._runtimes: dict[str, RuntimeAdapterDescriptor] = {
            "http-json": RuntimeAdapterDescriptor(
                runtime="http-json",
                version="0.1",
                title="HTTP JSON Runtime Adapter",
                description="Execute a task by forwarding a normalized envelope to an HTTP JSON agent runtime.",
                supports_http=True,
                input_modes=["task-envelope"],
                output_modes=["json-object"],
            ),
            "langgraph-http": RuntimeAdapterDescriptor(
                runtime="langgraph-http",
                version="0.1",
                title="LangGraph HTTP Runtime Adapter",
                description="Execute a task by calling a LangGraph-style HTTP endpoint with thread, input, and optional run configuration.",
                supports_http=True,
                input_modes=["thread-input", "task-envelope"],
                output_modes=["run-state", "assistant-message", "json-object"],
            ),
            "container-job": RuntimeAdapterDescriptor(
                runtime="container-job",
                version="0.1",
                title="Container Job Runtime Adapter",
                description="Execute a task as a local container-engine job skeleton with task-file injection and JSON result capture.",
                supports_local=True,
                input_modes=["task-file", "env"],
                output_modes=["json-object", "stdout"],
            ),
            "openai-chat": RuntimeAdapterDescriptor(
                runtime="openai-chat",
                version="0.1",
                title="OpenAI-Compatible Chat Adapter",
                description="Execute a task by calling an OpenAI-compatible chat completions endpoint, including OpenClaw Gateway.",
                supports_structured_output=True,
                supports_http=True,
                supports_json_schema=True,
                input_modes=["chat-messages", "json-schema"],
                output_modes=["assistant-message", "structured-json"],
            ),
            "claude-http": RuntimeAdapterDescriptor(
                runtime="claude-http",
                version="0.1",
                title="Claude HTTP Messages Adapter",
                description="Execute a task by calling an Anthropic-compatible Claude Messages endpoint over HTTP.",
                supports_http=True,
                input_modes=["messages-api", "system-prompt", "tools-api", "tool-results-api"],
                output_modes=["assistant-message", "tool-use", "json-object"],
            ),
            "ollama-chat": RuntimeAdapterDescriptor(
                runtime="ollama-chat",
                version="0.1",
                title="Ollama Chat Runtime Adapter",
                description="Execute a task by calling an Ollama-compatible local chat endpoint.",
                supports_http=True,
                input_modes=["chat-messages"],
                output_modes=["assistant-message"],
            ),
            "cli-json": RuntimeAdapterDescriptor(
                runtime="cli-json",
                version="0.1",
                title="CLI JSON Runtime Adapter",
                description="Execute a task by invoking a local CLI agent that accepts JSON over stdin/stdout.",
                supports_local=True,
                input_modes=["task-envelope"],
                output_modes=["json-object"],
            ),
            "claude-code-cli": RuntimeAdapterDescriptor(
                runtime="claude-code-cli",
                version="0.1",
                title="Claude Code CLI Adapter",
                description="Execute a task by invoking a local Claude Code style CLI with prompt text over stdin or argv and normalizing stdout back into an assistant result.",
                supports_local=True,
                input_modes=["prompt-text", "stdin", "argv"],
                output_modes=["assistant-message", "stdout", "json-object"],
            ),
        }

    def list_runtimes(self) -> list[dict[str, Any]]:
        return [descriptor.to_dict() for descriptor in self._runtimes.values()]

    def get_runtime(self, runtime: str) -> dict[str, Any]:
        runtime_key = str(runtime or "").strip().lower()
        if runtime_key not in self._runtimes:
            raise ValueError(f"unsupported runtime adapter: {runtime}")
        return self._runtimes[runtime_key].to_dict()

    def advertisement(self, enabled_runtimes: list[str] | None = None) -> dict[str, dict[str, Any]]:
        names = [str(item).strip().lower() for item in list(enabled_runtimes or self._runtimes.keys()) if str(item).strip()]
        advertised: dict[str, dict[str, Any]] = {}
        for name in names:
            if name in self._runtimes:
                advertised[name] = self._runtimes[name].to_dict()
        return advertised

    def normalize_binding(self, runtime: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        runtime_key = str(runtime or "").strip().lower()
        if runtime_key not in self._runtimes:
            raise ValueError(f"unsupported runtime adapter: {runtime}")
        payload = dict(options or {})
        payload["runtime"] = runtime_key
        payload.setdefault("bound_at", utc_now())
        return payload
