# AgentCoin Frontend Plan: ASCII Multilingual Console

## Goal

Build the next front-end phase as a local-first, multilingual ASCII console rather than a generic SaaS dashboard.
The UI should expose real AgentCoin runtime capability already present in the Python node, while preserving the current visual language:

- ASCII-first presentation
- monochrome / high-contrast terminal hierarchy
- selective glow, transparency, and HUD overlays
- local-first trust and loopback workflows
- full locale parity across Simplified Chinese, English, and Japanese

## Current State

The current web client already has:

- a multilingual landing page with ASCII Earth and manifesto-style intro
- a themed terminal-like workspace shell
- locale routing with `next-intl`
- a visual concept for local/remote agent discovery

The current web client does **not** yet expose most of the runtime that now exists in the backend.
That is the main front-end gap.

## Backend Capability Inventory Relevant To Frontend

The Python node already exposes enough capability to justify a much richer front-end.
The front-end plan should be built around these capability groups.

### 1. Local node bootstrap and trust

Available backend surfaces:

- `GET /healthz`
- `GET /v1/manifest`
- `GET /v1/card`
- `GET /v1/auth/challenge`
- `POST /v1/auth/verify`

Front-end implication:

- the browser can detect whether a local daemon is running
- the browser can read node identity / manifest info
- the browser can complete local signed auth bootstrap
- the browser can move from static mock state into a real loopback session model

### 2. Local agent discovery and ACP sessions

Available backend surfaces:

- `GET /v1/discovery/local-agents`
- `GET /v1/discovery/local-agents/managed`
- `GET /v1/discovery/local-agents/acp-sessions`
- `POST /v1/discovery/local-agents/register`
- `POST /v1/discovery/local-agents/start`
- `POST /v1/discovery/local-agents/stop`
- `POST /v1/discovery/local-agents/acp-session/open`
- `POST /v1/discovery/local-agents/acp-session/close`
- `POST /v1/discovery/local-agents/acp-session/initialize`
- `POST /v1/discovery/local-agents/acp-session/poll`
- `POST /v1/discovery/local-agents/acp-session/task-request`
- `POST /v1/discovery/local-agents/acp-session/apply-task-result`

Front-end implication:

- the current fake radar panel should become a real local-agent discovery console
- discovered GitHub Copilot CLI / Claude Code CLI / VS Code agents can be surfaced as real inventory
- ACP session lifecycle can be presented as inspectable terminal turns rather than hidden transport state

### 3. Task dispatch and workflow execution

Available backend surfaces:

- `GET /v1/tasks`
- `POST /v1/tasks`
- `POST /v1/tasks/dispatch`
- `GET /v1/tasks/dispatch/preview`
- `POST /v1/tasks/dispatch/evaluate`
- `POST /v1/tasks/claim`
- `POST /v1/tasks/lease/renew`
- `POST /v1/tasks/ack`
- `POST /v1/tasks/requeue`
- `GET /v1/tasks/replay-inspect`
- `GET /v1/workflows`
- `GET /v1/workflows/summary`
- `POST /v1/workflows/fanout`
- `POST /v1/workflows/merge`
- `POST /v1/workflows/finalize`
- `POST /v1/workflow/execute`

Front-end implication:

- the workspace can move from a decorative terminal into a real task composer
- dispatch preview can become an operator-facing routing explainer
- workflow state can be rendered as an ASCII branch tree and merge/review graph
- replay-inspect can power an evidence drawer for receipts, audits, and delivery history

### 4. Runtime and integration binding

Available backend surfaces:

- `GET /v1/runtimes`
- `POST /v1/runtimes/bind`
- `POST /v1/integrations/openclaw/bind`
- `POST /v1/integrations/claude-code/bind`
- `POST /v1/integrations/claude-http/bind`
- `POST /v1/integrations/claude-http/follow-up-bind`
- `POST /v1/integrations/claude-http/follow-up-from-tool-task`
- `POST /v1/integrations/claude-http/tool-fanout`

Front-end implication:

- a runtime binding drawer is now justified
- users should be able to inspect supported runtime features before binding
- follow-up and tool-fanout flows can be visualized as nested execution frames

