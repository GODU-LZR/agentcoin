# Committee, Bond, And Replay Architecture

## Purpose

This document explains how the current AgentCoin runtime handles three closely related control loops:

- dispute opening and committee resolution
- challenger bond outcomes and PoAW side effects
- settlement relay replay and reconciliation after on-chain delivery failures

These features are implemented today as an off-chain governance and recovery lane inside the Python node. They are not yet the final chain-native dispute or settlement system, but they already define the repository's executable control-plane shape.

## Design Goal

The runtime separates three concerns that the original blueprint grouped together conceptually:

1. challenge intake and review governance
2. economic consequence recording
3. transport recovery and replay after partial settlement failure

The intent is pragmatic:

- keep review and challenge logic durable and inspectable
- keep bond and score consequences explicit even before full contracts exist
- keep settlement relays resumable under weak network or RPC faults

This means the repository now has a usable pre-on-chain governance lane rather than only a future-facing design note.

## Main Components

### Node HTTP layer

The node exposes the operator and workflow entry points for disputes, committee voting, replay inspection, settlement replay, and settlement reconciliation.

Key endpoints:

- `GET /v1/disputes`
- `POST /v1/disputes`
- `POST /v1/disputes/vote`
- `GET /v1/tasks/replay-inspect?task_id=...`
- `POST /v1/onchain/settlement-relays/replay`
- `POST /v1/onchain/settlement-relays/reconcile`

### NodeStore durability

`NodeStore` is the backbone for this lane. It persists:

- disputes and their resolution payloads
- bond amount and bond status
- committee votes, quorum, and deadline
- score events and reputation deltas
- settlement relay history
- settlement relay queue state
- settlement reconciliation snapshots

### On-chain helper layer

The `onchain` module does not finalize disputes or bonds yet, but it already consumes governance outputs during settlement preview and relay planning. In practice this means open or escalated dispute state can block or alter the local settlement readiness view before future contracts take over.

Phase 14 now also projects each dispute into a contract-aligned view exposed by the node API and replay inspector:

- current `BountyEscrow` action implied by dispute state such as `challengeJob`, `slashJob`, or settlement re-entry to `completeJob`
- challenger bond custody remaining local because current `StakingPool` only covers worker stake locks
- committee vote and escalation outcomes pointing at a future `ChallengeManager` handoff instead of pretending that the first contract set already stores committee state

## Dispute And Committee Lane

### Opening a dispute

A dispute is opened against a task with:

- `task_id`
- `challenger_id`
- optional `actor_id`
- severity and evidence hash
- optional challenger bond amount
- optional committee quorum and deadline

When opened, the runtime immediately writes:

- a durable dispute row with status `open`
- a governance action of type `dispute-opened`
- a PoAW score event of type `challenge-open`
- challenge evidence material for replay-inspect when an evidence hash exists

If the bond amount is non-zero, the initial bond status is `locked`. Otherwise it stays `none`.

### Committee voting

Committee voting is explicitly modeled as a separate step rather than overloading direct operator resolution.

Each vote stores:

- `voter_id`
- `decision` in `approve`, `reject`, or `abstain`
- optional note and payload
- timestamp

The dispute keeps a derived tally for:

- `approve`
- `reject`
- `abstain`

Resolution happens automatically once quorum semantics are satisfied:

- quorum of `approve` resolves the dispute as `upheld`
- quorum of `reject` resolves the dispute as `dismissed`
- quorum reached without decisive `approve` or `reject` resolves as `escalated`

This makes committee voting an executable state machine, not just a stored annotation.

### Resolution outputs

Dispute resolution writes a normalized resolution payload and updates both governance and scoring side effects.

Current resolution outcomes are:

- `upheld`
- `dismissed`
- `escalated`

Only `upheld` and `dismissed` currently produce bond and score consequences. `escalated` is intentionally preserved as an unresolved handoff state for future on-chain or higher-order governance.

## Bond And PoAW Lane

### Bond lifecycle today

The runtime currently treats challenger bond handling as an explicit local accounting skeleton.

