from __future__ import annotations

from typing import Any


AGENTCOIN_CONTEXT_URL = "https://agentcoin.ai/ns/context/v0.1"


def context_document() -> dict[str, Any]:
    return {
        "@context": {
            "@version": 1.1,
            "agentcoin": "https://agentcoin.ai/ns#",
            "schema": "https://schema.org/",
            "name": "schema:name",
            "description": "schema:description",
            "capabilities": "agentcoin:capability",
            "protocols": "agentcoin:protocol",
            "runtimes": "agentcoin:runtime",
            "node_id": "agentcoin:nodeId",
            "workflow_id": "agentcoin:workflowId",
            "required_capabilities": "agentcoin:requiredCapability",
            "deliver_to": "agentcoin:deliverTo",
            "branch": "agentcoin:branch",
            "revision": "agentcoin:revision",
            "role": "agentcoin:role",
            "kind": "agentcoin:kind",
            "status": "agentcoin:status",
            "sender": "agentcoin:sender",
            "created_at": "schema:dateCreated",
            "available_at": "agentcoin:availableAt",
            "endpoints": "agentcoin:endpoint",
            "identity": "agentcoin:identity",
            "network": "agentcoin:network",
        }
    }


def agent_card_semantics(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "@context": AGENTCOIN_CONTEXT_URL,
        "@type": "agentcoin:AgentCard",
        "node_id": card.get("node_id"),
        "name": card.get("name"),
        "description": card.get("description"),
        "protocols": list(card.get("protocols") or []),
        "capabilities": list(card.get("capabilities") or []),
        "runtimes": list(card.get("runtimes") or []),
        "endpoints": dict(card.get("endpoints") or {}),
        "identity": dict(card.get("identity") or {}),
        "network": dict(card.get("network") or {}),
    }


def task_semantics(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "@context": AGENTCOIN_CONTEXT_URL,
        "@type": "agentcoin:TaskEnvelope",
        "node_id": task.get("sender"),
        "workflow_id": task.get("workflow_id"),
        "kind": task.get("kind"),
        "role": task.get("role"),
        "status": task.get("status"),
        "sender": task.get("sender"),
        "required_capabilities": list(task.get("required_capabilities") or []),
        "deliver_to": task.get("deliver_to"),
        "branch": task.get("branch"),
        "revision": task.get("revision"),
        "created_at": task.get("created_at"),
        "available_at": task.get("available_at"),
    }


def semantic_examples() -> dict[str, Any]:
    return {
        "agent_card": {
            "@context": AGENTCOIN_CONTEXT_URL,
            "@type": "agentcoin:AgentCard",
            "node_id": "agentcoin-local",
            "name": "AgentCoin Reference Node",
            "capabilities": ["task-routing", "offline-queue"],
            "runtimes": ["python", "openai-chat", "ollama-chat"],
        },
        "task_envelope": {
            "@context": AGENTCOIN_CONTEXT_URL,
            "@type": "agentcoin:TaskEnvelope",
            "node_id": "agentcoin-local",
            "workflow_id": "wf-1",
            "kind": "generic",
            "role": "worker",
            "required_capabilities": ["worker"],
            "status": "queued",
        },
    }
