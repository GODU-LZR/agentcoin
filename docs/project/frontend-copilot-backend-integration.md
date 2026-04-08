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

## Live Integration Findings (2026-04-08)

This section records issues observed against the currently running local frontend-integration daemon on `http://127.0.0.1:8080`.

These findings describe the live instance exactly as tested. If another agent is debugging or hot-restarting that daemon in parallel, the running behavior may temporarily differ from the current workspace code.

### Confirmed Backend Contract Issues

- `GET /v1/capabilities` currently returns the service registry under `items` instead of capability data.
- `GET /v1/services` and `GET /v1/capabilities` both currently return `{ "items": [...] }`, while the current frontend attach flow expects `services` and `capabilities`.
- `GET /v1/payments/receipts/status` can return consumed receipt objects whose mutable status fields no longer match the original signature, so reposting that returned object to `POST /v1/payments/receipts/introspect` fails signature verification.
- `GET /v1/payments/renter-tokens/status` has the same stale-signature problem for consumed or updated renter tokens, so reposting the returned token to `POST /v1/payments/renter-tokens/introspect` can also fail signature verification.
- `POST /v1/auth/verify` works when the caller sends both the JSON body and signed `X-Agentcoin-*` identity headers. A body-only browser call fails even though the route itself is healthy.
- When `onchain.enabled=false`, proof-building endpoints reject as expected, but `POST /v1/payments/receipts/onchain-relay-queue` still accepts queue items that later dead-letter during processing.

### GitHub Copilot CLI ACP Findings

- Local discovery, managed process launch, and ACP initialize all succeeded for `github-copilot-cli`.
- The tested live daemon still dispatched ACP task requests with method `prompt`, and GitHub Copilot CLI responded with JSON-RPC error `-32601` (`Method not found`).
- The tested live daemon required `server_session_id` for ACP task dispatch, but the observed initialize response did not provide a usable server session id.
- `POST /v1/discovery/local-agents/acp-session/apply-task-result` currently accepts only success frames that contain `result`. If Copilot returns a JSON-RPC `error` frame, the local task remains `queued` instead of being marked failed.
- Ordinary `worker` tasks are not ideal ACP test fixtures because the background `agentcoin-worker` can claim them before the ACP bridge applies a result. Reviewer-only tasks are safer for isolated ACP debugging.
- The tested live daemon did not expose newer ACP session helper routes that already exist in the repository, which strongly suggests that the process bound to `127.0.0.1:8080` may be stale relative to the current workspace code.

### Retest Guidance

- Confirm which Python process actually owns `127.0.0.1:8080` before drawing conclusions from ACP behavior.
- If GitHub Copilot CLI still reports `Method not found` for `prompt`, restart the local daemon from the current workspace state before changing frontend ACP logic.
- Treat `server_session_id` handling and ACP error-frame materialization as backend issues first, not frontend rendering issues.

## PowerShell Reproduction Notes (2026-04-08)

These examples were captured from the same live daemon. They are meant to help another debugger reproduce the observed behavior quickly without guessing route names or payload shape.

### 1. Confirm Which Process Owns Port 8080

```powershell
Get-NetTCPConnection -LocalPort 8080 -State Listen |
  Select-Object LocalAddress, LocalPort, OwningProcess

Get-CimInstance Win32_Process -Filter "ProcessId = 42240" |
  Select-Object ProcessId, CommandLine | Format-List
```

Observed result during this test pass:

- port `8080` was owned by PID `42240`
- PID `42240` command line was `"C:\Users\Twist\AppData\Local\Programs\Python\Python311\python.exe" -m agentcoin --config configs/node.frontend-local.json --log-level INFO`

### 2. Reproduce the Service/Capability Payload Mismatch

```powershell
$headers = @{ Authorization = 'Bearer dev-token' }

Invoke-RestMethod -Uri 'http://127.0.0.1:8080/v1/capabilities' -Headers $headers |
  ConvertTo-Json -Depth 6

Invoke-RestMethod -Uri 'http://127.0.0.1:8080/v1/services' -Headers $headers |
  ConvertTo-Json -Depth 6
```

Observed result during this test pass:

- both routes returned the same `items` array
- the returned array contained service metadata for `premium-review`
- the live payload did not expose distinct top-level `capabilities` or `services` fields

### 3. Reproduce the GitHub Copilot CLI ACP Method Mismatch

```powershell
$headers = @{ Authorization = 'Bearer dev-token' }

Invoke-RestMethod -Uri 'http://127.0.0.1:8080/v1/discovery/local-agents/acp-sessions' -Headers $headers |
  ConvertTo-Json -Depth 8
```

Observed result during this test pass:

- session `d235df08-17ee-44d5-898e-efce621475d4` was open for `local-github-copilot-cli`
- the initialize response identified Copilot CLI `1.0.20`
- `last_task_request_intent.request.method` was still `prompt`
- the latest server frame contained JSON-RPC error `-32601` with message `Method not found: prompt`

### 4. Reproduce Missing Newer ACP Helper Routes on the Live Daemon

```powershell
try {
  $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/v1/discovery/local-agents/acp-session/list' `
    -Headers @{ Authorization = 'Bearer dev-token' } -UseBasicParsing
  'STATUS=' + [int]$resp.StatusCode
} catch {
  'STATUS=' + [int]$_.Exception.Response.StatusCode.value__
}

