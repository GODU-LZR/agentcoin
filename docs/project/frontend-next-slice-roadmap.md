# AgentCoin Frontend Next-Slice Roadmap

## Purpose

This document recalibrates the next frontend tasks against the current codebase.

Older planning documents were written when the workbench was still converging on a Compose plus Node baseline. That is no longer the full picture. The live frontend already has a shell, a loopback proxy, attach/auth flows, alert routing, and five working window surfaces.

The goal of this document is to define the next slice without re-planning work that is already shipped.

## Source Baseline

This roadmap is grounded in the current implementations and planning documents:

- `agentcoin/node.py`
- `web/src/app/[locale]/page.tsx`
- `web/src/app/api/local-node/route.ts`
- `docs/project/frontend-copilot-backend-integration.md`
- `docs/project/frontend-ascii-multilingual-plan.md`
- `docs/project/frontend-window-ownership-map.md`

## What Is Already True

### Browser-to-node transport already exists

- the frontend already uses a same-origin proxy at `web/src/app/api/local-node/route.ts`
- that proxy already restricts requests to loopback hosts only
- attach already probes `GET /v1/status`, then reads `GET /v1/manifest` and `GET /v1/auth/challenge`
- local browser auth already upgrades into a short-lived `Agentcoin-Session`

### The shell is already live

- the workbench already has a window rail
- the active workspace area is already switchable
- the shell already aggregates alerts and critical-action guards
- the tutorial and landing scenes already exist

### All five primary windows already render live data

- `Compose`: terminal feed, multimodal draft state, attachment gallery, task dispatch entry
- `Node`: local attach, discovery, managed registrations, ACP lifecycle, runtime refresh
- `Swarm`: peer list, peer cards, peer health, trust review and sync state
- `Wallet`: payment ops summary, usage summary, reconciliation state, renter-token summary
- `Community`: local services, capabilities, remote operator directory, trust posture

### The remaining gaps are depth and ownership, not basic existence

- the workflow entry point is still a modal instead of a Swarm-native workspace
- Wallet is mostly summary-first and read-heavy, not action-first
- Community is already readable, but still intentionally phase-one read-only
- `page.tsx` still owns too much cross-window state and logic

## Planning Corrections

The next planning slice should explicitly correct these outdated assumptions:

1. Do not describe `Swarm`, `Wallet`, or `Community` as future-only windows. They are already live in the current workspace.
2. Do not keep shipping copy that says phase one only contains `Compose` and `Node`. The message catalogs still contain that older framing.
3. Do not treat local attach and real discovery as unfinished roadmap items. They are already wired.
4. Do not add more surface area into `page.tsx` before state ownership is split into shell and window modules.
5. Do not leave locale-sensitive proxy, network, auth, and security errors hardcoded in Chinese when the workspace already supports multilingual UI.

## Backend Surfaces Already Ready For Frontend Expansion

The backend already exposes more than the current frontend is consuming deeply.

### Swarm / runtime / workflow surfaces

- `GET /v1/peers`
- `GET /v1/peer-cards`
- `GET /v1/peer-health`
- `POST /v1/peers/sync`
- `POST /v1/tasks/dispatch`
- `GET /v1/tasks/dispatch/preview`
- `POST /v1/tasks/dispatch/evaluate`
- `GET /v1/tasks`
- `GET /v1/workflows`
- `GET /v1/workflows/summary`
- `GET /v1/tasks/replay-inspect`
- `GET /v1/outbox`
- `GET /v1/outbox/dead-letter`

### Wallet / payment / settlement surfaces

- `GET /v1/payments/ops/summary`
- `GET /v1/payments/service-usage/summary`
- `GET /v1/payments/service-usage/reconciliation`
- `GET /v1/payments/renter-tokens/summary`
- `GET /v1/payments/receipts/onchain-relays`
- `GET /v1/payments/receipts/onchain-relays/latest`
- `GET /v1/payments/receipts/onchain-relays/latest-failed`
- `GET /v1/payments/receipts/onchain-relay-queue`
- `GET /v1/payments/receipts/onchain-relay-queue/summary`
- `POST /v1/payments/receipts/issue`
- `POST /v1/payments/receipts/introspect`
- `POST /v1/payments/renter-tokens/issue`
- `POST /v1/payments/renter-tokens/introspect`
- `POST /v1/payments/receipts/onchain-relay-queue/pause`
- `POST /v1/payments/receipts/onchain-relay-queue/resume`
- `POST /v1/payments/receipts/onchain-relay-queue/requeue`
- `POST /v1/payments/receipts/onchain-relay-queue/cancel`
- `POST /v1/payments/receipts/onchain-relay-queue/delete`
- `POST /v1/payments/receipts/onchain-relay-queue/auto-requeue/disable`
- `POST /v1/payments/receipts/onchain-relay-queue/auto-requeue/enable`
- `POST /v1/payments/receipts/onchain-relay/replay-helper`

### Governance and operator surfaces

- `GET /v1/disputes`
- `GET /v1/governance-actions`
- `GET /v1/violations`
- `GET /v1/quarantines`
- `GET /v1/onchain/settlement-relays`
- `GET /v1/onchain/settlement-relay-queue`
- `GET /v1/onchain/settlement-relays/latest`

## Next Tasks

### 1. Split the monolithic workspace into shell modules and window modules

