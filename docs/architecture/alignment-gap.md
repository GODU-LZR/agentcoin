# Blueprint Alignment And Gaps

## Purpose

This document compares the current AgentCoin repository against the original Word/PDF blueprint for the Web 4.0 agent swarm network.

The blueprint's core structure is:

1. interoperability and ontology
2. PoAW consensus and economic settlement
3. decentralized swarm scheduling and task collaboration
4. secure execution and governance

## Where The Current Repository Is Aligned

### 1. Interoperability direction is aligned

The repository already follows the blueprint's protocol-first spirit:

- capability cards
- peer discovery and synchronization
- generic task envelopes
- cross-node delivery primitives
- adapter-friendly HTTP + JSON boundary

This is consistent with the blueprint's emphasis on standardizing communication rather than forcing one runtime framework.

### 2. Swarm scheduling direction is aligned

The repository already implements the MVP skeleton for:

- planner to worker dispatch
- capability-based routing
- lease-based claiming
- task DAG fanout and merge
- review gates and protected merges
- weak-network retry, dead-letter, and replay

This matches the blueprint's view that multi-agent collaboration should be task-tree based rather than centralized and monolithic.

### 3. Checkpoint and persistence direction is aligned

The blueprint explicitly emphasizes checkpointable execution and durable task state. The repository already does this through SQLite-backed:

- tasks
- inbox
- outbox
- delivery receipts
- workflow terminal states

### 4. Secure-by-default MVP direction is aligned

The blueprint calls for gateway-mediated, controlled execution. The repository is still early, but already follows the right MVP posture:

- loopback bind by default
- bearer-token protected write endpoints
- HMAC-signed capability cards and task envelopes
- SSH-key based node identity for cards, task envelopes, and delivery receipts
- worker-side allowlists and restricted subprocess execution skeleton
- execution audit trail and replay inspection
- durable audit-friendly queue state
- transport and execution failure separation

### 5. Git-native collaboration is aligned with the blueprint's task decomposition goals

The blueprint wants code generation, review, and delivery to happen across collaborating agents. The repository now correctly treats Git as the code truth layer and AgentCoin as the orchestration layer above it.

## Where The Current Repository Still Deviates Or Lags

### 1. Ontology and semantic-web layer is only partially implemented

The blueprint strongly emphasizes:

- structured ontology
- JSON-LD / RDF semantics
- machine-readable role and capability meaning

The current repository now has lightweight JSON-LD style `semantics` on cards and task envelopes, plus a shared context endpoint, but it still does not implement:

- a full ontology
- RDF graph reasoning
- semantic negotiation between peers
- formal role and capability vocabularies beyond the current minimal schema

### 2. PoAW and economic settlement are still mostly conceptual

The blueprint expects:

- useful-work valuation
- proof-backed settlement
- stable usage credits
- native reward issuance
- staking and slashing

The repository currently has no real settlement engine, no token logic, no PoAW evaluator, and no staking/slashing contract integration.

### 3. Decentralization is still MVP-grade, not full network-grade

The current runtime is still a practical local-first coordinator model. It now has a local reputation / policy-violation / quarantine skeleton, but it does not yet implement:

- decentralized leader election
- hierarchical swarm topology
- anti-cartel reputation logic
- real distributed consensus

### 4. Security execution layer is still software-first, not TEE-grade

The blueprint explicitly mentions:

- TEE
- remote attestation
- stronger isolation guarantees
- cryptographic receipts

The current implementation now has a pragmatic signed-identity MVP with both HMAC and SSH-key based signatures, but it is still far from the blueprint's stronger target. There is no TEE integration, no attestation, no decentralized trust chain, and no cryptographic proof-of-work receipts yet.

### 5. Protocol compatibility is now skeleton-level, not standards-complete

The blueprint discusses MCP, A2A, ACP, LACP, and ANP directions. The current repository now has a pragmatic MCP / A2A bridge skeleton for import-export flows, but it does not yet provide full standards-complete bridges for those protocols.

## Current Overall Judgment

The repository has **not drifted away from the blueprint's main architecture**.

It has instead taken a pragmatic MVP path:

- start with a lightweight local-first reference runtime
- prove task routing, workflow control, retry, review, and Git integration
- postpone heavy economic, ontology, and hardware-trust layers

This is the correct direction for an MVP, but it means the repository currently realizes only the blueprint's execution and coordination subset, not the full protocol-economic-security stack.

## Highest-Impact Missing Areas

If the goal is to converge back toward the original blueprint, the most important remaining work is:

1. JSON-LD / ontology-backed capability and task semantics
2. stronger signed identity and envelope verification beyond the current HMAC MVP
3. PoAW scoring and settlement pipeline
4. stronger execution isolation and attestation
5. fuller MCP / A2A bridge adapters and additional protocol coverage

## Recommended Next Completion Path

1. finish Git-native review and approval policy
2. upgrade signed envelopes and peer identity from shared-secret HMAC to stronger asymmetric trust
3. add protocol bridge layer for MCP / A2A-style agents
4. add semantic capability schema
5. then implement PoAW and settlement

This keeps the current codebase on a realistic engineering path while remaining faithful to the original blueprint.
