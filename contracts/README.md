# Contracts Scaffold

This directory contains the first Solidity scaffold for the on-chain AgentCoin track described in:

- `docs/architecture/onchain-roadmap.md`
- `Agent 工作量证明机制研究.docx`
- `一、智能合约架构设计（基于 BNB Chain）.pdf`

Current contracts:

- `src/common/OwnableLite.sol`
- `src/interfaces/IAgentDIDRegistry.sol`
- `src/interfaces/IStakingPool.sol`
- `src/AgentDIDRegistry.sol`
- `src/StakingPool.sol`
- `src/BountyEscrow.sol`

## Scope

This is a contract skeleton, not a production-audited protocol.

Included:

- DID-style agent registration
- native BNB staking
- escrowed job funding
- stake locking and slashing
- evaluator-driven completion and rejection
- basic reputation updates through the registry

Not included yet:

- ERC-20 settlement
- full PoAW score ledger
- challenge bonds and fraud-proof games
- upgradeability
- reentrancy guards and full audit hardening
- tokenized BAP-578 style agent ownership

## Intended Deployment Order

1. deploy `AgentDIDRegistry`
2. deploy `StakingPool`
3. deploy `BountyEscrow`
4. authorize `BountyEscrow` in registry and staking pool

## Tooling Note

This workspace did not have `solc`, `forge`, or a working Hardhat toolchain available when this scaffold was added, so contract compilation was not run in this step.

The files are written for Solidity `^0.8.24` and are meant to be picked up by a later Foundry or Hardhat setup.
