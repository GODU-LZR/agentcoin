# PoAW Settlement Policy

This document defines how the current AgentCoin reference node turns local `PoAW` events into a settlement recommendation.

## Scope

The current implementation is a local, versioned policy layer. It does not broadcast transactions by itself and it does not replace chain settlement logic. It decides which path is recommended next:

- `completeJob`
- `challengeJob`
- `rejectJob`
- `slashJob`

## Policy Inputs

The settlement preview combines four sources:

- task-level `PoAW` score summary
- worker reputation
- task-scoped policy violations
- dispute state

The preview computes these score buckets:

- `local_score`
- `review_score`
- `network_trust_score`

It also keeps the aggregate `positive_points`, `negative_points`, and final bounded `score`.

## Config Keys

These node config keys control the active settlement policy:

- `poaw_policy_version`
- `poaw_score_weights`
- `onchain.settlement_policy_version`
- `onchain.settlement_complete_threshold`
- `onchain.settlement_challenge_negative_points_threshold`
- `onchain.settlement_min_review_score`
- `onchain.settlement_network_trust_threshold`
- `onchain.settlement_slash_negative_points_threshold`
- `onchain.settlement_challenge_on_open_dispute`
- `onchain.settlement_challenge_on_escalated_dispute`

## Decision Order

The current decision order is intentionally strict:

1. If the adapter policy rejected execution, recommend `rejectJob`.
2. If open or escalated disputes are configured to force review, recommend `challengeJob`.
3. If an upheld dispute exists, recommend `slashJob`.
4. If the worker is quarantined, has severe violations, or the negative score crosses the slash threshold, recommend `slashJob`.
5. If the total score, negative score, review score, or network trust score misses a configured threshold, recommend `challengeJob`.
6. Otherwise, recommend `completeJob`.

## Event Taxonomy

The current `PoAW` event vocabulary includes:

- `deterministic-pass`
- `deterministic-fail`
- `subjective-approve`
- `subjective-reject`
- `subjective-complete`
- `merge-completed`
- `task-completed`
- `challenge-open`
- `challenge-upheld`
- `challenge-dismissed`
- `dispute-bond-awarded`
- `dispute-bond-slashed`
- `policy-violation`

## Output Shape

`GET /v1/onchain/settlement-preview?task_id=...` returns:

- `recommended_resolution`
- `recommended_sequence`
- `score`
- `score_breakdown`
- `settlement_policy`
- `resolution_params`
- signed intent previews

The `settlement_policy` block is versioned so previews can be audited later against the policy that produced them.

## Current Limits

This policy is still a local MVP:

- it does not reconcile with on-chain receipts yet
- it does not include committee-weighted settlement math
- it does not implement final PoAW token economics
- it does not replace evaluator contracts

Those gaps are deliberate and are tracked in the implementation roadmap.
