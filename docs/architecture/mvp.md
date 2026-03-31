# AgentCoin MVP Architecture

## Goals

- Run on macOS, Linux, Windows, and WSL with the same reference behavior.
- Keep the first node lightweight and dependency-minimal.
- Stay compatible with different agent runtimes by exposing a simple HTTP + JSON boundary.
- Preserve basic usability during weak network conditions through local persistence and retryable delivery.
- Keep the default security posture conservative.

## Design Choices

### Python standard library reference node

The first node uses only Python 3.11 standard library modules. This keeps bootstrap friction low and makes the reference implementation portable across operating systems without forcing Docker or a heavy framework.

### Local-first persistence

Tasks, inbound messages, and outbound deliveries are stored in SQLite. This gives the node a durable local queue that survives process restarts and temporary network loss.

### Secure-by-default ingress

All write endpoints require a bearer token when `auth_token` is set. The default bind address is `127.0.0.1`, which keeps the node local until the operator explicitly opens it to a network.

### Agent compatibility through envelopes

The node does not assume a specific agent runtime. It accepts generic task envelopes and capability cards so different agent systems can be adapted behind the same interface.

### Offline and weak-network behavior

If a task includes `deliver_to`, the node stores an outbox record and retries delivery later. This allows workflows to continue collecting work locally even when peer nodes are unreachable.

## Implemented Endpoints

- `GET /healthz`
- `GET /v1/card`
- `GET /v1/tasks`
- `GET /v1/peers`
- `GET /v1/peer-cards`
- `GET /v1/outbox`
- `POST /v1/tasks`
- `POST /v1/tasks/claim`
- `POST /v1/tasks/lease/renew`
- `POST /v1/tasks/ack`
- `POST /v1/inbox`
- `POST /v1/outbox/flush`
- `POST /v1/peers/sync`

The node can now resolve `deliver_to` either as a full URL or as a configured `peer_id`. This is better suited for encrypted overlay networks because application code can target stable peer identities instead of embedding raw addresses everywhere.

It also supports capability-card synchronization from configured peers. This allows the node to cache peer capabilities locally before the scheduler layer is built.

The task queue now includes lease-based locking primitives. Workers can atomically claim work, renew the lease while executing, and explicitly acknowledge completion or failure.

## Coordination Direction

The next coordination layer should be built on top of these primitives:

1. `Task queue`: durable queue with lease locking and ACK.
2. `Message queue`: durable inter-node delivery with explicit receipts.
3. `Planner-worker model`: planners emit tasks, workers claim by capability.
4. `Retry and dead-letter`: failed tasks requeue or move to a failure lane.
5. `Checkpoint merge`: long workflows checkpoint state between stages.

## Next Milestones

1. Add peer registry and signed capability cards.
2. Add task state transitions and worker execution adapters.
3. Add encrypted local secrets and stricter outbound policy controls.
4. Add pluggable protocol bridges for MCP, A2A, and custom agents.
5. Add gossip sync and richer offline replay semantics.