### 5. Governance, trust, and delivery observability

Available backend surfaces:

- `GET /v1/disputes`
- `POST /v1/disputes`
- `POST /v1/disputes/resolve`
- `POST /v1/disputes/vote`
- `GET /v1/reputation`
- `GET /v1/poaw/events`
- `GET /v1/poaw/summary`
- `GET /v1/violations`
- `GET /v1/quarantines`
- `POST /v1/quarantines`
- `POST /v1/quarantines/release`
- `GET /v1/governance-actions`
- `GET /v1/audits`
- `GET /v1/peer-health`
- `GET /v1/outbox`
- `GET /v1/outbox/dead-letter`
- `POST /v1/outbox/flush`
- `POST /v1/outbox/requeue`

Front-end implication:

- the front-end can support a real operator console
- disputes, score events, and violations can become inspectable governance panels
- peer health and outbox state can become transport diagnostics
- this should remain visually terminal-native, not enterprise-table-first

### 6. Payments and settlement workflows

Available backend surfaces:

- `GET /v1/payments/receipts/status`
- `GET /v1/payments/receipts/onchain-relays`
- `GET /v1/payments/receipts/onchain-relays/latest`
- `GET /v1/payments/receipts/onchain-relays/latest-failed`
- `GET /v1/payments/receipts/onchain-relay-queue`
- `GET /v1/payments/receipts/onchain-relay-queue/summary`
- `GET /v1/payments/ops/summary`
- `POST /v1/payments/receipts/issue`
- `POST /v1/payments/receipts/introspect`
- `POST /v1/payments/receipts/onchain-proof`
- `POST /v1/payments/receipts/onchain-rpc-plan`
- `POST /v1/payments/receipts/onchain-raw-bundle`
- `POST /v1/payments/receipts/onchain-relay`
- `POST /v1/payments/receipts/onchain-relay-queue`
- `POST /v1/payments/receipts/onchain-relay-queue/pause`
- `POST /v1/payments/receipts/onchain-relay-queue/resume`
- `POST /v1/payments/receipts/onchain-relay-queue/requeue`
- `POST /v1/payments/receipts/onchain-relay-queue/cancel`
- `POST /v1/payments/receipts/onchain-relay-queue/delete`
- `POST /v1/payments/receipts/onchain-relay-queue/auto-requeue/disable`
- `POST /v1/payments/receipts/onchain-relay-queue/auto-requeue/enable`
- `POST /v1/payments/receipts/onchain-relay/replay-helper`
- `GET /v1/onchain/status`
- `GET /v1/onchain/settlement-preview`
- `GET /v1/onchain/settlement-ledger`
- `GET /v1/onchain/settlement-relays`
- `GET /v1/onchain/settlement-relay-queue`
- `GET /v1/onchain/settlement-relays/latest`
- `POST /v1/onchain/intents/build`
- `POST /v1/onchain/rpc-payload`
- `POST /v1/onchain/rpc-plan`
- `POST /v1/onchain/rpc/send-raw`
- `POST /v1/onchain/settlement-rpc-plan`
- `POST /v1/onchain/settlement-raw-bundle`
- `POST /v1/onchain/settlement-relay`
- `POST /v1/onchain/settlement-relay-queue`
- `POST /v1/onchain/settlement-relay-queue/pause`
- `POST /v1/onchain/settlement-relay-queue/resume`
- `POST /v1/onchain/settlement-relay-queue/requeue`
- `POST /v1/onchain/settlement-relay-queue/cancel`
- `POST /v1/onchain/settlement-relay-queue/delete`
- `POST /v1/onchain/settlement-relays/reconcile`
- `POST /v1/onchain/settlement-relays/replay`

Front-end implication:

- there is enough backend surface to justify a full payment + settlement operations section
- the UI should expose queue state, latest relay status, and replay / reconcile actions
- because the visual system is ASCII-first, these should read like chain control panels rather than wallet popups

## Frontend Work Packages

### Package A. Local-first boot and daemon attach

Deliverables:

