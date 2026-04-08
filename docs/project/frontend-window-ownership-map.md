# AgentCoin Frontend Window Ownership Map

## Purpose

This document maps the current monolithic workspace in `web/src/app/[locale]/page.tsx` into the target windowed ASCII workbench.

It exists to answer four questions before code refactoring begins:

- which state belongs to which future window
- which effects belong to landing, shell, or a specific window
- which handlers should be moved together during extraction
- which current UI blocks are temporary, transitional, or should be retired

This document should be updated before major shell or window refactors.

## Source Baseline

Current source of truth:

- `web/src/app/[locale]/page.tsx`

Primary target shell:

- `window rail`
- `active workspace area`
- `bottom status line`

Primary target windows:

- `Compose Window`
- `Agent Session Window`
- `Swarm Window`
- `Node Window`
- `Wallet Window`
- `Community Window`

## Hard Constraints To Preserve

- the selected locale must fully control all UI copy except true proper nouns, protocol names, and product names
- AI ASCII / pixel-art agent icons are protected visual assets and may be moved but not removed
- workspace windows should inherit the landing page's black-first terminal look and layered white brightness hierarchy
- error and warning states must be visually prominent, not reduced to tiny inline red text or buried logs

## Shell Ownership

These states and interactions should belong to the future shell, not to a single feature window.

### Shell state

- `mounted`
- `theme` / `setTheme`
- `locale`
- `router`
- `pathname`

### Shell responsibilities

- locale switching
- theme switching
- active window routing
- bottom status line aggregation
- alert summary routing

### Shell migration note

The current top header should be removed after the shell is implemented.
Its data should be redistributed to:

- the window rail
- the active window header
- the bottom status line

## Landing-only Ownership

These states and effects belong only to the landing layer and should not leak into the steady-state workspace shell.

### Landing state / refs

- `showLanding`
- `landingStep`
- `typedVision`
- `earthDisplay`
- `earthAngleRef`
- `asciiCanvasRef`
- `landingScrollRef`
- `startedRun`
- `showLandingRef`
- `bufferedBootHistoryRef`
- `bootOnlinePendingRef`
- `bootOnlineTimerRef`

### Landing effects

- landing boot history staging
- landing backdrop canvas animation
- landing typing progression
- landing auto-scroll behavior

### Landing UI blocks

- full-screen intro shell
- Earth ASCII sphere
- manifesto typing panel
- `Initialize Workspace` transition button

### Landing migration note

Landing should stay as a separate scene, not a special case inside the future workspace window system.

## Compose Window Ownership

Compose is the default creative task window.
It should own multimodal drafting, attachments, target selection, dispatch, and result flow.

### Current state that should move into Compose

- `history`
- `input`
- `inputRef`
- `localMultimodalPrompt`
- `localMultimodalKind`
- `localMultimodalAttachments`
- `localMultimodalError`
- `localMultimodalNotice`

### Current handlers that should move into Compose

- `handleEnter`
- `handleMultimodalFilesSelected`
- `handleDispatchMultimodalTask`

### Current UI blocks that should become Compose

- current terminal input / output area
- current multimodal form block
- current multimodal attachment gallery
- current dispatch success / failure feedback that is now split between inline state and terminal history

### Compose migration note

The current terminal area should not survive as a decorative shell emulator.
It should become a task composer plus execution feed.

## Agent Session Window Ownership

Agent Session is not yet a first-class window in the current page, but existing data already suggests its future shape.

### Existing source material for Agent Session

- `agents`
- `localTasks`
- `history` entries related to single-agent responses
- task media helpers and task result summaries

### Future ownership

- one live session per selected agent
- direct follow-up interaction with a single target agent
- per-agent artifact list and result stream
- per-agent connection and latency state

### Agent session migration note

The current AI agent cards should be repurposed into session identity assets for the window rail and session headers.
They should not remain as a passive showcase block.

## Swarm Window Ownership

Swarm should own multi-agent orchestration rather than hiding that flow inside a modal.

### Current state and handlers that point toward Swarm

- `showWorkflowModal`
- `handleWorkflowExecute`
- `localMultimodalKind` when used as target-routing context
- `localTasks` as shared task/result inventory

### Current UI blocks that should become Swarm

- current workflow modal
- workflow execution prompt and target selector
- future multi-agent assignment and aggregation controls

### Swarm migration note

The current workflow modal is a transitional implementation.
It should be replaced with a dedicated window, not expanded into a larger modal.

## Node Window Ownership

Node should own local runtime control, discovery, managed agents, and ACP lifecycle.

### Current state that should move into Node

- `localNodeEndpoint`
- `localNodeToken`
- `localNodeBusy`
- `localNodeOnline`
- `localNodeError`
- `localStatus`
- `localManifest`
- `localChallengeReady`
- `localAttachReady`
- `localDiscoveryBusy`
- `localDiscoveryItems`
- `isDiscovering`
- `scanComplete`
- `radarDisplay`
- `radarAngleRef`
- `foundAgents`
- `checkedToJoin`
- `localManagedRegistrations`
- `localAcpSessions`
- `localAcpBoundary`
- `localSessionTaskInputs`
- `localRuntimeBusy`
- `localRuntimeError`
- `localActionBusyKey`
- `localProbeStartedRef`

### Current effects that should move into Node

