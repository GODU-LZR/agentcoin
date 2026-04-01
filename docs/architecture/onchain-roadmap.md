# On-Chain Roadmap

This document turns the two new research reports into an implementation track for the repository:

- `Agent 工作量证明机制研究.docx`
- `一、智能合约架构设计（基于 BNB Chain）.pdf`

The current Python runtime already covers local coordination, weak-network delivery, review gates, signed receipts, and governance. The missing layer is the on-chain trust and settlement system:

- portable agent identity
- task escrow
- staking and slashing
- PoAW scoring
- challenge and dispute handling

This roadmap defines the minimum chain-native path for BNB Chain.

## Design Goal

The chain layer should not replace the current runtime. It should anchor:

- who the agent is
- who posted the job
- where the money is locked
- what stake is at risk
- what result was accepted or challenged
- how reputation and rewards change after resolution

The Python node remains the execution and coordination plane. BNB Chain becomes the trust, escrow, and settlement plane.

## Contract Set

The first contract set is intentionally narrow:

1. `AgentDIDRegistry`
2. `StakingPool`
3. `BountyEscrow`

Later phases should add:

4. `PoAWScorebook`
5. `ChallengeManager`
6. `Treasury / SettlementVault`
7. `ReputationEventLedger`

## Phase 1: Identity

`AgentDIDRegistry` is the chain-native identity anchor.

Responsibilities:

- register a unique `bytes32` DID
- bind the DID to a controller address
- store metadata URI and service endpoint
- store capability hash
- maintain aggregate counters for completed and failed jobs
- maintain a simple reputation score
- allow approved protocol contracts to apply reputation updates

Why this is first:

- escrow and staking need a stable identity source
- off-chain nodes need a chain-verifiable subject for rewards and penalties
- future BAP-578 or ERC-8004 style integration can map into this registry

## Phase 2: Stake Security

`StakingPool` is the anti-Sybil and penalty layer.

Responsibilities:

- accept native BNB stake deposits
- expose available stake per worker
- lock stake when a worker accepts a job
- unlock stake when a job is completed or rejected cleanly
- slash stake when a dispute is proven or a reviewer marks the work malicious
- authorize only protocol escrow contracts to lock, unlock, or slash stake

This is the simplest useful version of:

- worker bond
- slashable collateral
- economic cost of low-quality execution

## Phase 3: Escrow And Resolution

`BountyEscrow` is the first settlement contract.

Responsibilities:

- let a client create a funded job
- record stake requirements and minimum reputation
- let a worker accept a job if stake and reputation are sufficient
- accept a work submission hash and result URI
- let an evaluator or client complete, reject, refund, or slash the job
- move native BNB rewards
- update registry reputation
- lock and unlock stake through `StakingPool`

This phase is deliberately evaluator-driven. It is not yet a full decentralized PoAW system.

## Job State Machine

The first on-chain state machine should stay small:

- `Funded`
- `Assigned`
- `Submitted`
- `Challenged`
- `Completed`
- `Rejected`
- `Refunded`
- `Slashed`

Mapping to the current Python runtime:

- local task creation maps to `createJob`
- worker claim maps to `acceptJob`
- task ack/result maps to `submitWork`
- review gate completion maps to `completeJob` or `rejectJob`
- governance or challenge escalation maps to `challengeJob` and `slashJob`

## PoAW Evolution Path

The contract scaffold added now does not claim to solve final PoAW. It supports three future tracks:

### Deterministic track

For code, data extraction, and testable tasks:

- off-chain oracle or CI runner executes the test suite
- runner publishes a result hash or receipt URI
- evaluator resolves the escrow based on that receipt

### Subjective track

For reports, planning, and creative output:

- multi-reviewer or judge agents evaluate the result
- a future `PoAWScorebook` contract stores score events
- payout can be proportional to score bands

### Challenge track

For high-value or disputed jobs:

- `challengeJob` marks a submission disputed
- later `ChallengeManager` should manage challenge windows, challenger bonds, and final resolution

## Current Repository To Chain Mapping

Current runtime capabilities already available:

- signed node identity
- durable task queue
- worker reputation and quarantine
- governance action log
- review-gated workflow and merge policy
- execution audit trail

What should move on-chain:

- canonical agent identity
- economic stake
- funded job lifecycle
- slash outcome
- payout outcome
- challenge references

What should stay off-chain:

- prompt payloads
- tool traces
- full execution logs
- large model outputs
- bridge-specific payload details

These should be stored in Git, object storage, or content-addressed storage and referenced on-chain by hash or URI.

## Deployment Order

Recommended order on BNB Chain testnet:

1. deploy `AgentDIDRegistry`
2. deploy `StakingPool`
3. deploy `BountyEscrow` with registry and staking addresses
4. authorize the escrow contract in both registry and staking pool
5. register a small set of test agents
6. fund and run one deterministic task flow end-to-end

## First Integration Targets

After the contracts are compiled and deployed, the Python node should add:

- local config for contract addresses
- optional DID binding in node config
- signed task receipts that include on-chain job id
- worker submission hook that writes `submissionHash` and `resultURI`
- reviewer hook that calls `completeJob`, `rejectJob`, or `slashJob`

## Explicit Non-Goals For This Step

Not included in this first scaffold:

- ERC-721 or BAP-578 full asset semantics
- ERC-20 reward token support
- x402 settlement channels
- decentralized dispute committees
- challenge bonds
- score aggregation DAO
- TEE attestation
- zkML or VeriLLM verification

Those remain later milestones. The purpose of this step is to establish a clean contract boundary that matches the reports and gives the repository a concrete chain-native starting point.