- landing page `Use AgentCoin` transitions into real localhost attach flow
- daemon detection against `GET /healthz`
- local manifest fetch against `GET /v1/manifest`
- auth challenge + verify flow using `/v1/auth/challenge` and `/v1/auth/verify`
- explicit fallback states: daemon not running, auth denied, loopback unavailable

UI form:

- ASCII boot log
- loopback status panel
- signed-session banner

Priority:

- highest

### Package B. Real local-agent discovery panel

Deliverables:

- replace mock discovery data with `/v1/discovery/local-agents`
- show discovered local tools and IDE agents
- add managed local-agent registration / start / stop actions
- add ACP session list and status surface

UI form:

- radar stays as decorative discovery metaphor
- actual result list rendered as ASCII inventory cards
- session state rendered as turn-by-turn console transcript

Priority:

- highest

### Package C. Task composer and dispatch preview

Deliverables:

- task creation form bound to `POST /v1/tasks`
- dispatch preview bound to `GET /v1/tasks/dispatch/preview`
- semantic dispatch evaluation bound to `POST /v1/tasks/dispatch/evaluate`
- dispatch submit action bound to `POST /v1/tasks/dispatch`

UI form:

- left panel: task envelope editor
- right panel: dispatch score breakdown
- bottom strip: selected runtime / bridge / target peer

Priority:

- high

### Package D. Workflow graph and replay drawer

Deliverables:

- workflow summary viewer using `/v1/workflows` and `/v1/workflows/summary`
- fanout / merge / finalize controls
- replay-inspect drawer with receipts, audits, and proof bundles

UI form:

- ASCII branch tree
- merge gate indicators
- receipt viewer as stacked terminal frames

Priority:

- high

### Package E. Governance and trust console

Deliverables:

- dispute list and dispute detail viewer
- vote / resolve actions where permitted
- reputation, PoAW, violations, quarantine, governance-action panels
- peer-health and outbox diagnostics

UI form:

- monochrome control board
- severity-coded but still palette-constrained
- no generic admin dashboard cards

Priority:

- high

### Package F. Payment and settlement operations

Deliverables:

- payment receipt issue / introspection flows
- payment relay queue board
- settlement preview and settlement ledger inspector
- relay reconcile / replay / pause / resume / requeue actions

UI form:

- chain-ops HUD
- queue timeline with terminal statuses
- signed receipt and tx bundle inspector

Priority:

- medium-high

### Package G. Git and audit surfaces

Deliverables:

- Git status and diff inspection using `/v1/git/status` and `/v1/git/diff`
- task context attachment and branch creation actions later
- audit explorer bound to `/v1/audits`

UI form:

- ASCII diff viewer
- proof sidebar
- task-linked repository context strip

Priority:

- medium

## Design System Rules

The next front-end phase should preserve these rules.

### ASCII style rules

- keep monospace as the structural type system
- favor framed panels, scanlines, border glows, and HUD labels over modern app cards
- use transparency and glow sparingly to enhance focus, not to soften everything
- preserve black-first composition with white-dominant contrast
- render workflow and transport state in terminal metaphors before switching to tables

### Multilingual rules

- every user-facing label must ship in `zh`, `en`, and `ja` together
- never introduce mixed-language headers inside a localized page
- prefer locale-specific section titles rather than hard-coded English HUD labels
- keep long manifesto text semantically aligned across locales, not word-for-word if readability suffers
- all new front-end modules should define translation keys up front before UI implementation

### Interaction rules

- loading should feel like console progression, not skeleton shimmer
- errors should be explicit and operator-readable
- long-running background state should expose terminal-like statuses such as `queued`, `running`, `retrying`, `confirmed`, `dead-letter`
- every destructive or governance-sensitive action should show both receipt context and scope context

## Windowed Workbench Specification

The next workspace iteration should stop growing as a single terminal-plus-sidebar page.
It should become a documentation-first windowed workbench with a stable shell and explicit window roles.

### Documentation-first rule

Before layout or state refactors begin, the frontend must first document:

- the shell layout and window taxonomy
- the ownership of existing state, handlers, and panels
- the localization inventory for every new label and status string
- the alerting model and severity surfaces

