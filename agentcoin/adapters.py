from __future__ import annotations

from typing import Any

from agentcoin.models import utc_now


class ExecutionAdapterRegistry:
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
        return result

    def _execute_mcp(self, task: dict[str, Any], *, bridge: dict[str, Any], worker_id: str) -> dict[str, Any]:
        payload = dict(task.get("payload", {}))
        method = str(bridge.get("method") or "")
        tool_name = str(bridge.get("tool_name") or payload.get("tool_name") or "")
        arguments = payload.get("arguments") or {}
        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "bridge-skeleton",
            "protocol": "mcp",
            "status": "completed",
        }
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
                        },
                    }
                ]
            },
        }
        return result

    def _execute_a2a(self, task: dict[str, Any], *, bridge: dict[str, Any], worker_id: str) -> dict[str, Any]:
        payload = dict(task.get("payload", {}))
        content = payload.get("content")
        metadata = payload.get("metadata") or {}
        intent = str(bridge.get("intent") or "")
        result = self._base_result(task, worker_id=worker_id)
        result["adapter"] = {
            "mode": "bridge-skeleton",
            "protocol": "a2a",
            "status": "completed",
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
        return result
