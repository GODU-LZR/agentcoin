# Blueprint Continuous Improvement Master Checklist

This document is the long-horizon execution checklist for closing the gap between the AgentCoin blueprint and the current executable MVP.

It is intentionally broader than the current implementation roadmap. The roadmap tracks landed engineering phases. This document tracks the larger blueprint-convergence program, including architecture, protocol, economics, governance, execution security, deployment, testing, and documentation.

## Purpose

- Keep long-running implementation work independent from chat history.
- Translate blueprint concepts into concrete, checkable engineering tasks.
- Separate already-landed MVP primitives from still-missing blueprint layers.
- Provide a durable queue for autonomous execution bursts.
- Make it easy to pick the next high-value task without re-discovering context.

## Source Documents

- docs/whitepaper/en.md
- docs/project/overview.md
- docs/architecture/mvp.md
- docs/architecture/alignment-gap.md
- docs/architecture/onchain-roadmap.md
- docs/architecture/implementation-roadmap.md
- docs/testing/strategy.md

## Status Legend

- [x] landed in the current repository
- [~] partially implemented or actively being hardened
- [ ] not started or still concept-only

## Program Rules

- [ ] Keep public APIs additive unless a breaking change is explicitly justified.
- [ ] Prefer narrow, verifiable increments over wide speculative rewrites.
- [ ] Always connect blueprint concepts to a concrete runtime or document artifact.
- [ ] For each security feature, define both trust assumptions and downgrade behavior.
- [ ] For each economic feature, define both off-chain and on-chain authority boundaries.
- [ ] For each governance feature, define operator path, audit path, and replay path.
- [ ] For each bridge or adapter, define import, execution, export, and failure semantics.
- [ ] For each persistent mutation path, define preview, apply, persist, and rollback behavior.
- [ ] For each deployment shape, define minimum smoke tests and expected operator commands.
- [ ] Keep multilingual docs aligned once a workstream materially changes user-facing behavior.

## Current Baseline Snapshot

- [x] Durable task queue with lease, retry, and dead-letter semantics exists.
- [x] Durable outbox, inbox dedupe, and delivery ACK flow exists.
- [x] Workflow fanout, merge, review-gate, and finalize primitives exist.
- [x] Git-aware task context and proof bundle propagation exist.
- [x] Local reputation, violation tracking, quarantine, and governance-action log exist.
- [x] Signed cards, envelopes, and receipts exist with HMAC and SSH identity paths.
- [x] SSH staged rotation, explicit revocation, drift reporting, operator apply, and optional config persistence now exist.
- [x] Runtime adapters exist for http-json, langgraph-http, container-job skeleton, openai-chat, ollama-chat, and cli-json.
- [x] Bridge skeleton exists for MCP and A2A import-export normalization.
- [x] Settlement relay queue, replay, reconciliation, and local ledger projection exist.
- [x] Headscale overlay examples and local multi-node compose demo exist.
- [x] Cross-platform unittest and CI baseline exists.

## Track 1: Identity And Trust Chain

- [~] Stabilize SSH identity rotation, revocation, drift reporting, operator apply, and config reconciliation.
- [ ] Add public-key request signing for sensitive operator APIs beyond bearer token only.
- [ ] Add signed peer-to-peer request authentication separate from payload signatures.
- [ ] Define trust-bootstrap states for unknown, observed, pending, approved, rejected, and revoked keys.
- [ ] Add multi-step approval workflow for high-risk trust updates.
- [ ] Add quorum-based trust approval policy for federated deployments.
- [ ] Add expiration timestamps for staged replacement keys.
- [ ] Add trust-update intent receipts separate from trust-update apply receipts.
- [ ] Add trust-update rollback and rollback receipt flow.
- [ ] Add trust-source classification: manual, observed, imported, chain-derived, committee-approved.
- [ ] Add reason codes for every trust mutation.
- [ ] Add trust chain replay view in replay-inspect or a dedicated peer-trust endpoint.
- [ ] Add peer identity timeline endpoint with before and after snapshots.
- [x] Add trust drift severity ranking so operators can prioritize urgent mismatches.
- [ ] Add local policy for rejecting peers that advertise keys conflicting with explicit revocation.
- [ ] Add trust policy for principal mismatch severity and default action.
- [ ] Add trust policy for stale trusted keys retained too long after rotation.
- [x] Add dry-run preview for trust apply and config persistence.
- [x] Add trust diff rendering as unified diff for operator review.
- [ ] Add persisted trust change history export for external audit.
- [ ] Add signed trust snapshots for cross-node audit exchange.
- [ ] Add optional chain-anchored identity proofs once DID binding is live.

