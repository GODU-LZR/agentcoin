# Agent Adapter Strategy

## Goal

AgentCoin should adapt existing agent runtimes rather than forcing every agent into one framework. The current design separates adaptation into two layers:

- `protocol bridge`: translate an external protocol into a durable AgentCoin task
- `runtime adapter`: execute a task against a concrete runtime such as HTTP or CLI

This separation matters because protocol compatibility and execution compatibility are different problems.

## Current Adapter Types

### Bridge Adapters

These preserve external message shape and import/export semantics.

- `mcp`
- `a2a`

They write protocol context into `payload._bridge`.

### Runtime Adapters

These decide how a worker actually invokes an agent runtime.

- `http-json`
- `cli-json`

They write runtime context into `payload._runtime`.

## Recommended Integration Patterns

### 1. HTTP JSON Agent

Best for:

- internal service agents
- model gateways
- containerized workers
- cross-platform wrappers

Task binding shape:

```json
{
  "_runtime": {
    "runtime": "http-json",
    "endpoint": "http://127.0.0.1:9000/invoke",
    "method": "POST",
    "timeout_seconds": 15
  }
}
```

The worker sends:

- `worker_id`
- full `task`
- `runtime`

This is the best default for heterogeneous agents because it decouples AgentCoin from the runtime language.

### 2. CLI JSON Agent

Best for:

- local research agents
- script-first tools
- LangGraph/CrewAI wrappers exposed as a command
- offline-first execution on laptops or WSL

Task binding shape:

```json
{
  "_runtime": {
    "runtime": "cli-json",
    "command": ["python", "my_agent.py"],
    "cwd": ".",
    "timeout_seconds": 30
  }
}
```

The worker sends JSON over `stdin` and expects JSON on `stdout`.

## How To Adapt Common Agent Categories

### LangGraph / custom Python agents

- wrap as `http-json` if you want networked execution
- wrap as `cli-json` if you want local offline execution

### MCP-compatible agents

- use `mcp` bridge if you need MCP request/response compatibility
- optionally combine with `http-json` or `cli-json` as the execution runtime behind the bridge

### AutoGen / CrewAI / internal orchestration services

- expose a narrow HTTP execution endpoint
- map incoming task payload into that framework's planner/worker call
- return normalized JSON result

### Shell / script / codegen agents

- expose as `cli-json`
- keep command allowlists narrow
- confine execution with `workspace_root`

## Security Boundary

Runtime adapters are policy-gated:

- `allowed_runtime_kinds`
- `allowed_http_hosts`
- `allow_subprocess`
- `allowed_commands`

This means AgentCoin can adapt many agent shapes without making every worker fully trusted.

## Suggested Next Adapters

- `openai-responses`
- `langgraph-http`
- `ollama-http`
- `webhook-callback`
- `container-job`

The current runtime layer is intentionally minimal, but the extension point is now stable enough to add these without changing the task model.
