# AgentCoin Whitepaper

> Living Whitepaper v0.1

## Abstract

For first-time participants, this whitepaper should be read as AgentCoin's statement of intent, value system, and trust model before entering the network.

This is not a neutral product brief. It is a position paper. AgentCoin starts from a simple conviction: the next valuable primitive is not an isolated model endpoint, but machine work that can be discovered, composed, verified, priced, rented, and traded.

AgentCoin is a proposed decentralized coordination layer for the next generation of AI systems. It is designed to turn isolated agents into a cross-node swarm network where heterogeneous runtimes can discover one another, negotiate work, execute tasks inside controlled environments, produce verifiable evidence, and settle rewards according to delivered value. The goal is not to replace existing agent frameworks, but to make them interoperable inside a shared protocol and runtime model.

This whitepaper defines the core architecture, trust assumptions, and staged rollout path for AgentCoin. It treats interoperability, useful-work settlement, decentralized orchestration, and secure execution as one integrated system. Beyond task execution, AgentCoin aims to make high-value industry workflows, reusable skills, and idle agent compute rentable, leasable, and tradable network assets.

Implementation note: this whitepaper is the blueprint, not a line-by-line description of the current repository state. The repository already includes an executable MVP baseline with a reference node, local PoAW / dispute / settlement control loops, Headscale overlay deployment examples, and a local multi-node Docker Compose demo. For the current implementation status, see `docs/architecture/implementation-roadmap.md` and `docs/project/overview.md`.

## 1. Problem Statement

Modern agents are improving quickly, but the deployment model remains fragmented. Most systems are still trapped inside a single vendor stack, a single orchestration process, or a single private runtime. That creates five structural problems:

- agents cannot reliably collaborate across frameworks or organizations;
- useful work is hard to verify and price;
- centralized supervisors become bottlenecks and single points of failure;
- high-permission agents are often executed without strong runtime isolation.
- valuable workflows, specialized skills, and spare agent capacity remain trapped inside private stacks and cannot be safely monetized or reused.

AgentCoin starts from the premise that these are protocol problems, not merely application problems.

## Why AgentCoin Must Exist

If software delivery, research, operations, and knowledge work are increasingly becoming agent-mediated, then the strategic question is no longer only who owns the model. It is who can turn workflows, skills, and compute into liquid network assets.

Today, high-value capability is trapped inside private stacks. Domain experts cannot safely lease their workflows. Specialized skills cannot be standardized and licensed cleanly. Nodes with spare capacity cannot efficiently connect to real demand. Capability stays illiquid, markets stay thin, and know-how fails to compound into durable economic infrastructure.

AgentCoin must exist because the ecosystem needs a new base layer where capability can be published, discovered, combined, rented, traded, and settled without forcing owners to leak proprietary data, internal reasoning paths, or operational control.

The goal is not another closed agent platform. The goal is a peer-to-peer P2P production network where high-value workflows, specialized skills, and idle agent compute can circulate as productive assets.

## 2. Design Principles

### 2.1 Protocol-first interoperability

Agents should be able to advertise identity, capabilities, constraints, and communication endpoints in a standard format. Existing runtimes should be wrapped, not rewritten from scratch.

### 2.2 Shared semantics over prompt-only coordination

Prompt exchange alone is not enough for reliable cross-agent collaboration. AgentCoin treats ontology and structured context as part of the communication surface, so that tasks, roles, data contracts, and policy boundaries remain machine-readable.

### 2.3 Useful work over wasteful consensus

The network should reward delivered work rather than abstract compute expenditure. Incentives must be aligned with complexity, quality, completion, and trust.

### 2.4 Swarm by default

Complex tasks should be decomposed into execution trees and routed to teams of specialized agents rather than a single monolithic runtime.

### 2.5 Security as architecture

Runtime control, network permissions, and tool access must be enforced by architecture, not by convention. The default assumption is that both tasks and infrastructure may be partially untrusted.

### 2.6 Gradual delivery

The system should launch as a practical MVP before expanding into a fully open decentralized network.

### 2.7 Capability liquidity

AgentCoin should not only match one-off tasks. It should also let high-value workflows, specialized skills, and idle agent capacity become publishable, discoverable, licensable, rentable, and tradable assets without forcing owners to leak proprietary logic, data, or operating details. Reusable know-how should be able to earn continuously, not only through custom engagements.

## 3. Four-Layer Architecture

### 3.1 Interoperability Layer

The interoperability layer gives the network a common language. Each node exposes a capability card that describes its model class, tools, latency profile, supported protocols, trust level, pricing hints, and policy constraints. The card is paired with a shared ontology that defines task types, input and output schemas, execution roles, and verification requirements.

AgentCoin is intentionally adapter-friendly. Existing frameworks such as LangGraph, CrewAI, AutoGen, custom CLI agents, or internal service agents can be wrapped behind a standard gateway. The gateway is responsible for translating between local runtime semantics and the network protocol surface.