## Track 2: Capability Semantics And Ontology

- [~] Keep lightweight semantics aligned with blueprint terms.
- [ ] Expand capability schema into a more formal controlled vocabulary.
- [ ] Define role taxonomy for planner, worker, reviewer, aggregator, committee-member, evaluator, and operator.
- [ ] Define task-type vocabulary for code, review, summarize, retrieve, judge, execute, deploy, and settle.
- [ ] Define evidence vocabulary for deterministic receipts, review receipts, challenge receipts, and settlement receipts.
- [ ] Define policy vocabulary for runtime, tool, network, sandbox, and merge constraints.
- [ ] Define trust vocabulary for runtime trust, evidence trust, reputation trust, and economic trust.
- [ ] Add schema version negotiation between peers.
- [ ] Add semantic compatibility negotiation for required capabilities.
- [ ] Add semantic incompatibility explanations in dispatch evaluation.
- [ ] Add richer machine-readable capability aliasing and implications.
- [ ] Add optional JSON-LD expansion or normalization tooling for docs and tests.
- [ ] Add semantic examples for multi-step workflows, disputes, and settlement.
- [ ] Add schema linting checks for capability and receipt examples.
- [ ] Add interoperability fixtures proving semantic compatibility across bridge inputs.
- [ ] Add formal vocabulary docs for human and AI reviewers.
- [ ] Add vocabulary docs for policy-rejected outcomes and quarantine causes.
- [ ] Add vocabulary docs for chain settlement outcomes.

## Track 3: Peer Discovery, Registry, And Routing

- [ ] Add richer peer metadata for pricing hints, trust class, policy envelope, and runtime quality hints.
- [ ] Add peer registry cache invalidation rules.
- [ ] Add peer-card freshness policy and staleness penalties.
- [ ] Add leader-election scoring beyond static role and capability matching.
- [ ] Add routing preference for trust domains and administrative boundaries.
- [ ] Add routing preference for locality, overlay reachability, and latency class.
- [ ] Add routing rejection reason transparency in dispatch scoring.
- [ ] Add route simulation endpoint for a full workflow, not just one task.
- [ ] Add peer-card signing policy stricter than current best-effort verification.
- [ ] Add peer-card mismatch warnings for overlay endpoint versus origin URL.
- [ ] Add operator endpoint to quarantine or disable a peer from routing without deleting trust config.
- [ ] Add peer disable reasons and audit trail.
- [ ] Add discovery import or static-registry sync format for larger federations.
- [ ] Add cold-start discovery guidance for bootstrap peers.

## Track 4: Swarm Orchestration And Workflow Governance

- [ ] Add richer planner decomposition receipts.
- [ ] Add workflow checkpoint documents beyond task-level persistence.
- [ ] Add resumable workflow coordinator handoff if planner node fails.
- [ ] Add planner lease or soft leadership semantics.
- [ ] Add branch-specific resource or trust constraints.
- [ ] Add review-chain policy beyond simple approval counts.
- [ ] Add reviewer disagreement handling and escalation states.
- [ ] Add merge conflict representation for non-Git workflows.
- [ ] Add workflow cancellation, abort, and pause semantics.
- [ ] Add operator override for blocked workflows with governance receipt.
- [ ] Add workflow SLA or timeout policy fields.
- [ ] Add partial completion states for long-running branches.
- [ ] Add aggregate-result receipts for multi-worker workflows.
- [ ] Add committee review path for disputed merge or workflow outcomes.
- [ ] Add orchestration metrics for decomposition quality and branch waste.
- [ ] Add DAG visualization export for workflow summaries.
- [ ] Add workflow archive and compaction policy for long-lived nodes.

## Track 5: Runtime Adapters And Secure Execution

