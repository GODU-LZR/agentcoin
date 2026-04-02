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

The MVP now also supports pragmatic signed identity checks:

- capability cards can be returned with a node-level HMAC signature
- remote task envelopes can be HMAC-signed before entering the outbox
- inbox delivery can require a valid sender signature
- peer-card sync can verify a peer signature before caching the card
- nodes can also use `ssh-keygen` compatible Ed25519 identities for cards, task envelopes, and delivery receipts

### Agent compatibility through envelopes

The node does not assume a specific agent runtime. It accepts generic task envelopes and capability cards so different agent systems can be adapted behind the same interface.

### Minimal semantic layer

The MVP now also adds a lightweight semantic layer:

- `AgentCard` and `TaskEnvelope` carry a JSON-LD style `semantics` object
- the node serves a shared context, capability schema, and example documents
- this is intentionally smaller than a full ontology stack, but keeps the data model aligned with the blueprint

### Offline and weak-network behavior

If a task includes `deliver_to`, the node stores an outbox record and retries delivery later. This allows workflows to continue collecting work locally even when peer nodes are unreachable.

The reference node now also models degraded network conditions explicitly:

- outbox delivery moves through `pending`, `retrying`, and `dead-letter`
- remote dispatch can downgrade into `fallback-local` when local execution is allowed and feasible
- delayed task retries use `available_at` to avoid hot-loop reclaim storms
- retry exhaustion moves work into task dead-letter instead of retrying forever

The outbound transport path is now centralized as well:

- peer sync, outbox delivery, worker API calls, and future chain RPC can share explicit `http_proxy` / `https_proxy`
- `no_proxy_hosts` supports hostnames, suffixes, and CIDR ranges for overlay and local bypass
- loopback traffic is always kept direct so local development does not depend on proxy hairpin behavior

## Implemented Endpoints

- `GET /healthz`
- `GET /v1/card`
- `GET /v1/schema/context`
- `GET /v1/schema/capabilities`
- `GET /v1/schema/examples`
- `GET /v1/poaw/events`
- `GET /v1/poaw/summary`
- `GET /v1/disputes`
- `GET /v1/onchain/settlement-preview?task_id=...`
- `GET /v1/tasks`
- `GET /v1/tasks/dead-letter`
- `GET /v1/tasks/replay-inspect?task_id=...`
- `GET /v1/git/status`
- `GET /v1/git/diff`
- `GET /v1/workflows?workflow_id=...`
- `GET /v1/workflows/summary?workflow_id=...`
- `GET /v1/peers`
- `GET /v1/peer-cards`
- `GET /v1/audits`
- `GET /v1/onchain/status`
- `GET /v1/bridges`
- `GET /v1/runtimes`
- `GET /v1/outbox`
- `GET /v1/outbox/dead-letter`
- `POST /v1/tasks`
- `POST /v1/tasks/dispatch`
- `POST /v1/tasks/dispatch/evaluate`
- `POST /v1/disputes`
- `POST /v1/disputes/resolve`
- `POST /v1/bridges/import`
- `POST /v1/bridges/export`
- MCP bridge traffic is normalized into `tool_call` and `tool_result` structures
- A2A bridge traffic is normalized into `message_envelope` and `message_result` structures
- `POST /v1/runtimes/bind`
- `POST /v1/integrations/openclaw/bind`
- `POST /v1/workflows/fanout`
- `POST /v1/workflows/review-gate`
- `POST /v1/workflows/merge`
- `POST /v1/workflows/finalize`
- `POST /v1/tasks/claim`
- `POST /v1/tasks/lease/renew`
- `POST /v1/tasks/ack`
- `POST /v1/tasks/requeue`
- `POST /v1/git/branch`
- `POST /v1/git/task-context`
- `POST /v1/inbox`
- `POST /v1/outbox/flush`
- `POST /v1/outbox/requeue`
- `POST /v1/onchain/rpc-payload`
- `POST /v1/onchain/rpc-plan`
- `POST /v1/onchain/rpc/send-raw`
- `POST /v1/peers/sync`

