from __future__ import annotations

import argparse
import copy
import json
import logging
import time
from typing import Any
from urllib import error

from agentcoin.adapters import AdapterPolicy, ExecutionAdapterRegistry
from agentcoin.models import utc_now
from agentcoin.net import OutboundNetworkConfig, OutboundTransport
from agentcoin.receipts import build_deterministic_execution_receipt, build_policy_receipt

LOG = logging.getLogger("agentcoin.worker")


class WorkerLoop:
    _OPAQUE_TOP_LEVEL_INPUT_FIELDS = ("messages", "content", "prompt", "query", "instruction")
    _OPAQUE_RUNTIME_INPUT_FIELDS = ("messages", "prompt", "assistant_tool_uses", "tool_results")
    _OPAQUE_RUNTIME_REDACTED_FIELDS = {
        "auth_token",
        "headers",
        "messages",
        "prompt",
        "assistant_tool_uses",
        "tool_results",
        "env",
        "args",
        "command",
        "executable_path",
    }

    def __init__(
        self,
        node_url: str,
        token: str,
        worker_id: str,
        capabilities: list[str],
        lease_seconds: int = 60,
        adapter_policy: AdapterPolicy | None = None,
        network: OutboundNetworkConfig | None = None,
        request_timeout_seconds: float = 10,
    ) -> None:
        self.node_url = node_url.rstrip("/")
        self.token = token
        self.worker_id = worker_id
        self.capabilities = capabilities
        self.lease_seconds = lease_seconds
        self.transport = OutboundTransport(network)
        self.adapters = ExecutionAdapterRegistry(adapter_policy, transport=self.transport)
        self.request_timeout_seconds = request_timeout_seconds

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self.transport.request_json(
                f"{self.node_url}{path}",
                method="POST",
                payload=payload,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.request_timeout_seconds,
            )
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            LOG.warning("request failed path=%s worker_id=%s error=%s", path, self.worker_id, exc)
            return None

    def run_once(self) -> bool:
        claimed = self._post_json(
            "/v1/tasks/claim",
            {
                "worker_id": self.worker_id,
                "worker_capabilities": self.capabilities,
                "lease_seconds": self.lease_seconds,
            },
        )
        if claimed is None:
            return False
        task = claimed.get("task")
        if not task:
            return False

        LOG.info("claimed task %s kind=%s", task["id"], task["kind"])
        result = self.execute_task(task)
        ack = self._post_json(
            "/v1/tasks/ack",
            {
                "task_id": task["id"],
                "worker_id": self.worker_id,
                "lease_token": task["lease_token"],
                "success": True,
                "result": result,
            },
        )
        if ack is None:
            LOG.warning("ack failed for task %s; lease will expire and task may be retried", task["id"])
            return False
        LOG.info("acked task %s ok=%s", task["id"], ack.get("ok"))
        return True

    @staticmethod
    def _json_schema_type_matches(value: Any, expected_type: str) -> bool:
        normalized = str(expected_type or "").strip().lower()
        if normalized == "object":
            return isinstance(value, dict)
        if normalized == "array":
            return isinstance(value, list)
        if normalized == "string":
            return isinstance(value, str)
        if normalized == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if normalized == "number":
            return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
        if normalized == "boolean":
            return isinstance(value, bool)
        return True

    @classmethod
    def _validate_json_schema(cls, value: Any, schema: dict[str, Any], *, path: str = "input") -> list[str]:
        if not isinstance(schema, dict) or not schema:
            return []
        errors: list[str] = []
        expected_type = str(schema.get("type") or "").strip().lower()
        if expected_type and not cls._json_schema_type_matches(value, expected_type):
            return [f"{path} must be {expected_type}"]
        if expected_type == "object" and isinstance(value, dict):
            properties = dict(schema.get("properties") or {})
            required = [str(item) for item in list(schema.get("required") or []) if str(item).strip()]
            for key in required:
                if key not in value:
                    errors.append(f"{path}.{key} is required")
            if schema.get("additionalProperties") is False:
                for key in value:
                    if key not in properties:
                        errors.append(f"{path}.{key} is not allowed")
            for key, property_schema in properties.items():
                if key in value:
                    errors.extend(cls._validate_json_schema(value[key], dict(property_schema or {}), path=f"{path}.{key}"))
            return errors
        if expected_type == "array" and isinstance(value, list):
            item_schema = dict(schema.get("items") or {})
            for index, item in enumerate(value):
                errors.extend(cls._validate_json_schema(item, item_schema, path=f"{path}[{index}]"))
            return errors
        return errors

    def _guardrail_rejection(self, task: dict[str, Any], *, reason: str, errors: list[str] | None = None) -> dict[str, Any]:
        artifacts: dict[str, Any] = {}
        if errors:
            artifacts["validation_errors"] = list(errors)
        return {
            "worker_id": self.worker_id,
            "handled_kind": task["kind"],
            "handled_at": utc_now(),
            "workflow_id": task.get("workflow_id"),
            "branch": task.get("branch"),
            "revision": task.get("revision"),
            "echo": self._redact_opaque_payload(task.get("payload", {})),
            "adapter": {
                "mode": "opaque-execution-guardrail",
                "protocol": "opaque-execution",
                "status": "rejected",
                "reason": reason,
            },
            "policy_receipt": build_policy_receipt(
                protocol="opaque-execution",
                decision="rejected",
                reason=reason,
                mode="opaque-execution-guardrail",
                **artifacts,
            ),
            "execution_receipt": build_deterministic_execution_receipt(
                task,
                worker_id=self.worker_id,
                protocol="opaque-execution",
                status="rejected",
                outcome="opaque-guardrail-rejected",
                artifacts=artifacts,
            ),
        }

    def _enforce_service_guardrails(self, task: dict[str, Any]) -> dict[str, Any] | None:
        payload = dict(task.get("payload") or {})
        service = dict(payload.get("_service") or {})
        opaque = dict(payload.get("_opaque_execution") or {})
        if not service and not opaque:
            return None

        runtime = dict(payload.get("_runtime") or {})
        if bool(opaque.get("enabled")):
            if isinstance(payload.get("messages"), list) and payload.get("messages"):
                return self._guardrail_rejection(
                    task,
                    reason="opaque service does not allow free-form payload.messages input",
                )
            if isinstance(runtime.get("messages"), list) and runtime.get("messages"):
                return self._guardrail_rejection(
                    task,
                    reason="opaque service does not allow runtime.messages input",
                )

        if bool(service.get("strict_input")):
            schema = dict(service.get("input_schema") or {})
            if schema:
                validation_errors = self._validate_json_schema(payload.get("input"), schema)
                if validation_errors:
                    return self._guardrail_rejection(
                        task,
                        reason="opaque service input does not satisfy declared schema",
                        errors=validation_errors,
                    )
        return None

    @staticmethod
    def _opaque_enabled(task: dict[str, Any]) -> bool:
        payload = dict(task.get("payload") or {})
        opaque = dict(payload.get("_opaque_execution") or {})
        service = dict(payload.get("_service") or {})
        return bool(opaque.get("enabled")) or str(service.get("privacy_level") or "").strip().lower() == "opaque"

    @classmethod
    def _sanitize_runtime_for_opaque_execution(cls, runtime: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        sanitized_runtime = copy.deepcopy(dict(runtime or {}))
        removed_fields: list[str] = []
        for field_name in cls._OPAQUE_RUNTIME_INPUT_FIELDS:
            if field_name in sanitized_runtime:
                sanitized_runtime.pop(field_name, None)
                removed_fields.append(f"_runtime.{field_name}")
        return sanitized_runtime, removed_fields

    @classmethod
    def _build_execution_task(cls, task: dict[str, Any]) -> dict[str, Any]:
        if not cls._opaque_enabled(task):
            return task
        execution_task = copy.deepcopy(task)
        payload = dict(execution_task.get("payload") or {})
        removed_fields: list[str] = []
        for field_name in cls._OPAQUE_TOP_LEVEL_INPUT_FIELDS:
            if field_name in payload:
                payload.pop(field_name, None)
                removed_fields.append(field_name)
        runtime = dict(payload.get("_runtime") or {})
        if runtime:
            sanitized_runtime, runtime_removed_fields = cls._sanitize_runtime_for_opaque_execution(runtime)
            payload["_runtime"] = sanitized_runtime
            removed_fields.extend(runtime_removed_fields)
        opaque = dict(payload.get("_opaque_execution") or {})
        opaque["enabled"] = True
        if removed_fields:
            opaque["runtime_input_sanitized"] = True
            opaque["removed_input_fields"] = removed_fields
        payload["_opaque_execution"] = opaque
        execution_task["payload"] = payload
        return execution_task

    @classmethod
    def _redact_runtime_for_opaque_result(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        redacted_runtime: dict[str, Any] = {}
        removed_fields: list[str] = []
        for key, value in dict(runtime or {}).items():
            if key in cls._OPAQUE_RUNTIME_REDACTED_FIELDS:
                removed_fields.append(key)
                continue
            redacted_runtime[key] = value
        if removed_fields:
            redacted_runtime["redacted_fields"] = sorted(removed_fields)
            redacted_runtime["opaque_redacted"] = True
        return redacted_runtime

    @classmethod
    def _redact_opaque_payload(cls, payload: Any) -> Any:
        if not isinstance(payload, dict):
            return payload
        redacted_payload = copy.deepcopy(payload)
        removed_fields: list[str] = []
        for field_name in cls._OPAQUE_TOP_LEVEL_INPUT_FIELDS:
            if field_name in redacted_payload:
                redacted_payload.pop(field_name, None)
                removed_fields.append(field_name)
        if "_runtime" in redacted_payload:
            redacted_payload["_runtime"] = cls._redact_runtime_for_opaque_result(dict(redacted_payload.get("_runtime") or {}))
        service = dict(redacted_payload.get("_service") or {})
        if service:
            redacted_payload["_service"] = {
                "service_id": service.get("service_id"),
                "privacy_level": service.get("privacy_level"),
                "strict_input": bool(service.get("strict_input")),
                "opaque_execution": bool(service.get("opaque_execution")),
            }
        opaque = dict(redacted_payload.get("_opaque_execution") or {})
        if opaque:
            opaque["enabled"] = True
            opaque["result_redacted"] = True
            if removed_fields:
                opaque["redacted_payload_fields"] = removed_fields
            redacted_payload["_opaque_execution"] = opaque
        if removed_fields:
            redacted_payload["redacted_fields"] = removed_fields
        return redacted_payload

    @classmethod
    def _redact_runtime_execution_for_opaque_result(cls, runtime_execution: dict[str, Any]) -> dict[str, Any]:
        redacted_execution = copy.deepcopy(dict(runtime_execution or {}))
        if isinstance(redacted_execution.get("request"), dict):
            request_payload = dict(redacted_execution.get("request") or {})
            redacted_execution["request"] = {
                "redacted": True,
                "keys": sorted(request_payload.keys()),
                "message_count": len(list(request_payload.get("messages") or [])) if isinstance(request_payload.get("messages"), list) else 0,
                "tool_count": len(list(request_payload.get("tools") or [])) if isinstance(request_payload.get("tools"), list) else 0,
                "opaque_execution": True,
            }
        redacted_execution["opaque_redacted"] = True
        return redacted_execution

    @classmethod
    def _redact_result_for_opaque_execution(cls, task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if not cls._opaque_enabled(task):
            return result
        redacted_result = copy.deepcopy(dict(result or {}))
        redacted_result["echo"] = cls._redact_opaque_payload(task.get("payload", {}))
        if isinstance(redacted_result.get("runtime_execution"), dict):
            redacted_result["runtime_execution"] = cls._redact_runtime_execution_for_opaque_result(
                dict(redacted_result.get("runtime_execution") or {})
            )
        redacted_result["opaque_execution"] = {
            "enabled": True,
            "privacy_level": dict(task.get("payload") or {}).get("_opaque_execution", {}).get("privacy_level")
            or dict(task.get("payload") or {}).get("_service", {}).get("privacy_level")
            or "opaque",
            "result_redacted": True,
        }
        return redacted_result

    def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        guardrail_result = self._enforce_service_guardrails(task)
        if guardrail_result is not None:
            return guardrail_result
        execution_task = self._build_execution_task(task)
        result = self.adapters.execute(execution_task, worker_id=self.worker_id)
        result.setdefault("worker_id", self.worker_id)
        result.setdefault("handled_kind", task["kind"])
        result.setdefault("handled_at", utc_now())
        result.setdefault("workflow_id", task.get("workflow_id"))
        result.setdefault("branch", task.get("branch"))
        result.setdefault("revision", task.get("revision"))
        result.setdefault("echo", task.get("payload", {}))
        return self._redact_result_for_opaque_execution(task, result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an AgentCoin worker loop skeleton.")
    parser.add_argument("--node-url", required=True, help="Base URL of the AgentCoin node.")
    parser.add_argument("--token", required=True, help="Bearer token for the node.")
    parser.add_argument("--worker-id", required=True, help="Stable worker identifier.")
    parser.add_argument(
        "--capability",
        dest="capabilities",
        action="append",
        default=[],
        help="Repeatable worker capability. Example: --capability worker",
    )
    parser.add_argument("--lease-seconds", type=int, default=60, help="Requested lease duration.")
    parser.add_argument("--poll-seconds", type=float, default=2.0, help="Sleep time between empty polls.")
    parser.add_argument(
        "--allow-tool",
        dest="allowed_tools",
        action="append",
        default=[],
        help="Repeatable MCP tool allowlist entry.",
    )
    parser.add_argument(
        "--allow-intent",
        dest="allowed_intents",
        action="append",
        default=[],
        help="Repeatable A2A intent allowlist entry.",
    )
    parser.add_argument(
        "--allow-runtime",
        dest="allowed_runtime_kinds",
        action="append",
        default=[],
        help="Repeatable runtime adapter allowlist entry such as http-json or cli-json.",
    )
    parser.add_argument(
        "--allow-http-host",
        dest="allowed_http_hosts",
        action="append",
        default=[],
        help="Repeatable runtime HTTP host allowlist entry. Supports exact hosts, suffixes, and CIDR.",
    )
    parser.add_argument("--allow-subprocess", action="store_true", help="Enable sandboxed subprocess execution for local-command tool.")
    parser.add_argument(
        "--allow-command",
        dest="allowed_commands",
        action="append",
        default=[],
        help="Repeatable subprocess executable allowlist entry.",
    )
    parser.add_argument("--workspace-root", help="Restrict subprocess cwd to this root path.")
    parser.add_argument("--subprocess-timeout-seconds", type=int, default=10, help="Timeout for allowlisted subprocess execution.")
    parser.add_argument("--http-proxy", help="Optional outbound HTTP proxy URL for node communication.")
    parser.add_argument("--https-proxy", help="Optional outbound HTTPS proxy URL for node communication.")
    parser.add_argument(
        "--no-proxy-host",
        dest="no_proxy_hosts",
        action="append",
        default=[],
        help="Repeatable hostname, suffix, or CIDR rule that should bypass proxy.",
    )
    parser.add_argument(
        "--disable-env-proxy",
        action="store_true",
        help="Ignore environment HTTP(S)_PROXY values for worker-to-node requests.",
    )
    parser.add_argument("--request-timeout-seconds", type=float, default=10, help="Timeout for worker-to-node API requests.")
    parser.add_argument("--once", action="store_true", help="Claim at most one task and exit.")
    parser.add_argument("--log-level", default="INFO", help="Python logging level.")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    loop = WorkerLoop(
        node_url=args.node_url,
        token=args.token,
        worker_id=args.worker_id,
        capabilities=args.capabilities,
        lease_seconds=args.lease_seconds,
        adapter_policy=AdapterPolicy(
            allowed_mcp_tools=args.allowed_tools,
            allowed_a2a_intents=args.allowed_intents,
            allowed_runtime_kinds=args.allowed_runtime_kinds,
            allowed_http_hosts=args.allowed_http_hosts,
            allow_subprocess=args.allow_subprocess,
            allowed_commands=args.allowed_commands,
            subprocess_timeout_seconds=args.subprocess_timeout_seconds,
            workspace_root=args.workspace_root,
        ),
        network=OutboundNetworkConfig(
            http_proxy=args.http_proxy,
            https_proxy=args.https_proxy,
            no_proxy_hosts=args.no_proxy_hosts or ["127.0.0.1", "localhost", "::1"],
            use_environment_proxies=not args.disable_env_proxy,
        ),
        request_timeout_seconds=args.request_timeout_seconds,
    )

    while True:
        handled = loop.run_once()
        if args.once:
            break
        if not handled:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