- [~] Keep existing runtime adapter layer stable while increasing execution realism.
- [ ] Turn container-job from skeleton into a real engine integration layer.
- [ ] Add runtime-level stdout and stderr capture policy by adapter.
- [ ] Add runtime timeout budget and retry policy per adapter kind.
- [ ] Add runtime environment variable allowlist support.
- [ ] Add adapter-side secret injection policy without exposing plaintext in task payloads.
- [ ] Add execution sandbox profile selection.
- [ ] Add filesystem scope restrictions and audited mounts.
- [ ] Add outbound host allowlist enforcement across runtime adapters.
- [ ] Add execution evidence bundle for adapter runs.
- [ ] Add deterministic replay metadata where adapter behavior allows it.
- [ ] Add non-deterministic execution disclaimers where replay cannot be strict.
- [ ] Add container image trust policy and digest pinning.
- [ ] Add adapter health probes and readiness descriptors to runtime capabilities.
- [ ] Add structured error taxonomy across adapters.
- [ ] Add operator-facing execution kill or cancel path.
- [ ] Add adapter policy inheritance between node config and task payload.
- [ ] Add adapter plugin registration model for third-party runtimes.
- [ ] Add secure temporary artifact cleanup policy.
- [ ] Add attestation placeholder model for future TEE integration.

## Track 6: Protocol Bridges And Interoperability

- [~] Keep MCP and A2A skeleton behavior aligned with evolving task model.
- [ ] Expand MCP bridge to fuller tool-call lifecycle coverage.
- [ ] Expand MCP bridge to resource listing and schema propagation.
- [ ] Expand MCP bridge error propagation and partial-result handling.
- [ ] Expand A2A bridge to richer conversation state mapping.
- [ ] Add bridge capabilities advertisement in peer cards.
- [ ] Add bridge policy restrictions per peer and per task.
- [ ] Add bridge-specific audit records for import and export.
- [ ] Add bridge interoperability fixtures and conformance examples.
- [ ] Add ACP, LACP, or adjacent protocol compatibility research notes.
- [ ] Add protocol bridge version negotiation.
- [ ] Add bridge fallback rules when remote peer lacks required protocol support.
- [ ] Add bridge security guidance for untrusted tool metadata.
- [ ] Add bridge response-size and artifact-size policy.
- [ ] Add bridge-specific retry and dead-letter classification.

## Track 7: Security, AuthN, AuthZ, And Policy Controls

- [ ] Move beyond bearer-token-only write protection.
- [ ] Add request signing for operator endpoints.
- [ ] Add per-endpoint auth policy tiers.
- [ ] Add per-peer auth scopes and least-privilege token model.
- [ ] Add encrypted local secret storage.
- [ ] Add secret rotation guidance and tooling.
- [ ] Add outbound ACL policy with allow, deny, and audit modes.
- [ ] Add policy for local-command subprocess restrictions by task and adapter.
- [ ] Add policy for dangerous file operations and path traversal defense.
- [ ] Add inbound payload size policy by endpoint group.
- [ ] Add policy receipts for denied operator mutations.
- [ ] Add operator role model for read-only, trust-admin, workflow-admin, and settlement-admin.
- [ ] Add auth failure audit trail.
- [ ] Add secure defaults for overlay-exposed deployments.
- [ ] Add formal threat model document for the reference node.
- [ ] Add attack simulation cases for forged peer cards, replay, and trust poisoning.
- [ ] Add stronger execution proof roadmap tied to attestation milestones.

## Track 8: Proof Of Agent Work, Reputation, And Local Economics

- [~] Preserve local PoAW as the off-chain accounting baseline.
- [ ] Define multi-dimensional quality scoring schema beyond current event taxonomy.
- [ ] Add latency penalties and waste penalties from real execution traces.
- [ ] Add sampled re-execution verification hooks.
- [ ] Add cross-check receipts for reviewer consensus.
- [ ] Add reward preview API based on richer scoring inputs.
- [ ] Add separate employer-facing pricing hints from worker reward model.
- [ ] Add stable usage-credit abstraction design doc.
- [ ] Add network trust weighting model tied to governance events.
- [ ] Add spam-cost or anti-abuse scoring rules.
- [ ] Add negative score reasons for forged evidence and policy deception.
- [ ] Add local treasury or settlement bucket abstraction before full chain-native vaults.
- [ ] Add economic event export format for chain anchoring.
- [ ] Add scorebook compatibility layer for future on-chain PoAW contracts.
- [ ] Add replayable score summaries for settlement decisions.

