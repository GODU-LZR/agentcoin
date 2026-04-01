# AgentCoin Project Documentation

## Positioning

AgentCoin is a decentralized agent collaboration protocol and reference runtime. Its purpose is to let heterogeneous agents cooperate across nodes, survive weak network conditions, and maintain verifiable workflow history.

The current repository contains:

- a multilingual whitepaper
- a Python 3.11 standard-library reference node
- a lightweight worker loop
- durable local task, inbox, outbox, and workflow state persistence
- Git-like workflow lineage, merge, and finalize semantics
- weak-network retry, dead-letter, and local fallback behavior
- Git-native repository inspection and task context attachment

## Design Goals

- Cross-platform: macOS, Linux, Windows, WSL
- Lightweight: dependency-minimal reference implementation
- Agent-compatible: generic HTTP + JSON protocol boundary
- Offline-first: useful behavior even under unstable or interrupted networking
- Secure-by-default: loopback bind and bearer-token protected write APIs
- Workflow-native: branch, merge, lineage, and replay semantics

## Repository Layout

- `agentcoin/`: runtime source code
- `configs/`: example configuration
- `docs/architecture/`: architecture and connectivity notes
- `docs/project/`: project-level documentation
- `docs/testing/`: testing strategy and verification notes
- `docs/whitepaper/`: multilingual whitepapers
- `compose.yaml`: local Docker Compose entrypoint

## Runtime Components

### `agentcoin.node`

The node is the main runtime process. It exposes HTTP endpoints for:

- agent capability cards
- local task ingestion
- peer routing
- protocol bridge import and export
- inbox and outbox delivery
- lease-based claiming
- workflow fanout, merge, summary, and finalize
- dead-letter inspection and replay

### `agentcoin.store`

`NodeStore` is the persistence layer built on SQLite. It stores:

- tasks
- inbox messages
- outbox deliveries
- delivery receipts
- peer cards
- workflow terminal states

This is the durability backbone for offline-first behavior.

### `agentcoin.worker`

The worker loop is intentionally minimal. It demonstrates:

- capability-based claiming
- task ACK completion
- graceful handling of temporary node connectivity failures

It is a reference execution adapter, not yet a full production executor.

### `agentcoin.config`

Configuration defines:

- node identity and bind settings
- auth token
- HMAC signing secret
- inbound signature requirement
- SSH identity principal and key paths
- persistence path
- peer definitions
- overlay metadata
- retry and fallback limits

## Core Runtime Model

### Task Model

Each task is a durable envelope with:

- identity: `id`, `kind`, `sender`
- scheduling: `priority`, `available_at`
- delivery: `deliver_to`, `delivery_status`
- routing: `required_capabilities`, `role`
- workflow lineage: `workflow_id`, `parent_task_id`, `branch`, `revision`, `merge_parent_ids`, `depends_on`, `commit_message`
- retry metadata: `attempts`, `max_attempts`, `retry_backoff_seconds`, `last_error`

### Queue Model

AgentCoin currently has two durable queues:

- task queue: work claiming, lease management, ACK, retry, dead-letter
- message queue: inter-node outbox, inbox dedupe, delivery ACK, replay

### Bridge Model

The bridge layer lets AgentCoin ingest external protocol messages without replacing its internal task model.

Current bridge capabilities:

- MCP message import
- A2A message import
- bridge metadata persisted in `payload._bridge`
- export of task state or result back into bridge-shaped response payloads
- bridge-aware worker execution skeleton with normalized MCP / A2A result shapes
- worker-side allowlists and restricted subprocess execution for bridge tasks

### Git Adapter Model

AgentCoin does not replace Git. It now adapts to Git repositories directly.

Current Git-native capabilities:

- inspect repository status
- inspect diffs
- create branches
- attach repository context to tasks

This keeps source-of-truth code history in Git while AgentCoin handles coordination and policy.

### Workflow Model

Workflows are treated as DAGs rather than flat queues.

Lifecycle:

1. create a root task
2. fan out worker branches
3. claim and complete branch tasks
4. create merge or reviewer tasks
5. finalize terminal workflow summary

This gives the system Git-like properties without pretending tasks are literally Git commits.

### Governance Model

Workflow governance now has a first executable layer:

- review tasks can target specific branch tasks
- merge tasks can protect specific branches
- protected merge waits for enough completed approvals per protected branch
- workflow summaries expose review and merge-gate state for planners and operators
- approval policy can distinguish human and AI reviewers
- review tasks can inherit Git context from the target task they inspect

## Delivery and Failure States

### Task states

- `queued`
- `leased`
- `completed`
- `failed`
- `dead-letter`

### Delivery states

- `local`
- `remote-pending`
- `remote-accepted`
- `fallback-local`
- `dead-letter`

### Outbox states

- `pending`
- `retrying`
- `delivered`
- `dead-letter`

## Weak-Network Behavior

Weak networking is a first-class design case, not an afterthought.

Current behavior:

- outbound remote delivery retries with exponential backoff
- message delivery requires explicit ACK before being marked delivered
- permanently failing remote dispatch can fall back to local execution if configured
- otherwise failed dispatch moves to task dead-letter
- task retries are delayed with `available_at`, which prevents hot retry loops

This means the system degrades into durable local queues instead of losing intent.

## Security Posture

Current baseline:

- binds to `127.0.0.1` by default
- protects write APIs with bearer token when configured
- supports HMAC-signed capability cards and task envelopes
- supports `ssh-keygen` compatible asymmetric signatures for cards, task envelopes, and delivery receipts
- can require signed inbox delivery from configured peers
- avoids mandatory external runtime dependencies
- treats transport and execution failure as separate accountability domains

Still missing for later milestones:

- public-key request signing
- stronger peer identity verification
- encrypted secret storage
- richer ACL and outbound policy
- attestation and verifiable execution proofs
- broader CI and release automation

## API Groups

### Node info

- `GET /healthz`
- `GET /v1/card`
- `GET /v1/peers`
- `GET /v1/peer-cards`
- `GET /v1/bridges`

### Task operations

- `GET /v1/tasks`
- `GET /v1/tasks/dead-letter`
- `POST /v1/tasks`
- `POST /v1/tasks/dispatch`
- `POST /v1/bridges/import`
- `POST /v1/bridges/export`
- `POST /v1/tasks/claim`
- `POST /v1/tasks/lease/renew`
- `POST /v1/tasks/ack`
- `POST /v1/tasks/requeue`

### Workflow operations

- `GET /v1/workflows?workflow_id=...`
- `GET /v1/workflows/summary?workflow_id=...`
- `POST /v1/workflows/fanout`
- `POST /v1/workflows/merge`
- `POST /v1/workflows/finalize`

### Message delivery

- `GET /v1/outbox`
- `GET /v1/outbox/dead-letter`
- `POST /v1/inbox`
- `POST /v1/outbox/flush`
- `POST /v1/outbox/requeue`

## Deployment Modes

### Local single-node

Best for development, debugging, and early adapter work.

### Local multi-node

Run multiple nodes on loopback or LAN to test routing and workflow behavior.

### Encrypted overlay network

Recommended medium-term direction:

- Headscale control plane
- Tailscale-compatible clients
- DERP fallback
- AgentCoin protocol over overlay addresses

## Current Limitations

- no key rotation, revocation, or trust-chain management yet
- no plugin adapter marketplace yet
- worker execution is still a skeleton
- review policy and branch protection are still MVP-grade rather than production-grade
- no production-grade authN/authZ model yet

## Current Verification

The repository now includes:

- `unittest`-based store tests
- `unittest`-based in-process node integration tests
- GitHub Actions CI for macOS, Linux, and Windows

The current automated coverage focuses on the stable MVP paths rather than exhaustive protocol coverage.

## Near-Term Roadmap

1. Upgrade HMAC signatures to stronger asymmetric identity and key rotation
2. Expand MCP / A2A bridges and add custom runtime adapters
3. Expand workflow governance, rejection handling, and policy controls
4. Harden authN/authZ, secret handling, and outbound ACLs
5. Add PoAW, reputation, and settlement scaffolding

## Document Map

- Architecture: [docs/architecture/mvp.md](../architecture/mvp.md)
- Connectivity: [docs/architecture/e2ee-connectivity.md](../architecture/e2ee-connectivity.md)
- Testing: [docs/testing/strategy.md](../testing/strategy.md)
- License notice: [docs/legal/gpl-notice.md](../legal/gpl-notice.md)
