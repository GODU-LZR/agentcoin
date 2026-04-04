# ChatGPT Backend Handoff Alignment

## Source

This note aligns the current Python node with the local handoff at [var/chatgpt-backend-handoff.md](C:/Users/Twist/Desktop/agentcoin/var/chatgpt-backend-handoff.md).

## Current Status

The repository already partially satisfies the handoff:

- passwordless local identity bootstrap exists
- signed local client auth exists
- `GET /v1/manifest` exists
- `402 Payment Required` flow exists
- payment receipts, attestation, on-chain proof, RPC plan, raw bundle, relay, queue, and replay helpers exist
- local discovery and ACP session skeletons exist
- runtime adapters exist for OpenAI-compatible, Claude HTTP, Claude Code CLI, Copilot ACP skeleton, and related helpers
- CORS policy now supports a frontend-origin alias and a dedicated `GET /v1/status` daemon attach endpoint

## Gaps Still Open

The handoff still asks for capabilities that are only partially implemented:

- Web3-native request signing is still SSH-first, not yet secp256k1 / EIP-191 / EIP-712
- mDNS or LAN auto-discovery is still not implemented
- renter-facing payment credentials are still local signed receipts, not macaroons or chain-backed scoped execution tokens
- opaque execution is still only partly enforced
- high-value workflow input typing was missing service-level schema enforcement before this alignment pass

## New Backend Slice Added

This alignment pass adds the first explicit service registry and typed workflow boundary:

- `NodeConfig.services` now defines priced service metadata
- `GET /v1/capabilities` and `GET /v1/services` expose those services
- `manifest.services` now includes the same registry
- `POST /v1/workflow/execute` now validates `input` against a declared service schema when `strict_input=true`
- accepted workflow tasks now carry `_service` and `_opaque_execution` metadata for worker-side guardrails
- worker execution now rejects opaque services that arrive with free-form `messages` payloads, and it re-validates `strict_input` schemas before adapter execution
- worker execution now also sanitizes opaque runtime inputs before adapter dispatch and redacts echoed runtime/request metadata from the stored task result
- service config now supports private executor metadata (`executor_runtime`, `executor_options`, prompt/system templates) that stays out of `/v1/services` and is only used internally to derive typed opaque runtime requests
- payment-gated workflows can now exchange a verified `payment_receipt` for a short-lived, service-scoped `renter token`, and that token now carries an explicit capability scope with allowed operations such as `workflow-execute` plus a bounded usage quota
- renter-token status and summary inspection are now available for front-end dashboards that need to display remaining usage and service-scoped token activity
- payment ops summary now folds renter-token usage into the existing payment dashboard surface, so the front end can inspect relay and renter-consumption state from one endpoint
- per-service usage aggregation now exists for renter tokens, which gives the front end and future settlement logic a simple service-level consumption ledger
- per-service usage aggregation now also computes estimated settlement amounts from `price_per_call`, so the front end can render accrued value before a real settlement layer is wired in
- service-usage reconciliation now exists, which lets the front end see whether renter-token usage is merely recorded, awaiting proof submission, in-flight, relayed, or dead-lettered

## What This Does Not Yet Solve

- it does not yet isolate meta-prompts from runtime adapters
- it does not yet inject a dedicated guardrail parser before every LLM call
- it does not yet issue renter-scoped execution tokens after payment verification
- it does not yet expose a full MCP service description format

## Recommended Next Steps

1. Add worker-side enforcement that rejects opaque services when `_service.input_schema` is missing or when the runtime receives raw free-form chat input.
2. Add renter-scoped execution receipts or short-lived scoped tokens after payment verification.
3. Add service-level output schema and post-execution validation.
4. Add mDNS or LAN discovery once the browser/local daemon attach surface is stable.