## Track 9: Disputes, Governance, And Committee Evolution

- [~] Preserve current local committee and governance primitives as the control-plane baseline.
- [ ] Add richer dispute evidence schemas and evidence attachment flow.
- [ ] Add challenge window semantics and time-based resolution paths.
- [ ] Add explicit challenger-bond source and custody metadata.
- [ ] Add governance escalation from operator decision to committee decision.
- [ ] Add committee member identity and trust requirements.
- [ ] Add quorum policy presets and rationale docs.
- [ ] Add committee vote receipts with stronger signature semantics.
- [ ] Add governance replay for trust changes, quarantines, disputes, and releases in one consolidated timeline.
- [ ] Add decision explanations and policy citations in governance receipts.
- [ ] Add operator override policy for emergency network isolation.
- [ ] Add governance export package for external auditors.
- [ ] Add governance dashboard payloads for unresolved actions.
- [ ] Add anti-collusion and anti-cartel design notes.

## Track 10: On-Chain Authority And Settlement Migration

- [~] Keep current chain roadmap aligned with local runtime control loops.
- [ ] Finalize deployment and integration workflow for AgentDIDRegistry.
- [ ] Finalize deployment and integration workflow for StakingPool.
- [ ] Finalize deployment and integration workflow for BountyEscrow.
- [ ] Add optional DID binding commands and node config helpers.
- [ ] Add on-chain identity proof references in capability cards.
- [ ] Add worker acceptance path that maps to stake lock.
- [ ] Add task submission path that maps to submissionHash and resultURI.
- [ ] Add reviewer or evaluator path that calls completeJob or rejectJob.
- [ ] Add slash path that maps local dispute resolution into on-chain action.
- [ ] Add settlement result reconciliation back into local governance timeline.
- [ ] Add content-addressed storage strategy for large result bundles.
- [ ] Add resultURI generation helpers and integrity checks.
- [ ] Add explicit chain failure downgrade path so local workflow can survive RPC or chain outages.
- [ ] Add PoAWScorebook integration design.
- [ ] Add ChallengeManager integration design.
- [ ] Add Treasury or SettlementVault design.
- [ ] Add ReputationEventLedger design.
- [ ] Add chain-native committee or DAO-finality research notes.

## Track 11: Deployment, Networking, And Operations

- [~] Preserve loopback, local multi-node, compose, and overlay deployment modes.
- [ ] Automate Docker smoke tests when engine availability is detected.
- [ ] Add Windows-friendly smoke guidance for compose and overlay modes.
- [ ] Add operator guide for Headscale bootstrap and ACL validation.
- [ ] Add node backup and restore guidance for SQLite state.
- [ ] Add peer trust backup and export guidance.
- [ ] Add structured health endpoints for runtime, trust, chain, and bridge subsystems.
- [ ] Add metrics endpoint or metrics export format.
- [ ] Add operator log correlation IDs across workflow, delivery, and settlement.
- [ ] Add event stream export for dashboards.
- [ ] Add database maintenance and compaction guidance.
- [ ] Add production-ish deployment notes for reverse proxy and TLS termination.
- [ ] Add blue-green or rolling restart behavior notes for future multi-node deployments.
- [ ] Add disaster recovery checklist for trust data and governance log recovery.
- [ ] Add network chaos testing playbook.

## Track 12: Testing, CI, And Verification

