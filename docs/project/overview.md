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
- outbound proxy and VPN-aware transport rules for peer sync, outbox delivery, worker calls, and future chain RPC
- Git-native repository inspection and task context attachment
- local governance primitives for policy violations, reputation, and quarantine
- an on-chain scaffold for DID, staking, and bounty escrow on BNB Chain
- a node-side on-chain integration skeleton for task binding, signed submission receipts, and JSON-RPC payload building
- live JSON-RPC planning and raw transaction relay for external signers and wallets
- a first runtime-adapter layer for HTTP and CLI agent execution
- a lightweight semantic layer for cards and task envelopes
- a local PoAW score-event ledger for useful-work accounting

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
- `docs/architecture/committee-bond-replay.md`: local governance, bond, replay, and reconciliation control-plane architecture
- `docs/architecture/onchain-roadmap.md`: BNB Chain trust and settlement rollout plan
- `docs/project/`: project-level documentation
- `docs/project/blueprint-continuous-improvement-checklist.md`: long-horizon blueprint convergence checklist
- `docs/project/multi-node-demo.md`: local Docker Compose topology for planner, peers, and worker loops
- `docs/testing/`: testing strategy and verification notes
- `docs/whitepaper/`: multilingual whitepapers
- `contracts/`: Solidity scaffold for the BNB Chain trust and settlement layer
- `compose.yaml`: local Docker Compose entrypoint
- `compose.multi-node.yaml`: local multi-node demo compose for peer routing and worker loops

## Runtime Components

### `agentcoin.node`

The node is the main runtime process. It exposes HTTP endpoints for:

- agent capability cards
- local task ingestion
- peer routing
- protocol bridge import and export
- execution audit and replay inspection
- reputation, policy-violation, and quarantine inspection
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
- execution audits
- actor reputation state
- policy violations
- quarantine records
- governance action history
- score-event ledger entries

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
- outbound network policy, explicit proxies, and no-proxy rules
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

### Runtime Adapter Model

Runtime adapters decide how a worker invokes the actual agent implementation.

Current runtime adapter capabilities:

- `GET /v1/runtimes` exposes built-in runtime adapter descriptors
- `POST /v1/runtimes/bind` can attach runtime metadata to an existing task
- `payload._runtime` can route execution into:
  - `http-json`
  - `langgraph-http`
  - `container-job`
  - `openai-chat`
  - `ollama-chat`
  - `cli-json`
- `AgentCard.runtime_capabilities` now exposes structured runtime features such as `supports_structured_output` and `supports_json_schema`
- `langgraph-http` normalizes graph-style execution into `thread_id`, `run_id`, `state`, and assistant output while preserving the raw response
- `container-job` normalizes a local container-engine job into `stdout_json`, `output_json`, and execution metadata while keeping the current implementation as a skeleton
- `openai-chat` can translate `payload._runtime.structured_output` into an OpenAI-compatible `response_format` request and normalize parsed JSON output
- runtime policy can restrict allowed runtime kinds and allowed HTTP hosts

This lets AgentCoin adapt different agent implementations without pretending every agent speaks the same native protocol.

### Semantic Layer

The repository now also has a lightweight semantic layer:

- `AgentCard` and `TaskEnvelope` expose a JSON-LD style `semantics` object
- the node serves a shared context document, capability schema, and example payloads
- receipt and evidence examples are now exposed through `GET /v1/schema/examples`
- dispatch scoring now also considers peer health, cooldown / blacklist state, and outbox backlog
- this is still a minimal ontology step, not a full RDF / JSON-LD reasoning layer

This keeps the current implementation aligned with the blueprint without introducing heavy semantic-web dependencies too early.

### Git Adapter Model

AgentCoin does not replace Git. It now adapts to Git repositories directly.

Current Git-native capabilities:

- inspect repository status
- inspect diffs
- create branches
- attach repository context to tasks
- attach `commit_sha`, `diff_hash`, and ref / SHA proof fields to Git-aware tasks
- propagate review `base/head` proof metadata and merge `mergeability` snapshots
- expose Git proof bundles through replay inspection

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

Execution governance now also has a first local enforcement layer:

- policy-rejected executions are recorded as violations
- workers accumulate a local reputation score
- repeated violations automatically quarantine the worker id for future task claims
- operators can inspect reputation, violation history, and active quarantines over HTTP
- operators can also set and release manual quarantines with a durable governance action log
- if node signing is enabled, those governance actions also carry a signed governance receipt

### Local PoAW Ledger

The repository now also has a first local PoAW-style accounting layer:

- successful task completion writes a positive score event
- policy violations write a negative score event
- score events can be listed by actor or task
- score summaries can be aggregated without requiring any chain connection

This is intentionally narrower than the whitepaper target. It is a local useful-work ledger, not a final settlement engine.

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
- trust, quarantine, and dispute governance actions now emit structured signed governance receipts with target, reason-code, auth-context, and mutation metadata
- avoids mandatory external runtime dependencies
- treats transport and execution failure as separate accountability domains

Still missing for later milestones:

- public-key request signing
- per-endpoint auth policy enforcement beyond the current documented rollout plan
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
- `GET /v1/audits`
- `GET /v1/bridges`

### Task operations

- `GET /v1/tasks`
- `GET /v1/tasks/dead-letter`
- `GET /v1/tasks/replay-inspect?task_id=...`
- `GET /v1/onchain/settlement-relay-queue`
- `POST /v1/onchain/settlement-relay-queue`
- `POST /v1/tasks`
- `POST /v1/tasks/dispatch`
- `POST /v1/bridges/import`
- `POST /v1/bridges/export`
- MCP bridge import/export now normalizes tool traffic into explicit `tool_call` and `tool_result` shapes
- A2A bridge import/export now normalizes message traffic into explicit `message_envelope` and `message_result` shapes
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

The repository now also includes a reproducible Docker Compose version of that topology with one planner node, two peer nodes, and dedicated worker loops for remote dispatch verification.

### Encrypted overlay network

Recommended medium-term direction:

- Headscale control plane
- Tailscale-compatible clients
- DERP fallback
- AgentCoin protocol over overlay addresses

The connectivity architecture doc now also includes a concrete Phase 14 deployment example: a minimal Headscale bootstrap, ACL skeleton, two-node overlay config shape, and smoke-test flow for AgentCoin over tailnet addresses.

## Current Limitations

- SSH identity rotation now supports staged multi-key trust plus explicit revoked-key lists, peer sync surfaces trust drift with severity ranking for operator review, operators can export trust reconciliation with suggested actions and previewed runtime or config diffs, operators can apply trust updates with structured governance receipts and optionally persist them back to the loaded JSON config, but stronger trust bootstrap and richer trust-chain management are not implemented yet
- no plugin adapter marketplace yet
- worker execution is still a skeleton
- review policy and branch protection are still MVP-grade rather than production-grade
- operator auth is still not production-complete, but a Tier 1 read-only slice now covers preview POST endpoints plus selected replay, dispute, settlement, governance, and operational observability GET endpoints when `operator_identities` are configured, while Tier 2 workflow-admin and bridge-admin plus Tier 3 and Tier 4 write paths support signed operator requests, nonce replay rejection, denial policy receipts, durable auth audit records, and workflow / bridge governance receipts; broader diagnostic and operator-only coverage, scoped bearer tokens, and deployment hardening remain unfinished
- operator auth now also supports loopback-only scoped bearer tokens for local automation on explicitly scoped endpoints, while signed requests remain the intended steady-state control for higher-risk operator flows
- Tier 1 local operational endpoints now also expose explicit `local-admin` scope policy while preserving loopback shared-bearer migration compatibility

## Current Verification

The repository now includes:

- `unittest`-based store tests
- `unittest`-based in-process node integration tests
- GitHub Actions CI for macOS, Linux, and Windows

The current automated coverage focuses on the stable MVP paths rather than exhaustive protocol coverage.

## Near-Term Roadmap

1. Add stronger trust bootstrap and richer trust-chain management on top of the current staged SSH key rotation, explicit revocation, sync-time trust-drift visibility, and operator apply / config reconciliation flow
2. Expand MCP / A2A bridge coverage and add more production-grade runtime adapters
3. Extend the new signed operator auth path into broader diagnostic and operator-only coverage, scoped bearer tokens, stronger secret handling, and outbound ACL policy
4. Move local challenge, PoAW, reputation, and settlement control loops toward chain-backed authority
5. Add automated Docker smoke coverage for the local multi-node demo and related deployment paths

## Document Map

- Architecture: [docs/architecture/mvp.md](../architecture/mvp.md)
- Operator auth hardening plan: [docs/project/operator-auth-hardening-plan.md](operator-auth-hardening-plan.md)
- Trust operator runbook: [docs/project/trust-operator-runbook.md](trust-operator-runbook.md)
- Connectivity: [docs/architecture/e2ee-connectivity.md](../architecture/e2ee-connectivity.md)
- Testing: [docs/testing/strategy.md](../testing/strategy.md)
- License notice: [docs/legal/gpl-notice.md](../legal/gpl-notice.md)
