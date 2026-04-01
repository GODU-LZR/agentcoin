# OpenClaw Integration

## Goal

Use OpenClaw through AgentCoin without adding a one-off protocol branch that would drift away from the blueprint.

The current recommended path is:

- keep AgentCoin responsible for orchestration, routing, review, receipts, and weak-network handling
- treat OpenClaw as an execution runtime behind the interoperability layer
- connect through an OpenAI-compatible chat endpoint

## Recommended Path

Use the `openai-chat` runtime adapter against an OpenClaw Gateway endpoint.

If you want a one-step bind from the node API, use:

```bash
curl -X POST http://127.0.0.1:8080/v1/integrations/openclaw/bind \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task-1",
    "endpoint": "http://127.0.0.1:3000/v1/chat/completions",
    "model": "openclaw/gateway",
    "auth_token": "replace-me",
    "prompt": "Review this task",
    "temperature": 0
  }'
```

Example task binding:

```json
{
  "_runtime": {
    "runtime": "openai-chat",
    "endpoint": "http://127.0.0.1:3000/v1/chat/completions",
    "model": "openclaw/gateway",
    "auth_token": "replace-me",
    "prompt": "Review this task",
    "temperature": 0,
    "timeout_seconds": 60
  }
}
```

## Why This Stays Aligned With The Blueprint

- it uses a standard protocol boundary instead of a hardcoded one-off integration
- it keeps execution adapters separate from bridge adapters
- it preserves AgentCoin as the coordination layer and OpenClaw as a runtime layer
- it remains compatible with future model gateways that expose the same interface

## Execution Flow

1. create a normal AgentCoin task
2. bind `_runtime.runtime = openai-chat`
3. point `endpoint` at the OpenClaw Gateway
4. worker claims the task
5. worker sends an OpenAI-compatible chat completions request
6. assistant response is normalized back into the task result

## Security Notes

- keep `allowed_runtime_kinds` limited to `openai-chat`
- keep `allowed_http_hosts` limited to loopback, overlay, or trusted internal addresses
- prefer short-lived gateway tokens
- do not expose OpenClaw directly on a public bind unless you also place it behind a proper gateway

## When To Use Another Adapter Instead

- if OpenClaw exposes a custom tool or plugin protocol you need to preserve semantically, use a bridge
- if OpenClaw is wrapped as a local script, use `cli-json`
- if you only need a generic service call and do not care about OpenAI-compatible semantics, use `http-json`