This is the highest-leverage next task.

Ship next:

- a shell component that owns the rail, status strip, alert summary, tutorial overlay, and critical-action guard
- dedicated window components for `Compose`, `Node`, `Swarm`, `Wallet`, and `Community`
- shared client hooks for local attach/auth, peer state, wallet ledger state, and ACP session state
- shared request helpers so fetch/proxy/auth logic no longer sits inline inside `page.tsx`

Why now:

- all five windows already exist, so the bottleneck is ownership clarity, not concept design
- additional UI work inside the current monolith will increase drift and duplicated logic

### 2. Promote Swarm from peer monitor into the actual orchestration workspace

Ship next:

- move the workflow modal into the `Swarm` window
- expose dispatch preview and route evaluation instead of only firing dispatch requests
- add workflow inventory and replay drill-down using `GET /v1/tasks`, `GET /v1/workflows`, `GET /v1/workflows/summary`, and `GET /v1/tasks/replay-inspect`
- expose outbox and dead-letter diagnostics as Swarm-side operational panels

Why now:

- the window already has remote peer, trust, and sync context
- keeping workflow execution inside a modal blocks Swarm from becoming a first-class coordination surface

### 3. Promote Wallet from summary dashboard into an actionable ledger

Ship next:

- map backend `recommended_actions` into concrete CTA buttons instead of rendering them as plain strings
- wire the existing browser helpers for receipt issue/introspection and renter-token issue/introspection into Wallet panels
- add relay history and queue drill-down panels
- expose pause, resume, requeue, cancel, delete, replay-helper, and auto-requeue controls
- expose latest failed relay and reconciliation status as operator-first recovery flows

Why now:

- the backend already concentrates the default dashboard state in `GET /v1/payments/ops/summary`
- Wallet already shows enough summary context to support operator actions without inventing a new information model

Implementation note:

- the browser already has helper functions for receipt and renter-token operations, but they are not yet surfaced in the active window UX
- the browser also has a `handleWorkflowExecute` helper, but it is not wired into the active workspace flow and should be aligned to the backend `workflow_name` contract before it becomes the primary metered workflow path

### 4. Tighten Node ownership and remove cross-window duplication

Ship next:

- keep `Node` focused on local attach, discovery, managed local agents, runtimes, and ACP control
- remove the duplicated multimodal composer block from `Node`
- keep window shortcuts, but stop using `Node` as a general spillover surface for Compose and Wallet behavior

Why now:

- `Node` is already too broad compared with the ownership map
- the current duplication makes future refactors harder and weakens the meaning of the window model

### 5. Expand Community from read-only directory into publish and invite preparation

Ship next:

- keep phase one Community read-only for services, capabilities, and remote operator profiles
- add explicit publish-readiness panels for local service metadata and capability metadata
- add invite and external-operator onboarding flows only after Wallet and Swarm no longer borrow the same responsibilities

Why later than Wallet and Swarm:

- Community depends on trust posture and settlement visibility being legible elsewhere first
- the current read-only catalog is enough for the present slice

### 6. Add governance and replay operator views without adding a sixth major window yet

Ship next:

- drawers or tabs for disputes, governance actions, violations, quarantines, and settlement relay queue views
- start by attaching these views to `Swarm` and `Wallet` where the operator context already exists

Why this shape first:

- the backend is ready now
- a dedicated governance window can wait until the existing five windows are fully coherent

### 7. Remove copy drift and locale debt

Ship next:

- move hardcoded proxy, timeout, auth, payment, and security errors into the locale message files
- retire or rewrite the old `planned_window_*` phase-one messaging so it no longer contradicts the live workspace
- update older frontend roadmap docs to point readers to this document for the current next slice

Why now:

- the current workspace already aims for locale-pure copy
- copy drift is now causing architectural drift, not just wording drift

## Recommended Delivery Order

### Slice A. Structural extraction and copy cleanup

Complete first:

- shell extraction
- window extraction
- shared hooks and request helpers
- removal of hardcoded multilingual drift

### Slice B. Swarm orchestration and Wallet actions

Complete next:

- move workflow modal into `Swarm`
- add workflow replay and outbox drill-down
- add Wallet CTAs for receipt, renter-token, and queue operations

### Slice C. Governance overlays and Community expansion

Complete after that:

- disputes, governance, violations, quarantine, and settlement relay views
- Community publish-readiness and invite preparation

## Exit Criteria For This Next Slice

The next slice should be considered complete when:

1. `page.tsx` is reduced to shell composition rather than full workspace ownership.
2. `Swarm`, `Wallet`, and `Community` are treated as current surfaces in both code and docs, not as planned-only windows.
3. Wallet can perform at least one end-to-end actionable payment recovery flow instead of only showing summaries.
4. Workflow execution no longer depends on a generic modal as the main orchestration entry point.
5. Locale-sensitive runtime and network errors no longer bypass the message catalogs.

## Maintenance Note

Keep this document synchronized with:

- `docs/project/frontend-window-ownership-map.md` for state and handler ownership
- `docs/project/frontend-copilot-backend-integration.md` for endpoint-level backend usage
- `docs/project/frontend-ascii-multilingual-plan.md` for shell and visual constraints

When those documents and the live frontend diverge, this roadmap should be updated before adding more UI surface area.