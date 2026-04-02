# Operator Auth Hardening Plan

This document defines the near-term rollout for moving operator-facing AgentCoin endpoints beyond a single shared bearer token.

## Current Baseline

Today the reference node has one practical write-path guard:

- bind to loopback by default
- require `Authorization: Bearer <token>` when `auth_token` is configured
- rely on signed payload receipts for audit after a mutation succeeds

That baseline is useful for local and small trusted deployments, but it does not provide endpoint scoping, replay resistance, per-operator identity, or a clean downgrade policy when a node is exposed outside loopback.

## Goals

The hardening plan should deliver all of the following without breaking the current MVP API surface in one step:

1. Distinguish low-risk local write paths from high-risk trust, governance, and settlement mutations.
2. Identify the requesting operator or committee key separately from the shared node bearer token.
3. Prevent replay with explicit timestamp, nonce, and body-digest validation.
4. Preserve a migration path where existing bearer-token automation keeps working on loopback during rollout.
5. Emit explicit audit records for both successful mutations and denied requests.

## Endpoint Tiers

The reference node should classify write endpoints into policy tiers.

### Tier 0: Public read

Examples:

- `GET /healthz`
- `GET /v1/card`
- `GET /v1/peer-cards`
- `GET /v1/tasks`

Requirements:

- no operator auth required
- continue to rely on existing response-size and bind-address controls

### Tier 1: Local operational write

Examples:

- `POST /v1/tasks/requeue`
- `POST /v1/outbox/flush`
- `POST /v1/outbox/requeue`
- `POST /v1/git/branch`
- `POST /v1/git/task-context`

Requirements:

- bearer token remains acceptable during migration
- add scope checks once scoped tokens exist
- deny non-loopback access unless explicitly allowed

### Tier 2: Workflow and bridge admin

Examples:

- `POST /v1/workflows/fanout`
- `POST /v1/workflows/merge`
- `POST /v1/workflows/finalize`
- `POST /v1/bridges/import`
- `POST /v1/bridges/export`

Requirements:

- require operator identity, not only shared bearer possession
- add per-endpoint scopes such as `workflow-admin` and `bridge-admin`
- emit denial audit records when scope does not match the requested mutation

### Tier 3: Trust and governance admin

Examples:

- `POST /v1/peers/identity-trust/apply`
- `POST /v1/quarantines`
- `POST /v1/quarantines/release`
- `POST /v1/disputes`
- `POST /v1/disputes/resolve`
- `POST /v1/disputes/vote`

Requirements:

- require signed operator requests
- attach operator key id and auth metadata into governance receipts
- support committee identities without reusing a generic admin key
- keep bearer-token-only mode as an explicitly documented downgrade, not the default steady state

### Tier 4: Settlement and chain-control admin

Examples:

- `POST /v1/onchain/register-did`
- `POST /v1/onchain/stake`
- `POST /v1/onchain/create-job`
- `POST /v1/onchain/settlement-relay`
- `POST /v1/onchain/settlement-relay/replay`

Requirements:

- strongest auth tier in the node
- require signed requests plus scoped authorization
- prefer a separate settlement-admin key set from trust-admin keys
- disable bearer-only fallback once non-loopback chain control is enabled

## Request Signing Shape

The rollout should standardize a canonical operator-signing envelope.

Required request components:

- method
- path
- canonical query string
- timestamp
- nonce
- body digest
- operator key id
- signature

Suggested headers:

- `X-Agentcoin-Key-Id`
- `X-Agentcoin-Timestamp`
- `X-Agentcoin-Nonce`
- `X-Agentcoin-Body-Digest`
- `X-Agentcoin-Signature`

Validation rules:

1. Reject timestamps outside a narrow skew window.
2. Reject reused nonce plus key-id pairs.
3. Recompute and compare the body digest before signature verification.
4. Bind the signature to the exact HTTP method and path.
5. Record denial cause when any check fails.

## Operator Identity Model

The node should support at least these operator roles:

- `read-only`
- `workflow-admin`
- `trust-admin`
- `settlement-admin`
- `committee-member`

Each identity should map to:

- one or more public keys
- allowed scopes
- optional source restrictions such as loopback-only or overlay-only
- rotation status and revocation state

## Rollout Phases

### Phase 1: Policy inventory and docs

- document endpoint tiers
- surface auth context inside governance receipts
- keep bearer-token enforcement unchanged

### Phase 2: Scoped bearer model

- introduce scoped local tokens
- map existing operator endpoints to scopes
- add auth-failure audit records

### Phase 3: Signed operator requests

- add canonical request signing and verification
- support multiple operator keys and committee keys
- keep loopback bearer fallback only where explicitly configured

### Phase 4: Denial receipts and stricter defaults

- emit policy receipts for denied operator mutations
- deny high-risk tier access when only bearer auth is configured on non-loopback listeners
- add rotation and rollback guidance for operator keys

### Phase 5: Overlay and federated posture

- require stronger auth defaults when the node binds outside loopback or overlay addresses
- add least-privilege peer or operator scope separation
- integrate trust-source and committee-policy controls with the auth model

## Downgrade Behavior

Every phase should keep downgrade behavior explicit.

- If only bearer auth is configured, Tier 3 and Tier 4 endpoints should remain visibly marked as downgraded in docs and status views.
- If signed operator keys are configured, non-loopback Tier 3 and Tier 4 requests should stop accepting bearer-only fallback by default.
- If key verification fails but bearer fallback is still allowed, the node should reject silently upgrading to bearer semantics for a signed-looking request.

## Audit Requirements

Successful and denied operator requests should ultimately expose:

- operator key id or committee identity
- auth mode used
- endpoint and policy tier
- replay-protection inputs such as timestamp and nonce state
- mutation target
- allow or deny decision
- signed receipt or denial receipt when configured

## Exit Criteria

This plan can be considered implemented when:

1. all Tier 3 and Tier 4 endpoints require either signed operator requests or an explicitly documented local-only downgrade
2. operator roles and scopes are enforced per endpoint
3. auth failures create durable audit records
4. committee votes and trust mutations can be attributed to a concrete operator or committee key id
5. deployment docs no longer describe bearer-token-only protection as the primary long-term control