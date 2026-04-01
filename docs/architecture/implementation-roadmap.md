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

- `[~]` challenge bond local skeleton
- `[x]` disputes include `bond_amount_wei`
- `[x]` disputes include `bond_status`
- `[x]` challenger bond required config
- `[x]` upheld disputes produce positive bond outcome
- `[x]` dismissed disputes produce negative bond outcome
- `[x]` bond outcomes are written into `score_events`
- `[x]` bond outcomes are written into reputation metadata

## Phase 3

- `[ ]` dispute committee local skeleton
- `[ ]` committee member role in capability schema
- `[ ]` dispute `committee_votes`
- `[ ]` dispute `quorum`
- `[ ]` dispute `deadline`
- `[ ]` `approve / reject / abstain`
- `[ ]` committee result -> `upheld / dismissed / escalated`
- `[ ]` replay-inspect committee timeline

## Phase 4

- `[ ]` finer `PoAW` event taxonomy
- `[ ]` `deterministic-pass`
- `[ ]` `deterministic-fail`
- `[ ]` `subjective-approve`
- `[ ]` `subjective-reject`
- `[ ]` `challenge-open`
- `[ ]` `challenge-upheld`
- `[ ]` `challenge-dismissed`
- `[ ]` score policy version
- `[ ]` configurable weights

## Phase 5

- `[ ]` `PoAW settlement policy` config document
- `[ ]` separate local score
- `[ ]` separate review score
- `[ ]` separate network trust score
- `[ ]` separate slash threshold
- `[ ]` separate challenge threshold
- `[ ]` separate complete threshold
- `[ ]` settlement preview bound to policy version

## Phase 6

- `[ ]` bridge-aware dispatch scoring doc
- `[ ]` bridge priority
- `[ ]` runtime priority
- `[ ]` recent success rate
- `[ ]` weak-network penalty
- `[ ]` relay backlog penalty
- `[ ]` peer health cache
- `[ ]` dispatch blacklist / cooldown

## Phase 7

- `[ ]` execution receipt schema version
- `[ ]` deterministic receipt schema
- `[ ]` subjective review receipt schema
- `[ ]` challenge evidence schema
- `[ ]` settlement relay receipt schema
- `[ ]` all receipts exposed through `schema/examples`

## Phase 8

- `[ ]` Git-native proof bundle
- `[ ]` task `commit sha`
- `[ ]` task `diff hash`
- `[ ]` review task `base/head`
- `[ ]` merge task `mergeability snapshot`
- `[ ]` dispute task `diff evidence`
- `[ ]` replay-inspect Git proof bundle

## Phase 9

- `[ ]` structured output for OpenClaw / OpenAI runtime
- `[ ]` LangGraph HTTP adapter
- `[ ]` container-job adapter skeleton
- `[ ]` MCP tool schema normalization
- `[ ]` A2A message schema normalization
- `[ ]` runtime capability advertisement

## Phase 10

- `[ ]` relay queue persistence
- `[ ]` background settlement relay worker
- `[ ]` relay queue pause / resume
- `[ ]` relay queue max in-flight
- `[ ]` relay queue dead-letter
- `[ ]` operator relay requeue

## Phase 11

- `[ ]` on-chain event reconciliation skeleton
- `[ ]` local relay vs chain tx comparison
- `[ ]` tx receipt fetch
- `[ ]` confirmed / reverted / unknown
- `[ ]` replay-inspect reconciliation state
- `[ ]` relay history `confirmed_at`

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
