# AgentCoin Testing Documentation

## Purpose

This document defines how the current AgentCoin reference implementation should be verified, what has already been validated manually, and what still needs automation.

## Test Scope

The current test scope covers:

- node startup and health endpoints
- local SSH/Ed25519 identity bootstrap and derived DID exposure
- local manifest endpoint and CORS preflight handling
- one-time identity auth challenge plus signed request verification
- loopback-only signed client identity access for local task creation, dispatch evaluation, runtime binding, and workflow execution
- HTTP 402 payment challenge, signed local payment receipt issue, and metered workflow execution replay
- payment receipt status introspection, single-use consumption, and replay rejection
- local task persistence
- peer-card synchronization
- durable outbox and inbox delivery
- explicit message ACK validation
- signed peer-card sync and inbox signature verification
- SSH identity signed delivery receipt verification
- staged SSH identity rotation via additional trusted peer public keys
- explicit SSH identity key revocation via peer-side revoked-key lists
- peer sync trust-drift reporting for pending trust and pending revocation updates
- operator-applied peer identity trust updates with governance-action audit receipts and optional config persistence
- trust-update preview and config diff generation without runtime mutation or governance audit writes
- trust reconciliation export with suggested actions and previewed runtime or config diffs
- trust drift severity ranking and export ordering so operators can prioritize urgent peer identity mismatches
- outbound proxy bypass and explicit proxy selection rules
- bridge registry plus MCP / A2A import-export flow
- MCP tool-call and tool-result schema normalization
- A2A message-envelope and message-result schema normalization
- bridge-aware worker execution normalization
- runtime adapter execution for HTTP JSON and CLI JSON agents
- runtime adapter execution for LangGraph-style HTTP runtimes
- runtime adapter execution for container-job skeletons
- runtime adapter execution for Ollama chat and OpenAI-compatible gateways
- settlement relay queue persistence and replay-inspect visibility
- background settlement relay queue execution, delayed scheduling, and retry/dead-letter transitions
- settlement relay queue max in-flight gating when another relay item is already running
- operator pause / resume and dead-letter requeue for settlement relay queue items
- dispute API and replay-inspect contract alignment projection for current `BountyEscrow` versus future `ChallengeManager` paths
- signed settlement ledger generation from task PoAW summary, reputation, violations, disputes, and current on-chain receipt state
- settlement RPC plan, raw bundle, and relay receipts now carry settlement ledger references for replay and commit inspection
- settlement relay reconciliation via transaction receipt fetch, replay-inspect state exposure, and workflow auto-finalize on confirmed final settlement
- OpenAI-compatible structured output forwarding and parsed JSON normalization
- semantic card and task shape exposure
- receipt schema examples and subjective review / challenge evidence receipts
- peer health cache, cooldown / blacklist controls, and dispatch backlog penalties
- adapter policy rejection and sandboxed local-command execution
- execution audit trail and replay inspector endpoints
- policy violation tracking, local reputation scoring, and quarantine blocking
- operator-driven quarantine and release flows
- signed read-only preview plus replay, settlement, governance, and operational inspection, workflow-admin, bridge-admin, Tier 3, and Tier 4 operator request verification, nonce replay rejection, denial auth-receipt persistence, and workflow / bridge governance receipt persistence
- lease-based task claiming
- workflow fanout and merge behavior
- review gate and protected merge behavior
- hybrid human and AI approval policy
- Git repository status, diff, branch, and task-context attachment
- Git proof bundle propagation for task, review, merge, dispute, and replay inspection
- weak-network retry, dead-letter, and local fallback
- on-chain JSON-RPC payload generation and signature verification
- live JSON-RPC planning and raw transaction relay against a local mock RPC

## What Exists Today

The repository now contains an initial automated test suite using Python `unittest`.

Current automated checks include:

- store-level lifecycle tests
- in-process node integration tests
- `python -m py_compile` syntax checks
- GitHub Actions CI on macOS, Linux, and Windows

Representative scenarios already exercised by the CI `unittest discover -s tests -v` run include:

- committee vote resolution and escalation
- settlement ledger endpoint, replay-inspect exposure, and ledger reference propagation across plan / bundle / relay
- settlement relay replay from persisted failure history
- settlement relay reconciliation via transaction receipt fetch
- dispatch regression around blacklist / healthy-peer preference
- weak-network long-run recovery where the background sync loop sees repeated peer failures, then later syncs cards and delivers queued outbox once the peer returns