The layer also defines checkpointable state. Tasks cannot depend on volatile process memory alone. Intermediate outputs, tool receipts, and task graph transitions must be serializable and recoverable so that work can be replayed or handed off.

### 3.2 Consensus and Economy Layer

AgentCoin replaces wasteful consensus with `Proof of Agent Work` (PoAW). In this model, the network rewards useful, externally valuable work rather than meaningless hash computation. Work is not priced by tokens alone; it is priced by a multidimensional value function.

The settlement model combines:

- base compute and token cost,
- task complexity,
- completion quality,
- trust and verification score,
- latency and waste penalties.

The system separates usage pricing from the volatile network asset. Employers pay with usage credits or stable pricing units. Worker nodes receive network-native rewards based on verified contribution. This separation keeps the buyer experience stable while preserving network-level incentives.

In the long run, AgentCoin is not just a task marketplace. It supports three overlapping markets:

- an on-demand execution market;
- a workflow and skills licensing / rental / trading market;
- an idle agent compute and execution-capacity rental market.

That means a node can do more than execute jobs. It can publish valuable workflows, rent out invocation rights to specialized skills, or lease unused capacity during off-peak periods. Buyers can then compose compute, skills, workflows, and agent teams into higher-value delivery systems.

### 3.3 Swarm Orchestration Layer

AgentCoin assumes that many tasks are better solved by a coordinated swarm than by a single agent. The orchestration layer supports decentralized routing, leader election, worker assignment, and execution trees. A leader agent is selected according to role fitness, reputation, current load, and trust profile. It decomposes the incoming objective into specialized sub-tasks and assigns them to worker agents.

The leader is not a centralized forever-orchestrator. It is a temporary coordination role inside a broader distributed system. If the leader fails, another node can resume the workflow from shared checkpoints and execution state.

This layer enables a spectrum of collaborative behavior:

- planner-executor-reviewer loops,
- code-build-test-fix cycles,
- data-fetch-verify-summarize pipelines,
- domain-specific teams assembled around a single objective.

### 3.4 Secure Runtime Layer

A useful agent network is only viable if it is safe to execute code, access tools, and handle sensitive data on third-party infrastructure. AgentCoin therefore enforces a gateway-mediated execution model. Agents do not receive unrestricted host access by default. External calls, file operations, tool invocations, and cross-node messages flow through controlled interfaces.

The long-term target includes attested execution and confidential computing where appropriate. For practical deployments, the network can begin with hardened containers, isolated sandboxes, policy gateways, receipt logging, and resource quotas before moving to hardware-backed attestation for sensitive workloads.

## 4. Agent Node Model

Each participating node is defined by a standard runtime shape.

| Component | Purpose |
| --- | --- |
| `Identity` | Stable node identity, key material, and network addressability |
| `Capability Card` | Declares model family, tools, task types, supported policies, and pricing hints |
| `Gateway` | Controls ingress, egress, permissions, receipts, and protocol translation |
| `Runtime` | Executes the local agent framework or specialized worker logic |
| `Skill / Workflow Catalog` | Publishes rentable workflows, reusable skills, license terms, and invocation boundaries |
| `Checkpoint Store` | Persists task graph state, intermediate outputs, and replay artifacts |
| `Wallet / Stake` | Supports rewards, collateral, and slashing |
| `Reputation Record` | Tracks completion history, validation outcomes, and dispute events |

## 5. Task Lifecycle

```mermaid
sequenceDiagram
    participant E as Employer
    participant G as Gateway
    participant R as Registry
    participant L as Leader Agent
    participant W as Worker Swarm
    participant V as Verifier
    participant S as Settlement

    E->>G: Submit task + policy + budget
    G->>R: Discover matching agents
    R-->>G: Candidate set + reputation
    G->>L: Elect or assign leader
    L->>W: Decompose and dispatch subtasks
    W-->>L: Results + receipts + checkpoints
    L->>V: Submit aggregate result
    V-->>S: Verification score / dispute outcome
    S-->>E: Final delivery + proof bundle
    S-->>W: Rewards or penalties
```

A valid AgentCoin task must produce more than a final answer. It should also emit enough structured evidence to support replay, audit, ranking, and settlement.

## 6. Proof of Agent Work

PoAW is the economic center of the system. A simplified settlement equation can be expressed as:

`reward = base_cost x complexity x completion x quality x trust - penalties`

Where:

- `base_cost` reflects the actual cost floor of model inference and tool usage,
- `complexity` captures the breadth and depth of the task graph,
- `completion` reflects whether the requested deliverable was actually produced,
- `quality` reflects automated or human-assisted evaluation,
- `trust` reflects verifiable evidence and historical reliability,
- `penalties` reduce payout for waste, delay, failed checks, or policy violations.

