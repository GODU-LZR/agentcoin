from __future__ import annotations

from typing import Any


AGENTCOIN_CONTEXT_URL = "https://agentcoin.ai/ns/context/v0.1"

CAPABILITY_PROFILES: dict[str, dict[str, list[str] | str]] = {
    "worker": {"title": "Worker", "aliases": ["executor", "implementer"], "implies": []},
    "codegen": {"title": "Code Generation Worker", "aliases": ["coder", "coding", "developer"], "implies": ["worker"]},
    "reviewer": {"title": "Reviewer", "aliases": ["review"], "implies": []},
    "ai-reviewer": {"title": "AI Reviewer", "aliases": ["ai-review", "llm-reviewer"], "implies": ["reviewer"]},
    "human-reviewer": {"title": "Human Reviewer", "aliases": ["human-review"], "implies": ["reviewer"]},
    "committee-member": {"title": "Dispute Committee Member", "aliases": ["juror", "arbiter"], "implies": ["reviewer"]},
    "planner": {"title": "Planner", "aliases": ["coordinator", "orchestrator"], "implies": []},
    "task-routing": {"title": "Task Router", "aliases": ["dispatcher", "router"], "implies": ["planner"]},
    "local-command": {"title": "Local Command Executor", "aliases": ["shell", "cli-tool"], "implies": ["worker"]},
    "http-json": {"title": "HTTP JSON Runtime", "aliases": ["http-agent"], "implies": ["worker"]},
    "openai-chat": {"title": "OpenAI-Compatible Chat Runtime", "aliases": ["openai-compatible", "openclaw-gateway"], "implies": ["worker"]},
    "ollama-chat": {"title": "Ollama Chat Runtime", "aliases": ["ollama", "local-llm"], "implies": ["worker"]},
}


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


def capability_schema() -> dict[str, Any]:
    return {
        "@context": AGENTCOIN_CONTEXT_URL,
        "@type": "agentcoin:CapabilitySchema",
        "capabilities": [
            {
                "id": capability,
                "title": profile.get("title"),
                "aliases": list(profile.get("aliases") or []),
                "implies": list(profile.get("implies") or []),
            }
            for capability, profile in sorted(CAPABILITY_PROFILES.items())
        ],
    }


def expand_capabilities(capabilities: list[str] | None) -> set[str]:
    raw_values = [str(item or "").strip().lower() for item in list(capabilities or []) if str(item or "").strip()]
    expanded = set(raw_values)
    alias_map: dict[str, str] = {}
    for capability, profile in CAPABILITY_PROFILES.items():
        alias_map[capability] = capability
        for alias in list(profile.get("aliases") or []):
            alias_map[str(alias).strip().lower()] = capability
    queue = [alias_map.get(item, item) for item in raw_values]
    while queue:
        current = queue.pop(0)
        if current in expanded:
            pass
        expanded.add(current)
        profile = CAPABILITY_PROFILES.get(current) or {}
        for implied in list(profile.get("implies") or []):
            implied_key = str(implied).strip().lower()
            if implied_key and implied_key not in expanded:
                queue.append(implied_key)
    normalized = set(alias_map.get(item, item) for item in expanded)
    return normalized | expanded


def capabilities_satisfy(required_capabilities: list[str] | None, available_capabilities: list[str] | None) -> bool:
    required = expand_capabilities(required_capabilities)
    available = expand_capabilities(available_capabilities)
    return required.issubset(available)


def capability_match_report(required_capabilities: list[str] | None, available_capabilities: list[str] | None) -> dict[str, Any]:
    required_raw = [str(item or "").strip().lower() for item in list(required_capabilities or []) if str(item or "").strip()]
    available_raw = [str(item or "").strip().lower() for item in list(available_capabilities or []) if str(item or "").strip()]
    required_expanded = expand_capabilities(required_capabilities)
    available_expanded = expand_capabilities(available_capabilities)
    exact_matches = sorted(set(required_raw).intersection(set(available_raw)))
    expanded_matches = sorted(required_expanded.intersection(available_expanded))
    missing = sorted(required_expanded - available_expanded)
    return {
        "required_raw": required_raw,
        "available_raw": available_raw,
        "required_expanded": sorted(required_expanded),
        "available_expanded": sorted(available_expanded),
        "exact_matches": exact_matches,
        "expanded_matches": expanded_matches,
        "missing": missing,
        "satisfied": not missing,
    }