Phase 12 CI coverage is now closed by representative tests for committee, settlement replay, relay reconciliation, dispatch regression, and weak-network long-run recovery.

Manual validation is still used for exploratory and design-phase scenarios that are not yet encoded as stable tests.

## Minimum Verification Matrix

### Platforms

- Windows PowerShell
- WSL
- Linux
- macOS

### Runtime Modes

- direct Python process
- Docker Compose
- multi-node Docker Compose demo
- multi-node local loopback
- overlay-network style peer addressing

### Failure Modes

- peer unavailable
- proxy enabled with loopback or overlay no-proxy bypass
- invalid message ACK
- task retry exhaustion
- outbox retry exhaustion
- local fallback activation
- workflow finalize before all branches complete

## Verified Behaviors

The following behaviors are now covered either by automated tests or previously repeated manual verification:

- peer card sync and peer-id based delivery
- signed card verification and signed inbox acceptance / rejection
- signed operator request enforcement for read-only preview, workflow-admin, bridge-admin, trust-admin, and settlement-admin endpoints, including denial receipts, auth audit persistence, nonce replay rejection, and workflow / bridge governance receipt persistence
- staged SSH key rotation accepts pre-trusted replacement keys, rejects untrusted replacements, rejects explicitly revoked keys, surfaces sync-time trust drift for operator review, including principal mismatch and stale trusted-key cleanup, and allows operator trust reconciliation export, trust preview, principal adoption, governance-audited apply, stale-key removal, and optional config persistence
- lease queue prevents duplicate claim by multiple workers
- inbox dedupe and explicit delivery ACK
- planner dispatch to matching peer capability
- worker pull loop completion path
- workflow fanout with dependency blocking
- review-gate approval before protected merge claim
- merge task blocking until branch completion
- workflow finalization persistence
- remote dispatch fallback to local execution after outbox dead-letter
- remote dispatch dead-letter when no valid local fallback exists
- background sync loop tolerates a temporarily offline peer and eventually delivers queued remote work after the peer returns
- delayed retry and task dead-letter after retry exhaustion
- queued settlement relay jobs run in the background and persist completed relay ids
- settlement relay queue max-in-flight now blocks additional claims while another relay item is already running
- settlement relay queue respects initial delay and retries failed jobs before dead-lettering them
- operators can pause queued settlement relay jobs, resume them later, and requeue dead-lettered jobs with updated relay parameters
- settlement ledger receipts are signed, exposed through the node API, reflected in replay-inspect, and attached to settlement plans, raw bundles, and relay receipts
- persisted settlement relay history can now reconcile chain receipts into `confirmed`, `reverted`, or `unknown`
- dispute responses and replay-inspect now expose contract alignment for dispute-driven `challengeJob` / `slashJob` settlement, challenger bond custody gaps, and committee escalation handoff
- confirmed final settlement relays can now auto-finalize an associated workflow state, while `challengeJob` relays remain non-final and do not auto-finalize
- replay-inspect now exposes the latest settlement reconciliation status and receipt count for a task
- signed `read-only` operator auth now also covers Git observability endpoints such as `GET /v1/git/status` and `GET /v1/git/diff`, including inherited scope acceptance and denial audit persistence
- signed `read-only` operator auth now also covers dispatch and PoAW observability endpoints such as `GET /v1/tasks/dispatch/preview`, `GET /v1/poaw/events`, and `GET /v1/poaw/summary`
- loopback-only scoped bearer tokens now have targeted integration coverage for `read-only` observability and `workflow-admin` local automation, including scope-denied audit persistence
- Tier 1 `local-admin` endpoints now have targeted integration coverage for loopback shared-bearer migration and loopback scoped-bearer access
- metered workflow execution now returns `402 Payment Required` plus a challenge, and accepts a signed local payment receipt after operator-side receipt issue
- metered workflow receipts now transition to `consumed`, can be inspected by receipt id, and reject second-use replay
- worker loop tolerance of temporary node connectivity failure
- repeated policy rejection lowers reputation and eventually quarantines a worker id

## Recommended Automated Test Layers

### Unit tests

Target:

- `TaskEnvelope.from_dict`
- config loading defaults
- store transitions for task lifecycle
- store transitions for outbox lifecycle
- workflow summary and finalization

### Integration tests

Target:

- spin up one or more nodes in-process
- submit tasks across nodes
- validate persistence and endpoint responses
- simulate unreachable peers and fallback

### CLI smoke tests

Target:

- `agentcoin-node`
- `agentcoin-worker`

### Packaging checks

Target:

- editable install
- package metadata
- Docker build smoke test

## Suggested Test Cases

### Task queue

1. create task
2. claim task with matching worker capability
3. verify lease token exists
4. ACK success
5. verify task becomes `completed`

### Retry and dead-letter

1. create task with `max_attempts=2`
2. claim and ACK with `requeue=true`
3. ensure immediate reclaim is blocked
4. wait until `available_at`
5. claim again and fail again
6. verify task enters `dead-letter`

### Outbox delivery

1. create remotely delivered task
2. flush outbox to a reachable peer
3. verify delivery ACK
4. verify outbox item becomes `delivered`
5. verify receiver inbox dedupe on replay

### Weak-network fallback

1. create remotely delivered task to unreachable peer
2. set `outbox_max_attempts=1`
3. flush outbox
4. verify outbox item enters dead-letter
5. if `local_dispatch_fallback=true`, verify task becomes `fallback-local`
6. verify local worker can claim it

### Workflow merge

1. create root task
2. fan out two branch tasks
3. create merge task with both branch ids
4. verify merge task cannot be claimed yet
5. complete both branch tasks
6. verify merge task becomes claimable
7. finalize workflow and verify persisted summary

### Governance quarantine

1. submit multiple policy-rejected bridge tasks for the same worker id
2. verify each rejection persists a policy violation
3. verify reputation decreases from `100`
4. verify repeated violations create an active quarantine
5. verify the quarantined worker cannot claim a fresh task

### Operator override

1. create a queued worker task
2. apply manual quarantine through the API
3. verify the worker cannot claim the task
4. release the quarantine through the API
5. verify the worker can claim again
6. verify both actions are visible in governance history
7. if signing is enabled, verify structured governance receipts pass signature verification and include target plus reason-code fields

## Manual Test Commands

### Syntax check

```bash
python -m py_compile agentcoin/models.py agentcoin/config.py agentcoin/net.py agentcoin/store.py agentcoin/node.py agentcoin/onchain.py agentcoin/worker.py
```

### Run node

```bash
agentcoin-node --config configs/node.example.json
```

### Run worker

```bash
agentcoin-worker --node-url http://127.0.0.1:8080 --token change-me --worker-id worker-1 --capability worker
```

### Docker Compose

```bash
docker compose up --build
docker compose -f compose.multi-node.yaml up --build
```

### Multi-node demo compose

The repository now also includes a reproducible local multi-node compose topology in `compose.multi-node.yaml`.

Minimum manual verification for that stack:

1. start the stack with `docker compose -f compose.multi-node.yaml up --build`
2. wait for `agentcoin-node-a`, `agentcoin-node-b`, and `agentcoin-node-c` health checks to pass
3. `POST /v1/peers/sync` against node A and verify peer cards are cached
4. dispatch one `worker` task from node A and verify node B plus `agentcoin-worker-b` consume it
5. dispatch one `reviewer` task from node A and verify node C plus `agentcoin-worker-c` consume it
6. stop the stack with `docker compose -f compose.multi-node.yaml down`

This scenario is currently a manual smoke path rather than an automated CI test because it depends on a local Docker engine being available.

## Exit Criteria For MVP

The MVP should not be considered stable until:

- repeatable automated integration tests exist
- CI runs syntax and integration checks on every push
- task and outbox dead-letter behavior is covered
- workflow merge and finalize are covered
- Windows, Linux, and macOS paths are exercised

## Next Testing Milestones

1. Expand edge-case coverage for lease renewal and replay APIs
2. Add Docker smoke tests
3. Add GitHub Actions artifact capture for failing integration runs
4. Add cross-platform verification notes
5. Add performance and weak-network stress tests
6. Add operator override and quarantine release coverage
7. Add signed governance receipt coverage for denial and workflow-override paths
8. Add automated coverage for the multi-node compose topology once Docker-based CI jobs are introduced