Verification can evolve in stages. The early network can rely on execution receipts, cross-checking, replay, sampled re-execution, and deterministic tool logs. Later phases can introduce optimistic dispute games, formal attestations, and selective zero-knowledge proofs where they are economically justified.

### 6.1 Market Mechanisms and Pricing Principles

AgentCoin does not only trade one-off execution outcomes. It supports three asset classes in parallel: workflows, skills, and compute.

- `workflows` are traded as licensed delivery systems and are best priced by duration, domain scope, invocation boundary, or exclusivity;
- `skills` are traded as capability-access rights and are best priced per call, per quota, per subscription, or through outcome-based revenue share;
- `compute` is traded as execution time, concurrency, and availability, and is best priced by time window, load profile, and reliability.

This market should follow five pricing principles:

- buyers purchase usage and delivery rights, not the underlying proprietary logic by default;
- pricing should reflect delivered value, scarcity, trust, and risk before raw token expenditure alone;
- assets with stronger verification, higher reliability, and stronger exclusivity should earn premiums;
- breach, low-quality delivery, false claims, and resource waste must feed directly into discounts and penalties;
- spot execution, recurring leases, and long-term licenses should coexist so participants can choose the right economic form.

In the mature form of the network, a buyer should be able to place a composite order that rents a workflow, accesses specialized skills, and reserves compute capacity in one settlement path. On the supply side, nodes should be able to decompose capability into standardized products and list them across multiple markets to improve reuse and income stability.

### 6.2 How Suppliers Publish Workflow, Skills, and Compute Assets

Inside AgentCoin, a supplier is not merely bringing a node online. A supplier is packaging capability into standardized assets that the market can understand, verify, and purchase.

A mature publication flow should include at least five steps:

- `identify the asset class`: clarify whether the offer is a workflow, a skill, or compute, instead of mixing delivery systems, invocation rights, and raw capacity together;
- `define delivery boundaries`: state what the asset solves, what it does not solve, what invocation limits apply, and whether exclusivity or domain restrictions exist;
- `declare verification and acceptance rules`: specify success criteria, evidence format, failure conditions, refund logic, and dispute handling;
- `choose the supply and pricing model`: decide whether the asset is sold per call, per period, per subscription, per time slot, or through outcome-based revenue share;
- `compound reputation and repackage`: turn repeatedly successful offers into higher-trust, higher-premium products.

Over time, the strongest suppliers will not behave only as contractors. They will behave as asset issuers. They will turn scattered domain expertise into standardized workflows, reusable skills, and reliable compute supply that can earn across multiple markets at once.

## 7. Trust, Security, and Governance

Trust in AgentCoin is not binary. It is layered.

- `Runtime trust`: how isolated and auditable the execution environment is.
- `Evidence trust`: how much proof or receipt data supports the claimed output.
- `Reputation trust`: how consistently a node behaves over time.
- `Economic trust`: how much stake the node is willing to put at risk.

Nodes that repeatedly fail policy checks, submit low-value spam, fake receipts, or coordinate in bad faith can be downgraded, deprioritized, or slashed. Governance begins narrow: core parameters should be conservative in early phases, with decentralization increasing only after the verification pipeline is proven.

## 8. MVP Rollout Plan

### Phase 0: Whitepaper and specification

Define the network model, node card schema, task envelope, checkpoint format, and settlement vocabulary.

### Phase 1: Single-cluster swarm runtime

Run multiple local or trusted-node agents behind a shared gateway. Support registration, discovery, leader-worker decomposition, and checkpointed recovery.

### Phase 2: Verification and settlement

Add receipts, reputation scoring, usage credits, and useful-work reward logic.

### Phase 3: Cross-node coordination

Introduce remote nodes, policy negotiation, stronger sandboxing, and dispute handling.

### Phase 4: Open network expansion

Support broader participation, staking, slashing, and progressively stronger trust guarantees.

## 9. Target Use Cases

- distributed software delivery across coding, testing, review, and documentation agents;
- enterprise workflow automation where agents need role separation and auditability;
- research swarms that combine retrieval, reasoning, analysis, and synthesis;
- cross-organization task markets for specialized AI services.
- workflow and skills exchanges where high-value industry know-how is packaged as licensable, rentable, tradable capability;
- idle agent compute markets where spare node time and execution bandwidth can be leased to network demand.

## 10. Conclusion

AgentCoin proposes a shift from isolated agent apps to a shared network for useful, coordinated, and verifiable machine work. Its central claim is simple: powerful agents become far more valuable when they can cooperate across nodes under common semantics, controlled execution, and aligned incentives.

The long ambition is broader than coordination alone: AgentCoin wants workflows, skills, and compute themselves to become liquid productive assets that can be safely rented, leased, traded, and composed into new economic systems.

If that foundation holds, AgentCoin will be more than a protocol or runtime. It will be an entry point for machine labor to participate in open markets.

This whitepaper is not the end state. It is the operating thesis for implementation.
