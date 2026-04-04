# Frontend Copilot Backend Integration Guide

## Purpose

This guide is for the frontend Copilot workstream. It explains which local-first backend surfaces already exist in AgentCoin and how the web app should consume them without guessing hidden backend behavior.

## Scope

This document focuses on:

- local daemon attach
- service and capability discovery
- payment and renter-token flows
- payment relay and renter usage dashboards
- reconciliation and operator guidance payloads

It does not cover visual design, copywriting, or front-end component structure.

## Base Assumptions

- the backend daemon runs on `http://127.0.0.1:<port>`
- the frontend should prefer `GET /v1/status` first
- after attach succeeds, the frontend should read `GET /v1/manifest`
- the frontend should not hardcode backend routes when a route already appears in `manifest.payment` or `card.endpoints`

## Recommended Attach Flow

1. Probe `GET /v1/status`
2. If reachable, read:
   - `local_daemon`
   - `local_identity`
   - `frontend_origins`
   - `routes`
3. Read `GET /v1/manifest`
4. Cache:
   - `manifest.payment`
   - `manifest.services`
   - `manifest.discovery`
   - `manifest.card.endpoints`

## Service Discovery Surfaces

Use these endpoints:

- `GET /v1/manifest`
- `GET /v1/capabilities`
- `GET /v1/services`

Important service fields already exposed:

- `service_id`
- `description`
- `price_per_call`
- `price_asset`
- `renter_token_max_uses`
- `privacy_level`
- `input_schema`
- `output_schema`
- `strict_input`
- `opaque_execution`
- `tags`

Important constraint:

- private opaque executor fields are intentionally not exposed to the frontend

## Local Identity and Session Flow

Use these endpoints:

- `GET /v1/auth/challenge`
- `POST /v1/auth/verify`

Successful verify returns:

- a signed receipt
- a short-lived loopback `Agentcoin-Session`

The frontend can use that session for allowed local-only routes. The allowlist already includes payment, renter-token, discovery, and local task routes.

## Metered Workflow Flow

For a priced workflow:

1. call `POST /v1/workflow/execute`
2. if unpaid, expect `402 Payment Required`
3. read:
   - `payment.challenge`
   - `payment.quote`
   - `X-Agentcoin-Payment-Required`
4. issue a local receipt after payment proof is available:
   - `POST /v1/payments/receipts/issue`
5. optionally introspect it:
   - `POST /v1/payments/receipts/introspect`

## Renter Token Flow

The frontend should prefer renter tokens over repeatedly sending the original receipt.

Use these endpoints:

- `POST /v1/payments/renter-tokens/issue`
- `POST /v1/payments/renter-tokens/introspect`
- `GET /v1/payments/renter-tokens/status`
- `GET /v1/payments/renter-tokens/summary`

Important request fields:

- `workflow_name`
- `service_id`
- `payment_receipt`
- optional `max_uses`

Important response fields:

- `token`
- `token_status`
- `scope`
- `remaining_uses`
- `usage_count`

Current renter-token scope model:

- `workflow_name`
- `service_id`
- `allowed_operations`
- `privacy_level`
- `max_uses`

Current operation value used by the backend:

- `workflow-execute`

## Payment Operations Dashboard

Use:

- `GET /v1/payments/ops/summary`

This is the main dashboard payload. It already includes:

- quote template
- relay queue summary
- latest relay
- latest failed relay
- renter token summary
- service usage summary
- service usage reconciliation
- auto-requeue policy
- recent relays

Frontend recommendation:

- build the default payment workspace from this single payload
- use narrower endpoints only for drill-down panels

## Service Usage Dashboard

Use:

- `GET /v1/payments/service-usage/summary`
- `GET /v1/payments/service-usage/reconciliation`

`service-usage/summary` provides:

- per-service token counts
- active token counts
- total usage counts
- total remaining uses
- `price_per_call`
- `price_asset`
- `estimated_settlement_amount`
- `estimated_settlement_totals`

`service-usage/reconciliation` provides:

- `reconciliation_status`
- `recommended_actions`
- receipt state
- relay state
- queue summary
- usage summary

Current reconciliation states:

- `idle`
- `receipt-issued`
- `usage-recorded`
- `usage-recorded-awaiting-proof`
- `proof-in-flight`
- `proof-relayed`
- `proof-dead-letter`

Current recommended action values:

- `issue-renter-token`
- `introspect-receipt`
- `build-payment-proof`
- `queue-payment-relay`
- `inspect-relay-queue`
- `inspect-latest-relay`
- `inspect-latest-failed-relay`
- `replay-helper`
- `requeue-payment-relay`
- `build-onchain-rpc-plan`
- `inspect-renter-token-summary`

Frontend recommendation:

- render reconciliation badges directly from `reconciliation_status`
- map `recommended_actions` to CTA buttons instead of inventing custom heuristics

## Payment Relay Drill-Down

Use these when the dashboard needs deeper operator detail:

- `GET /v1/payments/receipts/onchain-relays`
- `GET /v1/payments/receipts/onchain-relays/latest`
- `GET /v1/payments/receipts/onchain-relays/latest-failed`
- `GET /v1/payments/receipts/onchain-relay-queue`
- `GET /v1/payments/receipts/onchain-relay-queue/summary`
- `POST /v1/payments/receipts/onchain-relay/replay-helper`

Queue controls already exist:

- pause
- resume
- auto-requeue disable
- auto-requeue enable
- requeue
- cancel
- delete

## Opaque Service Guardrails

Frontend should respect these backend constraints:

- opaque services should only send typed `input`
- do not send free-form `messages` to opaque services
- do not assume private executor prompts are available to the browser

If `strict_input=true`, build forms directly from the declared `input_schema`.

## Frontend Integration Priorities

1. Local daemon attach via `GET /v1/status`
2. Manifest-driven service list
3. 402 challenge and renter-token exchange
4. Payment ops dashboard
5. Service usage and reconciliation panels
6. Drill-down relay controls

## Do Not Assume

- do not assume secp256k1 or EIP-712 is active yet
- do not assume mDNS discovery exists yet
- do not assume private executor config is browser-visible
- do not assume every priced workflow already has a chain-backed settlement transaction
