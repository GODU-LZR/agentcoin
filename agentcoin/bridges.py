from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentcoin.models import TaskEnvelope, utc_now


@dataclass(frozen=True, slots=True)
class BridgeDescriptor:
    protocol: str
    version: str
    title: str
    description: str
    import_endpoint: str = "/v1/bridges/import"
    export_endpoint: str = "/v1/bridges/export"

    def to_dict(self) -> dict[str, str]:
        return {
            "protocol": self.protocol,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "import_endpoint": self.import_endpoint,
            "export_endpoint": self.export_endpoint,
        }


class BridgeRegistry:
    def __init__(self, enabled_protocols: list[str] | None = None) -> None:
        self.enabled_protocols = list(enabled_protocols or ["mcp", "a2a"])
        self._bridges: dict[str, BridgeDescriptor] = {
            "mcp": BridgeDescriptor(
                protocol="mcp",
                version="0.1",
                title="MCP Bridge",
                description="Translate MCP-style tool and request envelopes into AgentCoin tasks.",
            ),
            "a2a": BridgeDescriptor(
                protocol="a2a",
                version="0.1",
                title="A2A Bridge",
                description="Translate agent-to-agent message envelopes into AgentCoin tasks.",
            ),
        }

    @property
    def protocols(self) -> list[str]:
        return [f"{protocol}-bridge/0.1" for protocol in self.enabled_protocols if protocol in self._bridges]

    def list_bridges(self) -> list[dict[str, str]]:
        return [self._bridges[protocol].to_dict() for protocol in self.enabled_protocols if protocol in self._bridges]

    def import_task(self, protocol: str, message: dict[str, Any], task_overrides: dict[str, Any] | None = None) -> TaskEnvelope:
        protocol_key = str(protocol or "").strip().lower()
        if protocol_key not in self._bridges or protocol_key not in self.enabled_protocols:
            raise ValueError(f"unsupported bridge protocol: {protocol}")
        overrides = dict(task_overrides or {})
        if protocol_key == "mcp":
            return self._import_mcp(message, overrides)
        if protocol_key == "a2a":
            return self._import_a2a(message, overrides)
        raise ValueError(f"unsupported bridge protocol: {protocol}")

    def export_message(self, protocol: str, task: dict[str, Any], result: dict[str, Any] | None = None) -> dict[str, Any]:
        protocol_key = str(protocol or "").strip().lower()
        if protocol_key not in self._bridges or protocol_key not in self.enabled_protocols:
            raise ValueError(f"unsupported bridge protocol: {protocol}")
        if protocol_key == "mcp":
            return self._export_mcp(task, result)
        if protocol_key == "a2a":
            return self._export_a2a(task, result)
        raise ValueError(f"unsupported bridge protocol: {protocol}")

    @staticmethod
    def _base_bridge_payload(protocol: str, message: dict[str, Any]) -> dict[str, Any]:
        return {
            "_bridge": {
                "protocol": protocol,
                "imported_at": utc_now(),
                "source_message": message,
            }
        }

    def _import_mcp(self, message: dict[str, Any], overrides: dict[str, Any]) -> TaskEnvelope:
        method = str(message.get("method") or "").strip()
        if not method:
            raise ValueError("mcp bridge requires message.method")
        params = dict(message.get("params") or {})
        bridge_payload = self._base_bridge_payload("mcp", message)
        bridge_payload["_bridge"].update(
            {
                "request_id": message.get("id"),
                "method": method,
                "tool_name": params.get("name") or params.get("tool"),
            }
        )
        payload = dict(overrides.pop("payload", {}) or {})
        payload.update(bridge_payload)
        if "arguments" in params and "arguments" not in payload:
            payload["arguments"] = params.get("arguments")
        if "content" in params and "content" not in payload:
            payload["content"] = params.get("content")

        tool_name = str(params.get("name") or params.get("tool") or "").strip()
        default_required_capabilities = list(overrides.pop("required_capabilities", []) or [])
        if not default_required_capabilities and tool_name:
            default_required_capabilities = [tool_name]
        kind = str(overrides.pop("kind", "")) or ("tool-call" if tool_name else "mcp-call")

        return TaskEnvelope.from_dict(
            {
                "id": overrides.pop("id", None) or str(message.get("id") or ""),
                "kind": kind,
                "payload": payload,
                "sender": overrides.pop("sender", None) or str(message.get("sender") or "bridge:mcp"),
                "role": overrides.pop("role", None) or "worker",
                "required_capabilities": default_required_capabilities,
                "commit_message": overrides.pop("commit_message", None) or f"bridge import mcp {method}",
                **overrides,
            }
        )

    def _import_a2a(self, message: dict[str, Any], overrides: dict[str, Any]) -> TaskEnvelope:
        intent = str(message.get("intent") or message.get("type") or "").strip()
        if not intent:
            raise ValueError("a2a bridge requires message.intent or message.type")
        bridge_payload = self._base_bridge_payload("a2a", message)
        bridge_payload["_bridge"].update(
            {
                "message_id": message.get("message_id"),
                "conversation_id": message.get("conversation_id"),
                "intent": intent,
                "in_reply_to": message.get("in_reply_to"),
            }
        )
        payload = dict(overrides.pop("payload", {}) or {})
        payload.update(bridge_payload)
        if "content" in message and "content" not in payload:
            payload["content"] = message.get("content")
        if "metadata" in message and "metadata" not in payload:
            payload["metadata"] = message.get("metadata")

        default_required_capabilities = list(overrides.pop("required_capabilities", []) or list(message.get("required_capabilities") or []))
        kind = str(overrides.pop("kind", "")) or "a2a-message"

        return TaskEnvelope.from_dict(
            {
                "id": overrides.pop("id", None) or str(message.get("message_id") or ""),
                "kind": kind,
                "payload": payload,
                "sender": overrides.pop("sender", None) or str(message.get("sender") or "bridge:a2a"),
                "role": overrides.pop("role", None) or "worker",
                "required_capabilities": default_required_capabilities,
                "commit_message": overrides.pop("commit_message", None) or f"bridge import a2a {intent}",
                "workflow_id": overrides.pop("workflow_id", None) or message.get("conversation_id"),
                **overrides,
            }
        )

    @staticmethod
    def _export_mcp(task: dict[str, Any], result: dict[str, Any] | None = None) -> dict[str, Any]:
        bridge = dict(task.get("payload", {}).get("_bridge") or {})
        return {
            "protocol": "mcp",
            "message": {
                "jsonrpc": "2.0",
                "id": bridge.get("request_id") or task["id"],
                "result": {
                    "task_id": task["id"],
                    "status": task["status"],
                    "kind": task["kind"],
                    "sender": task["sender"],
                    "result": result if result is not None else task.get("result"),
                    "bridge": {
                        "method": bridge.get("method"),
                        "tool_name": bridge.get("tool_name"),
                    },
                },
            },
        }

    @staticmethod
    def _export_a2a(task: dict[str, Any], result: dict[str, Any] | None = None) -> dict[str, Any]:
        bridge = dict(task.get("payload", {}).get("_bridge") or {})
        return {
            "protocol": "a2a",
            "message": {
                "message_id": task["id"],
                "conversation_id": bridge.get("conversation_id") or task.get("workflow_id") or task["id"],
                "sender": task["sender"],
                "intent": "task.result",
                "in_reply_to": bridge.get("message_id"),
                "task": {
                    "id": task["id"],
                    "status": task["status"],
                    "kind": task["kind"],
                    "result": result if result is not None else task.get("result"),
                },
            },
        }
