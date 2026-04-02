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

Current MCP normalization adds two stable bridge-level shapes:

- `payload._bridge.tool_call`
- `result.bridge_execution.tool_result`

This keeps tool-call import, worker execution, and protocol export aligned around the same schema instead of scattered fields.

Current A2A normalization adds two stable bridge-level shapes:

- `payload._bridge.message_envelope`
- `result.bridge_execution.message_result`

This keeps message import, worker execution, and protocol export aligned around the same structure.

### Runtime Adapters

These decide how a worker actually invokes an agent runtime.

- `http-json`
- `langgraph-http`
- `container-job`
- `openai-chat`
- `ollama-chat`
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

### 3. LangGraph HTTP Agent

Best for:

- LangGraph services already exposed over HTTP
- graph-based agents with thread and run state
- remote orchestrators that should stay behind a simple JSON boundary

Task binding shape:

```json
{
  "_runtime": {
    "runtime": "langgraph-http",
    "endpoint": "http://127.0.0.1:8123/runs/wait",
    "assistant_id": "assistant-graph-1",
    "config": {
      "recursion_limit": 5
    },
    "timeout_seconds": 60
  }
}
```

The worker sends:

- `thread_id`
- `input`
- `task_id`
- `workflow_id`
- `worker_id`
- optional `assistant_id`, `config`, and `checkpoint`

The response is normalized into:

- `run_id`
- `thread_id`
- `state`
- `assistant_message`
- raw `response`

### 4. Container Job Agent

Best for:

- docker or podman backed worker jobs
- isolated build or codegen runners
- future sandboxed execution that should stay separate from the main worker process

Task binding shape:

```json
{
  "_runtime": {
    "runtime": "container-job",
    "image": "python:3.12-alpine",
    "command": ["python", "/app/run.py"],
    "timeout_seconds": 120
  }
}
```

Current skeleton behavior:

- writes the normalized task to a local task file
- exposes task/runtime/output paths through env vars
- can build a docker-style `run` command when `engine_command` is omitted
- can use a custom local `engine_command` for testing or alternative runtimes
- normalizes `stdout_json` and `output_json` back into the task result

This is intentionally a skeleton, not a full container orchestration layer.

### 5. Ollama Chat Agent

Best for:

- local private inference
- offline-first laptop or workstation execution
- weak-network environments where the model must stay on the node
- WSL or Docker-hosted local models

Task binding shape:

```json
{
  "_runtime": {
    "runtime": "ollama-chat",
    "endpoint": "http://127.0.0.1:11434/api/chat",
    "model": "qwen2.5:7b",
    "prompt": "Summarize this task",
    "options": {
      "temperature": 0
    },
    "timeout_seconds": 60
  }
}
```

The worker sends a non-streaming Ollama-style chat request and normalizes the assistant message into the task result.

### 6. OpenAI-Compatible Chat Agent

Best for:

- OpenClaw Gateway
- OpenAI-compatible gateways
- model routers that already expose `/v1/chat/completions`

Task binding shape:

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

The worker sends an OpenAI-compatible chat completions request and normalizes the first assistant message into the task result.

## How To Adapt Common Agent Categories

### LangGraph / custom Python agents

- wrap as `http-json` if you want networked execution
- wrap as `cli-json` if you want local offline execution
- use `langgraph-http` if you already have an HTTP graph runner with thread/run semantics

### MCP-compatible agents

- use `mcp` bridge if you need MCP request/response compatibility
- optionally combine with `http-json` or `cli-json` as the execution runtime behind the bridge

### AutoGen / CrewAI / internal orchestration services

- expose a narrow HTTP execution endpoint
- map incoming task payload into that framework's planner/worker call
- return normalized JSON result

### OpenClaw Gateway

- use `openai-chat`
- point `endpoint` to the gateway chat-completions path
- keep AgentCoin responsible for routing, receipts, retry, and governance
- keep OpenClaw responsible for model execution

### Ollama-hosted local models

- use `ollama-chat`
- keep endpoint allowlists restricted to local or overlay addresses
- prefer this path for private or weak-network deployments

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
- `webhook-callback`

The current runtime layer is intentionally minimal, but the extension point is now stable enough to add these without changing the task model.