try {
  $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/v1/discovery/local-agents/acp-session/load' `
    -Headers @{ Authorization = 'Bearer dev-token' } -UseBasicParsing
  'STATUS=' + [int]$resp.StatusCode
} catch {
  'STATUS=' + [int]$_.Exception.Response.StatusCode.value__
}
```

Observed result during this test pass:

- both routes returned `404`
- this differs from the current repository state, which already contains these helper routes

### 5. Reproduce `server_session_id` Rejection

```powershell
$body = @{
  session_id = 'd235df08-17ee-44d5-898e-efce621475d4'
  server_session_id = ''
  task_id = 'copilot-acp-queued-3a179f6d'
} | ConvertTo-Json

try {
  Invoke-WebRequest -Uri 'http://127.0.0.1:8080/v1/discovery/local-agents/acp-session/task-request' `
    -Method Post `
    -Headers @{ Authorization = 'Bearer dev-token'; 'Content-Type' = 'application/json' } `
    -Body $body -UseBasicParsing
} catch {
  'STATUS=' + [int]$_.Exception.Response.StatusCode.value__
}
```

Observed result during this test pass:

- the live daemon returned `400`
- the failure occurs before a useful ACP task request can be sent if the caller does not already know a server session id

### 6. Reproduce Stale Signature Objects from Status Endpoints

Example receipt and token ids observed in the live dev database:

- receipt id `ff9e8c06-33ce-4c2c-872b-e52c76dcb805`
- token id `c74c9cb1-0142-437f-ba59-e910bc465c85`

```powershell
$headers = @{ Authorization = 'Bearer dev-token' }

$receipt = (Invoke-RestMethod -Uri 'http://127.0.0.1:8080/v1/payments/receipts/status?receipt_id=ff9e8c06-33ce-4c2c-872b-e52c76dcb805' -Headers $headers).receipt
$receiptBody = @{ payment_receipt = $receipt } | ConvertTo-Json -Depth 12

try {
  Invoke-WebRequest -Uri 'http://127.0.0.1:8080/v1/payments/receipts/introspect' `
    -Method Post `
    -Headers @{ Authorization = 'Bearer dev-token'; 'Content-Type' = 'application/json' } `
    -Body $receiptBody -UseBasicParsing
} catch {
  'STATUS=' + [int]$_.Exception.Response.StatusCode.value__
}

$token = (Invoke-RestMethod -Uri 'http://127.0.0.1:8080/v1/payments/renter-tokens/status?token_id=c74c9cb1-0142-437f-ba59-e910bc465c85' -Headers $headers).token
$tokenBody = @{ token = $token } | ConvertTo-Json -Depth 12

try {
  Invoke-WebRequest -Uri 'http://127.0.0.1:8080/v1/payments/renter-tokens/introspect' `
    -Method Post `
    -Headers @{ Authorization = 'Bearer dev-token'; 'Content-Type' = 'application/json' } `
    -Body $tokenBody -UseBasicParsing
} catch {
  'STATUS=' + [int]$_.Exception.Response.StatusCode.value__
}
```

Observed result during this test pass:

- both introspection calls returned `400`
- the status payloads contained mutated fields such as `status`, `remaining_uses`, `usage_count`, `consumed_at`, and `consumed_task_id`
- the embedded signature still appeared to be the original issue-time signature

### 7. Reproduce Body-Only Local Auth Failure

```powershell
$challenge = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/v1/auth/challenge'
$body = @{
  challenge = $challenge.challenge
  public_key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIO3zoZe6NVRUF5ULEwEVuzXHbO7ehIniBKF8yswaOc9t agentcoin-local-dev'
  signature = 'invalid'
  client = @{ name = 'debug'; version = '0.1' }
} | ConvertTo-Json -Depth 8

try {
  Invoke-WebRequest -Uri 'http://127.0.0.1:8080/v1/auth/verify' `
    -Method Post `
    -Headers @{ 'Content-Type' = 'application/json' } `
    -Body $body -UseBasicParsing
} catch {
  'STATUS=' + [int]$_.Exception.Response.StatusCode.value__
}
```

Observed result during this test pass:

- body-only verification returned `400`
- the route requires the signed local identity request headers in addition to the JSON body

### 8. Reproduce Onchain-Disabled Queue Dead-Letter Behavior

```powershell
$headers = @{ Authorization = 'Bearer dev-token' }

Invoke-RestMethod -Uri 'http://127.0.0.1:8080/v1/payments/ops/summary' -Headers $headers |
  ConvertTo-Json -Depth 8
```

Observed result during this test pass:

- `queue_summary.counts.dead-letter` was `1`
- the latest failed queue item had `last_error = onchain payment proof requires onchain bindings to be enabled`
- the same local profile had `onchain.enabled=false`

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

## ASCII Workbench Companion

For local debugging outside the browser, the backend now exposes an ASCII terminal companion:

- `agentcoin-ascii --endpoint http://127.0.0.1:8080 --token <token>`

It mirrors the same backend surfaces the frontend should use:

- status
- manifest
- services
- local discovery
- payment ops summary
- service usage reconciliation

Useful commands inside the terminal:

- `connect`
- `token`
- `receipt`
- `probe`
- `services`
- `discover`
- `ops`
- `status`

## Do Not Assume

- do not assume secp256k1 or EIP-712 is active yet
- do not assume mDNS discovery exists yet
- do not assume private executor config is browser-visible
- do not assume every priced workflow already has a chain-backed settlement transaction