Code should follow the written spec, not invent a new structure mid-refactor.

The current ownership baseline for `web/src/app/[locale]/page.tsx` is documented in [frontend-window-ownership-map.md](C:/Users/Twist/Desktop/agentcoin/docs/project/frontend-window-ownership-map.md).

### Shell layout

The steady-state workspace shell should use:

- a left-side `window rail` for creation, switching, and minimal state badges
- a single `active workspace area` in the center
- a bottom `status line` for global state, locale, theme, connectivity, task counts, and highest-priority alerts

The persistent top header should be removed once the shell is implemented.
Global status should move into the bottom line instead of taking vertical space away from the active window.

### Window taxonomy

The workbench should standardize on these window types:

#### 1. Compose Window

Purpose:

- default entry window
- multimodal input and attachment management
- target-agent selection
- task dispatch and result streaming

Must not become a node-control form or payment detail inspector.

#### 2. Agent Session Window

Purpose:

- one window per agent session
- persistent single-agent context
- direct follow-up tasks, outputs, and artifacts

#### 3. Swarm Window

Purpose:

- multi-agent orchestration
- agent assignment, stage tracking, aggregation, and merge output

#### 4. Node Window

Purpose:

- local node attach
- discovery
- managed-agent lifecycle
- ACP runtime inspection and control

#### 5. Wallet Window

Purpose:

- payment receipts
- renter tokens
- usage summaries
- reconciliation and payment-required handling

#### 6. Community Window

Purpose:

- remote peers
- trust state
- channels / feed / collaboration entry points

### Window ownership rules

- Compose owns creative task input.
- Agent Session owns single-agent work.
- Swarm owns multi-agent collaboration.
- Node owns local runtime and transport control.
- Wallet owns payment and settlement detail.
- Community owns peers and social / network collaboration.

Do not re-collapse these domains back into one long right-side inspector.

## Localization Purity Rules

The selected locale must fully control interface language.

### Required rules

- if the user selects `zh`, all interface labels, statuses, actions, errors, notices, and summaries must render in Chinese
- if the user selects `en`, they must render in English
- if the user selects `ja`, they must render in Japanese
- proprietary names, protocol names, product names, and explicit external identifiers may remain in their canonical form

### Forbidden patterns

- mixed-language HUD labels inside one localized surface
- English fallback strings embedded in otherwise localized windows
- error messages that mix English severity prefixes with non-English body copy unless the prefix itself is a product or protocol term

This rule applies equally to:

- titles
- buttons
- empty states
- warnings
- errors
- status lines
- modal copy
- task and payment summaries

## Visual Constraints For Windowed UI

The windowed workbench should inherit the landing page's visual system rather than falling back to a generic app dashboard.

### Required visual language

- black-first composition
- fine framed borders
- terminal-native HUD labels
- restrained glow and transparency
- monochrome hierarchy with selective accent only where required

### White brightness hierarchy

Do not render all text at one brightness level.
Use a deliberate ladder instead:

- headline / active title: brightest white
- primary action labels and active status: high white
- body text and normal data: medium white
- metadata, hints, and passive labels: low white

This hierarchy should be visible across every window so dense screens remain legible.

### Preserved ASCII visual assets

The existing AI ASCII / pixel-art agent icons are protected visual assets.

- they may be moved into the window rail, window headers, empty states, or session covers
- they may be resized or reorganized
- they must not be removed or replaced with generic placeholder icons

## Unified Alerting Model

The current frontend already has multiple error sources, but many are only shown as small red text or appended to terminal history.
The windowed workbench must replace that with a structured alert system.

### Severity levels

#### Info

- task queued
- sync completed
- discovery completed

#### Warning

- node offline
- trust review pending
- reconciliation stale
- agent latency degraded

#### Error

- attach failed
- multimodal dispatch failed
- peer sync failed
- ACP action failed

#### Critical

- auth failed
- security validation failed
- invalid loopback endpoint
- payment required before execution

### Alert surfaces

Every alert should be routed to one or more explicit surfaces:

1. bottom status line summary
2. window-rail badge or marker
3. active-window alert banner
4. blocking confirmation / interruption layer for critical conditions

### Alerting rules

- do not rely on tiny red inline text as the only error signal
- do not bury operational failures only inside terminal history
- every actionable error should expose a next action such as retry, inspect, re-auth, open wallet, or switch window
- alert copy must obey the same locale-purity rules as the rest of the UI

## Windowed Delivery Sequence

The frontend should be refactored in this order.

### Phase 0. Documentation-first shell spec

Ship first:

- a written shell layout
- window ownership mapping for existing state and handlers
- locale-string inventory for all new window surfaces
- alert severity and routing inventory

Why first:

- it prevents the refactor from drifting into ad-hoc panel rewrites

### Phase 1. Workbench shell + Compose / Node split

Ship next:

- left window rail
- center active-window area
- bottom status line
- Compose Window
- Node Window

Why next:

- it converts the current page into a stable shell while preserving the shortest path to useful work

### Phase 2. Agent Session Window

Ship next:

- dedicated single-agent windows
- per-agent task continuity
- window-aware session alerts

Why next:

- it is the cleanest bridge from a single composer to persistent agent workspaces

### Phase 3. Swarm Window

Ship next:

- multi-agent task orchestration
- role assignment and aggregation
- stage-aware alerting

Why next:

- it unlocks the collaborative differentiator without overloading the Compose window

### Phase 4. Wallet + Community windows

Ship after that:

- payment and settlement control surfaces
- peer, trust, and collaboration surfaces

Why later:

- these are high-value expansions, but they should not block the shell and task-model transition

## Recommended Delivery Phases

### Phase 1. Local attach and real discovery

Ship first:

- localhost daemon detection
- auth bootstrap
- manifest fetch
- real local-agent discovery
- managed local-agent inventory

Why first:

- it converts the current front-end from concept demo into a real local-first client

### Phase 2. Task composer and dispatch preview

Ship next:

- task creation
- dispatch preview
- runtime binding surface
- task list and status polling

Why next:

- this is the shortest path from front-end UI to actual useful work

### Phase 3. Workflow replay and governance

Ship next:

- workflow summary
- replay-inspect drawer
- disputes and PoAW panels
- peer-health and outbox diagnostics

Why next:

- this exposes the system's differentiator: verifiable coordination rather than plain prompt submission

### Phase 4. Payments and settlement operations

Ship after that:

- payment receipt workflows
- relay queue operations
- settlement preview / ledger / reconcile tooling

Why later:

- these surfaces are richer and more operator-oriented, but the backend is already far enough along to justify them

## Immediate Frontend Tasks

1. Freeze the windowed workbench specification, locale-purity rules, ASCII asset-preservation rules, and alert severity model before UI refactoring.
2. Map current `page.tsx` state, effects, handlers, and panels into Compose / Agent Session / Swarm / Node / Wallet / Community ownership.
3. Replace mock local discovery with real `/v1/discovery/local-agents` integration.
4. Add localhost daemon attach and signed auth bootstrap using `/v1/healthz`, `/v1/manifest`, `/v1/auth/challenge`, and `/v1/auth/verify`.
5. Replace decorative terminal command responses with real task and node reads.
6. Add a translation-key checklist for every new window before UI coding begins.
7. Create a shared HUD component set for panel frame, ASCII section title, live status strip, alert banner, and terminal receipt view.
8. Keep [frontend-window-ownership-map.md](C:/Users/Twist/Desktop/agentcoin/docs/project/frontend-window-ownership-map.md) updated as state and handlers are extracted from `page.tsx`.

## Non-goals For The Next Slice

Do not spend the next slice on:

- generic marketing-site polish detached from node capability
- dark/light visual divergence that breaks the ASCII console identity
- introducing mixed-language UI shortcuts
- overbuilding charts before replay, receipts, and queue status are visible

## Result

If the front-end follows this plan, AgentCoin will stop looking like a themed mock terminal and start behaving like a real multilingual sovereign console for local agent discovery, cross-agent coordination, workflow governance, and settlement operations.
