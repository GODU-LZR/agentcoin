# Trust Operator Runbook

This runbook replaces the old chat-oriented handoff document with an operator-focused procedure for reviewing, previewing, applying, and recovering peer SSH identity trust state.

## Scope

Use this guide when an operator needs to inspect or update peer identity trust through the current HTTP API.

Relevant endpoints:

- `POST /v1/peers/sync`
- `GET /v1/peer-cards`
- `POST /v1/peers/identity-trust/export`
- `POST /v1/peers/identity-trust/apply`
- `GET /v1/governance-actions?actor_id=...`

## Preconditions

1. The node must be reachable over HTTP.
2. If the node is configured with `auth_token`, send `Authorization: Bearer <token>`.
3. Run at least one peer sync before attempting trust export or trust apply, otherwise no stored peer card will exist.
4. Start the node with `--config <path>` if the operator needs config previews or on-disk persistence. Without a loaded config file, preview still works in runtime-only mode, but `persist_to_config=true` will fail.

## Severity Model

The current trust report ranks review items as follows:

- `none`: no action required.
- `medium`: pending trust keys or stale trusted keys.
- `high`: principal mismatch or pending revocation.
- `critical`: a locally revoked key is still being advertised by the peer.

`POST /v1/peers/identity-trust/export` sorts items by descending `severity_rank`, so critical peers should be investigated first.

## Suggested Actions

The export and preview flow can suggest these actions:

- `adopt-advertised-principal`: accept the principal currently advertised by the peer card.
- `apply-pending-trust`: add newly advertised active keys into local trusted peer identity keys.
- `apply-pending-revocations`: add newly advertised revoked keys into local revoked keys and remove them from trusted keys.
- `remove-stale-trusted`: remove trusted keys that are no longer advertised as active.

If `revoked_still_advertised_public_keys` is populated, the current implementation marks the peer as critical but does not auto-suggest a mutation. Treat that as an incident review, not a routine approval.

## Standard Review Loop

### 1. Refresh peer cards

```bash
curl -X POST \
  -H "Authorization: Bearer token-a" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/v1/peers/sync \
  -d '{}'
```

### 2. Inspect stored trust state

```bash
curl \
  -H "Authorization: Bearer token-a" \
  http://127.0.0.1:8080/v1/peer-cards
```

Look at `identity_trust` for each peer card. The report exposes:

- `severity`, `severity_rank`, `severity_reasons`
- `principal_match`
- `pending_trust_public_keys`
- `pending_revocation_public_keys`
- `stale_trusted_public_keys`
- `revoked_still_advertised_public_keys`

### 3. Export a prioritized reconciliation bundle

```bash
curl -X POST \
  -H "Authorization: Bearer token-a" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/v1/peers/identity-trust/export \
  -d '{"include_preview": true}'
```

This returns:

- `items[].suggested_actions`
- `items[].preview`
- `items[].identity_trust`
- top-level severity fields copied onto each item for easier sorting and external review

Use `peer_id` in the request body to scope review to a single peer.

## Safe Apply Workflow

### 1. Preview the exact mutation

```bash
curl -X POST \
  -H "Authorization: Bearer token-a" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/v1/peers/identity-trust/apply \
  -d '{
    "peer_id": "node-b",
    "operator_id": "admin-1",
    "reason": "preview rotated peer key",
    "actions": ["apply-pending-trust"],
    "preview_only": true
  }'
```

Check:

- `before` versus `after`
- `applied_actions` versus `noop_actions`
- `config_preview`
- `would_persist_to_config`

### 2. Apply runtime-only or persist to config

Runtime-only apply:

```bash
curl -X POST \
  -H "Authorization: Bearer token-a" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/v1/peers/identity-trust/apply \
  -d '{
    "peer_id": "node-b",
    "operator_id": "admin-1",
    "reason": "approve rotated peer key",
    "actions": ["apply-pending-trust"]
  }'
```

Persist to the loaded config file:

```bash
curl -X POST \
  -H "Authorization: Bearer token-a" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/v1/peers/identity-trust/apply \
  -d '{
    "peer_id": "node-b",
    "operator_id": "admin-1",
    "reason": "approve rotated peer key and persist",
    "actions": ["apply-pending-trust"],
    "persist_to_config": true
  }'
```

### 3. Verify the audit trail

```bash
curl \
  -H "Authorization: Bearer token-a" \
  "http://127.0.0.1:8080/v1/governance-actions?actor_id=node-b"
```

Successful trust updates record:

- `action_type = peer-identity-trust-apply`
- `operator_id`
- a signed governance receipt
- `before` and `after` trust reports
- whether the change was runtime-only or persisted to config

## Recovery Patterns

### Rotated peer key observed

Symptoms:

- `pending_trust_public_keys` is populated.
- severity is usually `medium`.

Action:

- preview and then apply `apply-pending-trust`.

### Peer revoked an old key

Symptoms:

- `pending_revocation_public_keys` is populated.
- severity is `high`.

Action:

- preview and then apply `apply-pending-revocations`.

### Principal rename or canonicalization

Symptoms:

- `principal_match` is `false`.
- `advertised_principal` differs from `configured_principal`.

Action:

- preview and then apply `adopt-advertised-principal` if the rename is expected.

### Stale trusted key after rotation cleanup

Symptoms:

- `stale_trusted_public_keys` is populated.
- severity is usually `medium`.

Action:

- preview and then apply `remove-stale-trusted`.

### Revoked key still advertised

Symptoms:

- `revoked_still_advertised_public_keys` is populated.
- severity is `critical`.

Action:

1. Do not treat this as routine trust drift.
2. Freeze further trust approval for that peer until the advertised card is explained.
3. Re-sync once to rule out stale data.
4. Escalate for peer-side remediation or local rejection policy handling.

## Known Limits

- Tier 3 and Tier 4 operator mutations now accept signed operator requests with nonce replay rejection, denial receipts, and durable auth audit records when `operator_identities` are configured. The phased hardening plan still lives in `docs/project/operator-auth-hardening-plan.md`, and scoped bearer tokens plus broader role coverage are not complete yet.
- There is no persisted trust history export yet for external audit pipelines.
- The node surfaces critical revoked-key conflicts, but local automatic rejection policy is not implemented yet.
- `persist_to_config=true` requires a node config file loaded via `--config`.