- deferred local probe after landing
- discovery radar animation effect
- ACP session input normalization effect

### Current handlers that should move into Node

- `probeLocalNode`
- `fetchLocalDiscoveryItems`
- `fetchLocalAgentRuntimeState`
- `refreshLocalRuntimeState`
- `postLocalAction`
- `handleAttachLocalNode`
- `handleDiscoverAgents`
- `handleRegisterDiscoveredAgent`
- `handleRegisterSelectedAgents`
- `handleStartRegistration`
- `handleStopRegistration`
- `handleOpenAcpSession`
- `handleCloseAcpSession`
- `handleInitializeAcpSession`
- `handlePollAcpSession`
- `handleSendAcpTaskRequest`
- `handleApplyAcpTaskResult`

### Current UI blocks that should become Node

- local node attach box
- local discovery results and radar pass
- managed local-agent list
- ACP session list and ACP control panel

### Node migration note

Node should become its own window instead of occupying the top of a long right-side stack.

## Wallet Window Ownership

Wallet should own payment and settlement state, not remain sprinkled through node and workflow views.

### Current state that should move into Wallet

- `paymentOpsSummary`
- `serviceUsageSummary`
- `serviceUsageReconciliation`
- `renterTokenSummary`

### Current handlers that should move into Wallet

- `fetchPaymentAndServiceState`
- `handleRenterTokenOperations`
- `handleReceiptOperations`

### Cross-window dependency

- `handleWorkflowExecute` currently contains payment-required branching and should eventually delegate payment interruption handling into Wallet

### Wallet migration note

Payment-required execution should open or highlight Wallet instead of surfacing as an isolated inline or modal-side error.

## Community Window Ownership

Community should own peers, trust state, sync, and collaboration-facing network context.

### Current state that should move into Community

- `remotePeers`
- `remotePeerCards`
- `remotePeerHealth`
- `remotePeersBusy`
- `remotePeersError`
- `remotePeerSyncBusy`
- `isAddingRemote`
- `isAddingRemotePanel`
- `connectAnimFrame`
- `remoteForm`

### Current effects that should move into Community

- add-remote animation effect

### Current handlers that should move into Community

- `fetchRemotePeerState`
- `handleRefreshRemotePeers`
- `handleSyncRemotePeers`

### Current UI blocks that should become Community

- add remote panel
- remote peer summary panel
- future peer feed, invite, trust-review, and collaboration actions

### Community migration note

Remote peers should stop sharing a single panel with local runtime controls.

## Transitional Or Shared Elements

Some current elements do not yet have a final home and should be treated as transitional.

### Transitional demo state

- `mockQueue`
- `isOnline`
- parts of `history` currently used as decorative command output

### Transitional demo effects

- mock relay queue interval
- fake latency updates for static agent cards

### Recommendation

These should either:

- move into a lightweight shell-level demo layer temporarily
- be replaced by real backend state
- or be removed once the windowed workbench is functional

## Current UI Block To Window Mapping

| Current block in `page.tsx` | Future owner |
| --- | --- |
| landing intro scene | landing-only scene |
| top header with theme / language / status | shell bottom status line + window rail metadata |
| terminal area | Compose Window |
| command input row | Compose Window |
| local node attach box | Node Window |
| local discovery radar and found-agent list | Node Window |
| local discovered agents list | Node Window |
| multimodal form and attachment gallery | Compose Window |
| managed runtime list | Node Window |
| ACP session inspector and controls | Node Window first, then partial Agent Session extraction later |
| remote peers panel | Community Window |
| workflow modal | Swarm Window |
| clear hint footer | shell help / status line |

## Mixed-language Cleanup Inventory

The current file still contains hard-coded mixed-language or English-first strings that must be externalized before or during the window refactor.

Examples include:

- hard-coded node / network error prefixes
- service and payment summary labels
- workflow modal fallback copy
- inline `ERR:` presentation

These should all move into locale-bound translation keys before the corresponding window is considered complete.

## Alert Routing Inventory

The window refactor should not preserve the current pattern where many failures are only shown as small inline red text or terminal history entries.

### Required routing

- shell status line: highest-severity active alert summary
- window rail: per-window alert marker
- active window header: visible alert banner
- blocking overlay: critical failures such as auth, security validation, invalid endpoint, or payment-required interruption

### Existing state sources that must feed the alert system

- `localNodeError`
- `localRuntimeError`
- `remotePeersError`
- `localMultimodalError`
- payment-required exceptions from workflow execution
- security and auth failures from local auth and local action helpers

## Recommended Refactor Sequence From Current File

1. Extract landing-only scene concerns from workspace concerns.
2. Introduce shell state and window identifiers without moving all business logic at once.
3. Move Compose state and UI out of the right-side stack and into the central active area.
4. Move Node runtime state and UI into a dedicated Node window.
5. Move remote peer state and UI into a dedicated Community window.
6. Replace the workflow modal with a Swarm window.
7. Split payment state and actions into a Wallet window.
8. Replace demo shell state with real backend-driven state where possible.

## Definition Of Done For The First Real Windowed Slice

The first windowed slice should be considered complete only if:

- the header is no longer the primary global status container
- the shell exposes a real window rail
- Compose and Node are separate active-window surfaces
- locale purity is maintained for new UI copy
- AI ASCII agent icons are preserved and reused
- alerting is upgraded beyond inline red text and history-only failures
