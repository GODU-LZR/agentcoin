# Multi-Node Docker Compose Demo

## Purpose

This demo packages the current local multi-node runtime into one reproducible Docker Compose topology.

It is intentionally different from the Headscale deployment example:

- the Headscale example shows the recommended encrypted transport for real overlay deployment
- this compose demo uses a local Docker bridge network so contributors can exercise peer sync, remote dispatch, and worker pull loops without extra control-plane setup

## Topology

- `agentcoin-node-a`: planner and router node, exposed on host port `8081`
- `agentcoin-node-b`: worker-facing peer, exposed on host port `8082`
- `agentcoin-node-c`: reviewer-facing peer, exposed on host port `8083`
- `agentcoin-worker-b`: polling worker attached to node B with capability `worker`
- `agentcoin-worker-c`: polling worker attached to node C with capability `reviewer`

The services share one private Docker bridge network and use stable service names plus static container IPs to populate `advertise_url`, `overlay_endpoint`, and peer `url` values.

## Files

- `compose.multi-node.yaml`
- `configs/demo/node-a.json`
- `configs/demo/node-b.json`
- `configs/demo/node-c.json`

Each node stores its SQLite state under a separate host-mounted directory in `var/demo/`.

## Start The Demo

```bash
docker compose -f compose.multi-node.yaml up --build
```

The stack is ready once the three node services report healthy.

## Smoke Test

### 1. Check the three nodes

```bash
curl http://127.0.0.1:8081/healthz
curl http://127.0.0.1:8082/healthz
curl http://127.0.0.1:8083/healthz
```

### 2. Sync peer cards from node A

```bash
curl -X POST http://127.0.0.1:8081/v1/peers/sync -H "Authorization: Bearer demo-token-a"
curl http://127.0.0.1:8081/v1/peer-cards -H "Authorization: Bearer demo-token-a"
```

Node A should cache capability cards for peers B and C.

### 3. Dispatch a task to the worker peer

```bash
curl -X POST http://127.0.0.1:8081/v1/tasks/dispatch \
  -H "Authorization: Bearer demo-token-a" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "compose-demo-worker-task-1",
    "kind": "code",
    "required_capabilities": ["worker"],
    "payload": {"input": "demo worker task"}
  }'
```

Inspect node B afterwards:

```bash
curl http://127.0.0.1:8082/v1/tasks -H "Authorization: Bearer demo-token-b"
curl http://127.0.0.1:8082/v1/audits -H "Authorization: Bearer demo-token-b"
```

The worker loop on node B should claim and acknowledge the task automatically.

### 4. Dispatch a task to the reviewer peer

```bash
curl -X POST http://127.0.0.1:8081/v1/tasks/dispatch \
  -H "Authorization: Bearer demo-token-a" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "compose-demo-review-task-1",
    "kind": "review",
    "role": "reviewer",
    "required_capabilities": ["reviewer"],
    "payload": {"input": "demo reviewer task"}
  }'
```

Inspect node C afterwards:

```bash
curl http://127.0.0.1:8083/v1/tasks -H "Authorization: Bearer demo-token-c"
curl http://127.0.0.1:8083/v1/audits -H "Authorization: Bearer demo-token-c"
```

This verifies that node A can route by peer capabilities across the compose network and that the remote worker loop can complete the task.

## Notes

- this demo uses local Docker networking, not Headscale or DERP
- peer routing still goes through the normal AgentCoin `peers` configuration and outbox / inbox path
- the worker processes run the generic execution adapter unless a task payload opts into a more specific runtime or bridge adapter
- if you need a clean restart, remove `var/demo/` before bringing the stack up again

## Stop The Demo

```bash
docker compose -f compose.multi-node.yaml down
```