The node can now resolve `deliver_to` either as a full URL or as a configured `peer_id`. This is better suited for encrypted overlay networks because application code can target stable peer identities instead of embedding raw addresses everywhere.

It also supports capability-card synchronization from configured peers. This allows the node to cache peer capabilities locally before the scheduler layer is built.

The task queue now includes lease-based locking primitives. Workers can atomically claim work, renew the lease while executing, and explicitly acknowledge completion or failure.

The message queue layer now also requires explicit delivery acknowledgement. A receiver returns an ACK payload and the sender only marks the outbox item as delivered after validating that ACK. This separates `task completion` from `message delivery`.

The queueing layer now also includes bounded retry and dead-letter behavior:

- outbox retries are capped by `outbox_max_attempts`
- task retries are capped by per-task `max_attempts`
- transport failure and execution failure end up in separate dead-letter lanes
- dead-letter work can be replayed explicitly by operators

The planner layer now has a first executable skeleton:

- planners can submit `required_capabilities`
- the node selects a peer from cached capability cards
- task-aware dispatch can also factor runtime and bridge compatibility before selecting a target
- dispatch scoring now also uses peer health, cooldown / blacklist state, recent transport success rate, and outbox backlog
- dispatch falls back to local execution if local capabilities satisfy the task
- workers can run a simple pull loop and complete claimed tasks

The node now also has a Git-native adapter layer:

- repository status and diff inspection
- branch creation
- task attachment to real repository context
- task Git context now includes `commit_sha`, `diff_hash`, and ref / SHA proof fields
- review tasks now carry base/head proof metadata
- merge tasks now carry a mergeability snapshot and proof bundle
- dispute payloads inherit task Git evidence
- replay inspection now exposes a Git proof bundle
- no attempt to replace Git history with internal workflow metadata

The node now also has a first on-chain build layer:

- signed EVM transaction intents for `createJob`, `acceptJob`, `submitWork`, `completeJob`, `rejectJob`, and `slashJob`
- signed JSON-RPC payload skeletons for `eth_sendTransaction`, `eth_estimateGas`, and `eth_call`
- explicit `abi_encoding_required` markers so a future signer/broadcaster can stay decoupled from the coordination runtime
- live RPC planning for nonce, gas price, and gas estimate discovery
- raw transaction relay for externally signed transactions

The node now also has a first protocol-bridge layer:

- bridge registry for enabled MCP / A2A adapters
- MCP-style request import into durable task envelopes
- A2A-style message import into durable task envelopes
- protocol-shaped export of task state and results back to bridge callers

The worker loop now also has a first bridge-aware execution layer:

- detect bridge metadata from `payload._bridge`
- produce normalized MCP-style tool execution result payloads
- produce normalized A2A-style task result payloads
- leave real external runtime invocation for later adapters

The worker loop now also has a first runtime-adapter layer:

- `payload._runtime` can steer execution independently of bridge metadata
- `http-json` forwards a normalized task envelope to an HTTP agent runtime
- `langgraph-http` forwards thread-oriented graph execution requests to a LangGraph-style HTTP runtime
- `container-job` stages a task file and runs a local container-engine style job skeleton
- `cli-json` invokes a local CLI wrapper over JSON stdin/stdout
- runtime policy can restrict allowed runtime kinds and HTTP host targets

The worker loop now also has a first policy and sandbox layer:

- MCP tool allowlists
- A2A intent allowlists
- opt-in subprocess execution for `local-command`
- executable allowlists for subprocess mode
- workspace-root confinement for subprocess cwd

The runtime now also persists execution audit trails:

- each ACK writes an execution audit event
- audit events can be queried by task
- replay inspection can assemble the task, audit history, and bridge export preview in one response

The runtime now also persists a first local PoAW ledger:

- successful ACKs emit positive score events
- policy violations emit negative score events
- score events can be queried or summarized by actor / task
- this is local accounting only, not final settlement

