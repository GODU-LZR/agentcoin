# Dispatch Scoring

This document defines how AgentCoin currently ranks local and remote execution targets during task dispatch.

## Goal

Dispatch should not only answer "who can do this task?" It should also answer:

- who is healthy enough to receive it now
- who matches the runtime and bridge constraints
- who is already overloaded
- who should be temporarily avoided

## Candidate Inputs

The current task-aware dispatch evaluation uses:

- required capabilities
- semantic capability expansion
- runtime requirement from `payload._runtime.runtime`
- bridge requirement from `payload._bridge.protocol`
- peer reputation
- peer health cache
- per-peer outbox backlog
- local preference bias

## Health Cache

Each configured peer now accumulates a local health snapshot:

- `sync_successes`
- `sync_failures`
- `delivery_successes`
- `delivery_failures`
- `success_rate`
- `consecutive_failures`
- `cooldown_until`
- `blacklisted_until`
- `last_error`

The node updates this cache automatically on:

- `peer card sync`
- outbound message delivery

## Blocking Rules

A peer is not dispatchable when either of these flags is active:

- cooldown
- blacklist

`POST /v1/tasks/dispatch` ignores blocked peers.

`POST /v1/tasks/dispatch/evaluate` includes blocked peers so operators can still inspect why they lost.

## Score Components

The current score is additive:

- capability exact-match bonus
- capability semantic-match bonus
- runtime priority bonus
- bridge priority bonus
- reputation contribution
- recent success-rate contribution
- weak-network penalty
- relay backlog penalty
- cooldown penalty
- blacklist penalty

The last four items are negative terms.

## Weak-Network Penalty

Weak-network penalty grows from:

- falling transport success rate
- repeated consecutive failures

This keeps unstable peers from dominating dispatch even if their capability card is otherwise a perfect match.

## Relay Backlog Penalty

Relay backlog is computed from pending local outbox entries for the peer target:

- `pending`
- `retrying`
- `dead_letter`

Peers with a heavier unsent queue are penalized so the node prefers less congested routes.

## Operator Endpoints

The current node exposes:

- `GET /v1/peer-health`
- `POST /v1/peer-health/cooldown`
- `POST /v1/peer-health/blacklist`
- `POST /v1/peer-health/clear`

These endpoints only affect local dispatch decisions. They are not yet part of a global consensus layer.