- [~] Keep current unittest and syntax-check baseline green.
- [x] Add unit coverage for trust preview and config diff helpers.
- [ ] Add unit coverage for trust persistence helper edge cases.
- [x] Add integration coverage for principal-adoption flow.
- [x] Add integration coverage for stale-trusted-key removal flow.
- [x] Add integration coverage for dry-run preview flow.
- [ ] Add integration coverage for config write failure and recovery.
- [ ] Add CLI smoke tests for agentcoin-node and agentcoin-worker.
- [ ] Add Docker smoke tests for compose and multi-node compose.
- [ ] Add structured artifact capture for failing CI integration runs.
- [ ] Add cross-platform verification notes for PowerShell, WSL, Linux, and macOS.
- [ ] Add performance smoke tests for queue scale and relay backlog.
- [ ] Add weak-network chaos tests for partial overlay outages.
- [ ] Add auth failure and malicious input tests for operator endpoints.
- [ ] Add bridge conformance fixture tests.
- [ ] Add on-chain local-mock end-to-end tests for DID, stake, and escrow flow.
- [ ] Add signed governance receipt verification tests across more governance actions.
- [ ] Add reproducible test data fixtures for semantic documents and receipts.

## Track 13: Developer Experience, Tooling, And Packaging

- [ ] Add config patch preview CLI helper for trust updates.
- [ ] Add config linting or validation command.
- [ ] Add sample configs for more deployment profiles.
- [ ] Add richer CLI docs for node, worker, and operator flows.
- [ ] Add package smoke validation for editable and non-editable installs.
- [ ] Add release checklist for Python package and container image publication.
- [ ] Add script or task to bootstrap local multi-node demo faster.
- [ ] Add developer docs for adding a new runtime adapter.
- [ ] Add developer docs for adding a new bridge.
- [ ] Add developer docs for adding new receipts and replay fields.
- [ ] Add consistent changelog or release-notes process.

## Track 14: Documentation, Research, And Blueprint Reconciliation

- [~] Keep overview, README, and testing docs aligned with implementation deltas.
- [ ] Add a dedicated trust-chain management architecture doc.
- [ ] Add a dedicated runtime security and attestation architecture doc.
- [ ] Add a dedicated bridge compatibility matrix doc.
- [ ] Add a dedicated chain migration status matrix doc.
- [ ] Add a dedicated economic model gap doc comparing local PoAW and target chain-native PoAW.
- [ ] Keep whitepaper implementation notes fresh as milestones land.
- [ ] Keep multilingual whitepapers aligned when high-level direction changes.
- [ ] Add operator runbooks for trust update preview, apply, persist, and rollback.
- [ ] Add architecture diagrams for trust flow, dispute flow, and settlement flow.
- [ ] Add research notes for reputation manipulation and anti-collusion defenses.
- [ ] Add research notes for attestation and confidential execution options.
- [ ] Add research notes for protocol expansion beyond MCP and A2A.

## Near-Term Execution Queue

- [x] Add trust-update dry-run preview with structured before and after config diff.
- [x] Add principal-adoption tests and stale-trusted-key removal tests.
- [x] Add config reconciliation export endpoint or CLI helper.
- [x] Add richer operator runbook for trust update and recovery.
- [ ] Add auth hardening plan for operator endpoints.
- [ ] Add stronger receipt semantics for governance and trust changes.
- [ ] Add first task-state transition refinement beyond current queue status set.
- [ ] Expand runtime adapter realism for container-job.
- [ ] Expand MCP and A2A bridge conformance coverage.
- [ ] Add first on-chain identity integration step through DID binding helpers.

## Exit Criteria For Blueprint Convergence

- [ ] Identity is chain-anchorable, auditable, and replayable.
- [ ] Capability and task semantics are formal enough for cross-node negotiation.
- [ ] Swarm orchestration can resume coordinator loss with checkpoint continuity.
- [ ] Runtime execution is policy-controlled, auditable, and materially more isolated than the current skeleton.
- [ ] PoAW and settlement can move from local projection into chain-backed authority without changing the task model.
- [ ] Governance has clear operator, committee, audit, and replay paths.
- [ ] Deployment guidance covers local, compose, and overlay scenarios with repeatable tests.
- [ ] CI and verification cover the most critical safety and recovery paths.

## Execution Note

This checklist is intentionally oversized. It is not a single sprint backlog. It is the durable program map for repeated implementation bursts. During active execution, the preferred operating mode is:

1. pick one narrow vertical slice,
2. land code plus tests plus docs,
3. update this checklist and the implementation roadmap,
4. move to the next highest-leverage gap.