The runtime now also exposes a first receipt schema layer:

- execution receipts now have a shared `schema_version`
- deterministic execution receipts are used for runtime and bridge execution
- review acknowledgements now emit subjective review receipts
- dispute paths now expose structured challenge evidence
- settlement relay responses now use a dedicated relay receipt schema
- schema examples expose these receipt shapes through `GET /v1/schema/examples`

The runtime now also exposes a first settlement-preview layer:

- a completed task can be mapped into a signed `submitWork` + resolution sequence
- the resolution path can resolve to `completeJob`, `rejectJob`, `challengeJob`, or `slashJob`
- the preview uses local PoAW summaries, task-scoped violations, and worker reputation

The runtime now also has a first dispute lane:

- operators or reviewers can open task-scoped disputes with evidence hashes
- open disputes are persisted locally and visible over HTTP
- dispute resolution is persisted as governance history

The runtime now also has a first local governance loop:

- policy-rejected executions are persisted as `policy_violations`
- workers accumulate a local reputation score
- repeated violations create quarantine records
- quarantined worker ids are blocked from future task claims on that node
- operators can manually quarantine or release actors with durable governance action history

## Git-Like Task Model

Tasks now carry workflow lineage fields inspired by Git:

- `workflow_id`: identifies the whole DAG
- `parent_task_id`: identifies the task that spawned the current one
- `branch`: allows alternate solution paths
- `revision`: monotonic revision inside a branch
- `merge_parent_ids`: records merge-style ancestry
- `commit_message`: short human-readable intent for the task revision
- `depends_on`: explicit dependency edges

This makes AgentCoin closer to a distributed task graph with history, not just a transient queue.

## Workflow Convergence

The workflow model now also supports Git-like convergence:

- `fanout` spawns child tasks and auto-completes the parent planning task
- `review-gate` creates reviewer tasks bound to specific branch tasks
- `merge` creates a merge or aggregate task with multiple `merge_parent_ids`
- dependency checks keep merge tasks blocked until every upstream branch is completed
- protected merge checks keep merge tasks blocked until required reviews are approved
- `summary` exposes the workflow state for planners, reviewers, and dashboards
- `finalize` persists a terminal workflow snapshot once no queued or leased tasks remain

This gives the scheduler a simple but useful lifecycle:

1. planner creates a root task
2. planner fans out worker branches
3. workers complete branch tasks
4. reviewer or aggregator claims the merge task
5. workflow finalization records the terminal summary

Protected branches now work as a first governance primitive:

- reviewer tasks declare a review target in `payload._review.target_task_id`
- merge tasks declare protected branches and required approvals in `payload._merge_policy`
- the scheduler only releases the merge task after both dependency completion and review-policy satisfaction

## Failure Handling

The node now distinguishes:

- `retrying`: temporary delivery failure, still within budget
- `fallback-local`: remote route failed permanently, task was reclassified for local execution
- `dead-letter`: retry budget exhausted and work now requires operator attention
- `failed`: terminal execution failure without requeue

## Coordination Direction

The next coordination layer should be built on top of these primitives:

1. `Task queue`: durable queue with lease locking and ACK.
2. `Message queue`: durable inter-node delivery with explicit receipts.
3. `Planner-worker model`: planners emit tasks, workers claim by capability.
4. `Retry and dead-letter`: failed tasks requeue or move to a failure lane.
5. `Checkpoint merge`: long workflows checkpoint state between stages.
6. `Workflow governance`: richer merge policies, review gates, and branch protection.

## Next Milestones

1. Replace the current mixed HMAC / SSH MVP with key rotation, stronger trust bootstrap, and richer receipt semantics.
2. Add task state transitions and worker execution adapters.
3. Add encrypted local secrets and stricter outbound policy controls.
4. Expand the current MCP / A2A bridge skeleton into fuller protocol coverage and custom adapters.
5. Add gossip sync and richer offline replay semantics.
