# AgentCoin Testing Documentation

## Purpose

This document defines how the current AgentCoin reference implementation should be verified, what has already been validated manually, and what still needs automation.

## Test Scope

The current test scope covers:

- node startup and health endpoints
- local task persistence
- peer-card synchronization
- durable outbox and inbox delivery
- explicit message ACK validation
- signed peer-card sync and inbox signature verification
- SSH identity signed delivery receipt verification
- outbound proxy bypass and explicit proxy selection rules
- bridge registry plus MCP / A2A import-export flow
- bridge-aware worker execution normalization
- runtime adapter execution for HTTP JSON and CLI JSON agents
- adapter policy rejection and sandboxed local-command execution
- execution audit trail and replay inspector endpoints
- policy violation tracking, local reputation scoring, and quarantine blocking
- operator-driven quarantine and release flows
- lease-based task claiming
- workflow fanout and merge behavior
- review gate and protected merge behavior
- hybrid human and AI approval policy
- Git repository status, diff, branch, and task-context attachment
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
- delayed retry and task dead-letter after retry exhaustion
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
7. if signing is enabled, verify governance receipts pass signature verification

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
```

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
7. Add signed governance receipt coverage
