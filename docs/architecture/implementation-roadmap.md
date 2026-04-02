# Implementation Roadmap

This file preserves the long-running execution checklist for the repository so progress does not depend on chat history.

Status legend:

- `[x]` completed
- `[~]` in progress
- `[ ]` not started

## Phase 1

- `[x]` settlement relay persistence
- `[x]` relay failure classification
- `[x]` `GET /v1/onchain/settlement-relays/latest?task_id=...`
- `[x]` `POST /v1/onchain/settlement-relays/replay`
- `[x]` replay-inspect includes latest settlement relay
- `[x]` relay records include `final_status`
- `[x]` relay records include `last_successful_index`
- `[x]` relay records include `retry_count`

## Phase 2

- `[x]` challenge bond local skeleton
- `[x]` disputes include `bond_amount_wei`
- `[x]` disputes include `bond_status`
- `[x]` challenger bond required config
- `[x]` upheld disputes produce positive bond outcome
- `[x]` dismissed disputes produce negative bond outcome
- `[x]` bond outcomes are written into `score_events`
- `[x]` bond outcomes are written into reputation metadata

## Phase 3

- `[x]` dispute committee local skeleton
- `[x]` committee member role in capability schema
- `[x]` dispute `committee_votes`
- `[x]` dispute `quorum`
- `[x]` dispute `deadline`
- `[x]` `approve / reject / abstain`
- `[x]` committee result -> `upheld / dismissed / escalated`
- `[x]` replay-inspect committee timeline

## Phase 4

- `[x]` finer `PoAW` event taxonomy
- `[x]` `deterministic-pass`
- `[x]` `deterministic-fail`
- `[x]` `subjective-approve`
- `[x]` `subjective-reject`
- `[x]` `challenge-open`
- `[x]` `challenge-upheld`
- `[x]` `challenge-dismissed`
- `[x]` score policy version
- `[x]` configurable weights

## Phase 5

- `[x]` `PoAW settlement policy` config document
- `[x]` separate local score
- `[x]` separate review score
- `[x]` separate network trust score
- `[x]` separate slash threshold
- `[x]` separate challenge threshold
- `[x]` separate complete threshold
- `[x]` settlement preview bound to policy version

## Phase 6

- `[x]` bridge-aware dispatch scoring doc
- `[x]` bridge priority
- `[x]` runtime priority
- `[x]` recent success rate
- `[x]` weak-network penalty
- `[x]` relay backlog penalty
- `[x]` peer health cache
- `[x]` dispatch blacklist / cooldown

## Phase 7

- `[x]` execution receipt schema version
- `[x]` deterministic receipt schema
- `[x]` subjective review receipt schema
- `[x]` challenge evidence schema
- `[x]` settlement relay receipt schema
- `[x]` all receipts exposed through `schema/examples`

## Phase 8

- `[x]` Git-native proof bundle
- `[x]` task `commit sha`
- `[x]` task `diff hash`
- `[x]` review task `base/head`
- `[x]` merge task `mergeability snapshot`
- `[x]` dispute task `diff evidence`
- `[x]` replay-inspect Git proof bundle

## Phase 9

- `[x]` structured output for OpenClaw / OpenAI runtime
- `[x]` LangGraph HTTP adapter
- `[x]` container-job adapter skeleton
- `[x]` MCP tool schema normalization
- `[x]` A2A message schema normalization
- `[x]` runtime capability advertisement

## Phase 10

- `[x]` relay queue persistence
- `[x]` background settlement relay worker
- `[x]` relay queue pause / resume
- `[ ]` relay queue max in-flight
- `[x]` relay queue dead-letter
- `[x]` operator relay requeue

## Phase 11

- `[x]` on-chain event reconciliation skeleton
- `[x]` local relay vs chain tx comparison
- `[x]` tx receipt fetch
- `[x]` confirmed / reverted / unknown
- `[x]` replay-inspect reconciliation state
- `[x]` relay history `confirmed_at`

## Phase 12

- `[ ]` CI coverage for committee
- `[ ]` CI coverage for settlement replay
- `[ ]` CI coverage for relay reconciliation
- `[ ]` CI coverage for dispatch regression
- `[ ]` CI coverage for weak-network long-run tests

## Phase 13

- `[~]` project docs refresh as features land
- `[~]` testing docs refresh as features land
- `[ ]` architecture docs for committee / bond / replay
- `[~]` README multilingual sync
- `[ ]` alignment-gap refresh

## Phase 14

- `[ ]` challenge bond / committee contract alignment
- `[ ]` relay reconciliation -> auto finalize
- `[ ]` `PoAW -> settlement ledger -> on-chain commit`
- `[ ]` Headscale / overlay deployment examples
- `[ ]` multi-node demo compose