Bond statuses used today:

- `none`
- `locked`
- `awarded`
- `slashed`

The status transitions are:

- dispute opened with non-zero bond -> `locked`
- dispute upheld -> `awarded`
- dispute dismissed -> `slashed`

No on-chain transfer happens in this step. Instead, the repository records the intended outcome so the later contract path has a clean interface to consume.

### Score and reputation side effects

The bond lane is already wired into the PoAW ledger and reputation metadata.

Examples:

- `challenge-upheld`
- `challenge-dismissed`
- `dispute-bond-awarded`
- `dispute-bond-slashed`

These events update:

- score-event history for replay and audit
- local actor reputation state
- dispute resolution metadata with the bond outcome

This lets the repository express economic and trust consequences before the final staking and settlement contracts are live.

## Settlement Replay Lane

### Why replay exists

Settlement relay steps can fail after partial progress. The repository therefore persists relay history rather than treating chain submission as an all-or-nothing RPC call.

Each relay record tracks:

- total step count
- last successful step
- next replay index
- retry count
- failure category
- optional parent relay id when resumed
- raw relay payload and submitted step snapshots

This means a failed relay can resume from the last durable checkpoint instead of rebuilding the whole settlement from scratch.

### Replay flow

Replay can be requested by:

- `relay_id`
- or latest relay for `task_id`

The replay entry point reconstructs raw transactions from the stored relay record when the caller does not provide a fresh transaction list. It then invokes settlement relay execution with:

- `resume_from_index`
- incremented `retry_count`
- `resumed_from_relay_id`

This produces a new relay record rather than mutating the old one in place. The history therefore forms an append-only recovery chain.

### Replay-inspect view

`GET /v1/tasks/replay-inspect` is the operator-facing inspection surface for this entire lane. It aggregates:

- task state
- execution audits
- PoAW events and summary
- disputes and challenge evidence
- settlement relay history
- settlement relay queue items
- latest settlement relay snapshot
- settlement reconciliation summary
- Git proof bundle
- on-chain preview and receipt state

This endpoint is the current off-chain observability anchor for committee, bond, replay, and reconciliation behavior.

## Reconciliation Lane

Replay and reconciliation are separate on purpose.

- replay answers: how do we resume submission after an interrupted relay?
- reconciliation answers: what does the chain receipt say about the steps already submitted?

The reconciliation flow fetches `eth_getTransactionReceipt` for stored submitted steps and records per-step snapshots with status:

- `confirmed`
- `reverted`
- `unknown`

The relay history also stores:

- `reconciliation_status`
- `reconciliation_checked_at`
- `confirmed_at`
- receipt snapshot list

This gives the runtime an inspection-grade source of truth that now also feeds reconciliation-driven workflow auto-finalize for final settlement actions.

## Current Boundaries

### What is implemented now

- durable disputes
- challenger bond status accounting
- committee voting with quorum and escalation
- dispute contract alignment projection for current escrow paths and future challenge-manager paths
- PoAW event and reputation side effects
- signed settlement ledger receipts that bridge local PoAW, disputes, violations, reputation, and current on-chain receipt state into a stable commit artifact
- settlement relay replay from stored checkpoints
- settlement receipt reconciliation, replay-inspect exposure, and workflow auto-finalize for confirmed final settlement actions

### What is intentionally not implemented yet

- chain-native challenger bond custody
- contract-backed committee resolution
- DAO-style dispute escalation beyond the local `escalated` state

## How This Connects To Phase 14

This architecture intentionally sets up the next contract-facing work rather than trying to skip directly to full decentralization.

The next logical transitions are:

1. map local challenger bond outcomes onto the staking and escrow contracts
2. turn `escalated` committee outcomes into a contract-aware challenge manager path
3. move the signed settlement ledger from commit artifact into direct chain-native settlement authority
4. map local PoAW and governance consequences onto future scorebook / reputation contracts

In other words, the current repository already has the right control-plane primitives. Phase 14 is mostly about moving custody and final authority from local durable state into the chain layer without losing the existing replay and audit guarantees.