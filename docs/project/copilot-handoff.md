# GitHub Copilot Handoff

This document is the current engineering handoff for continuing AgentCoin without relying on prior chat history.

## Repository State

- Repository: `c:\Users\Twist\Desktop\agentcorn`
- Default branch: `main`
- Latest known good commit: `14f75c4` (`Add settlement relay queue persistence`)
- Test baseline: `60/60` passing with `python -m unittest discover -s tests -v`
- Python baseline: Python `3.11`
- Runtime style: Python standard library first, lightweight, cross-platform, SQLite-backed

Do not commit these two research source files unless explicitly asked:

- `Agent 工作量证明机制研究.docx`
- `一、智能合约架构设计（基于 BNB Chain）.pdf`

## Project Goal

AgentCoin is a Web 4.0 multi-agent collaboration network with:

- cross-node agent interoperability
- workflow/task orchestration
- Git-native task proof and review context
- secure execution and audit receipts
- local PoAW ledger and dispute handling
- on-chain settlement scaffolding for BNB Chain
- weak-network/offline-first behavior

The implementation is intentionally an MVP skeleton aligned to the original blueprint, not a finished production protocol.

## What Is Already Implemented

### Core Node

- local reference node in `agentcoin/node.py`
- SQLite state in `agentcoin/store.py`
- task queue with lease/claim/renew/ack
- message queue semantics with inbox/outbox, dedupe, receipts
- planner/worker/reviewer/committee coordination primitives
- workflow fanout/merge/finalize flow

### Git-Native Coordination

- Git adapter in `agentcoin/gitops.py`
- task Git context binding
- review base/head proof
- mergeability snapshot
- replay-inspect Git proof bundle

### Security and Governance

- HMAC transport signing
- SSH/Ed25519-compatible signing via `ssh-keygen`
- execution audits and replay-inspect
- policy violations
- reputation tracking
- quarantine / release
- governance receipts
- dispute lifecycle
- challenge bond skeleton
- committee vote skeleton

### Interoperability and Adapters

- protocol bridges in `agentcoin/bridges.py`
- `MCP` import/export normalization
- `A2A` import/export normalization
- runtime adapters in `agentcoin/adapters.py` and `agentcoin/runtimes.py`
- supported runtimes:
  - `http-json`
  - `openai-chat`
  - `ollama-chat`
  - `cli-json`
  - `langgraph-http`
  - `container-job`
- OpenClaw can be used through the OpenAI-compatible runtime path

### Semantics and Receipts

- lightweight JSON-LD style semantics in `agentcoin/semantics.py`
- schema examples endpoint
- capability aliasing and semantic dispatch support
- versioned receipts in `agentcoin/receipts.py`

### PoAW and Settlement

- local PoAW event ledger
- event taxonomy:
  - `deterministic-pass`
  - `deterministic-fail`
  - `subjective-approve`
  - `subjective-reject`
  - `challenge-open`
  - `challenge-upheld`
  - `challenge-dismissed`
- configurable PoAW and settlement thresholds
- settlement preview
- settlement RPC plan
- settlement raw bundle
- settlement relay
- resumable settlement relay
- persisted settlement relay history
- persisted settlement relay queue

### On-Chain Scaffold

- contracts scaffold in `contracts/`
- Python-side on-chain helpers in `agentcoin/onchain.py`
- transaction intent builders
- JSON-RPC payload builders
- settlement planning and relay pipeline

## Main APIs Already Present

Examples of important endpoints already implemented:

- `POST /v1/tasks`
- `POST /v1/tasks/dispatch`
- `POST /v1/tasks/dispatch/evaluate`
- `POST /v1/tasks/claim`
- `POST /v1/tasks/ack`
- `GET /v1/tasks/replay-inspect`
- `GET /v1/git/status`
- `GET /v1/git/diff`
- `POST /v1/git/branch`
- `POST /v1/git/task-context`
- `GET /v1/runtimes`
- `POST /v1/runtimes/bind`
- `GET /v1/schema/context`
- `GET /v1/schema/capabilities`
- `GET /v1/schema/examples`
- `GET /v1/poaw/events`
- `GET /v1/poaw/summary`
- `POST /v1/disputes`
- `POST /v1/disputes/vote`
- `POST /v1/disputes/resolve`
- `GET /v1/onchain/status`
- `POST /v1/onchain/intents/build`
- `POST /v1/onchain/rpc-plan`
- `POST /v1/onchain/rpc/send-raw`
- `GET /v1/onchain/settlement-preview`
- `POST /v1/onchain/settlement-rpc-plan`
- `POST /v1/onchain/settlement-raw-bundle`
- `POST /v1/onchain/settlement-relay`
- `GET /v1/onchain/settlement-relays`
- `GET /v1/onchain/settlement-relays/latest`
- `POST /v1/onchain/settlement-relays/replay`
- `POST /v1/onchain/settlement-relay-queue`
- `GET /v1/onchain/settlement-relay-queue`

## Current Roadmap Status

Source of truth:

- `docs/architecture/implementation-roadmap.md`

Status summary:

- `Phase 1-9`: completed
- `Phase 10`: started
  - completed: relay queue persistence
  - next: background settlement relay worker
- `Phase 11-14`: not started

## Recommended Next Task

The next implementation target should be:

- `Phase 10`: background settlement relay worker

Suggested scope:

1. Add a background loop that polls `settlement_relay_queue`.
2. Respect `next_attempt_at`, `max_attempts`, and queue item `status`.
3. Execute queued relay jobs by reusing existing settlement relay code paths.
4. Persist success/failure back to queue records.
5. Introduce queue states such as:
   - `queued`
   - `running`
   - `retrying`
   - `completed`
   - `dead-letter`
6. Expose operator controls afterward:
   - pause / resume
   - requeue
   - dead-letter inspection

## Files Most Likely To Change Next

- `agentcoin/node.py`
- `agentcoin/store.py`
- `agentcoin/onchain.py`
- `tests/test_node_integration.py`
- `docs/architecture/implementation-roadmap.md`
- `docs/testing/strategy.md`
- `README.md`
- `README.zh-CN.md`
- `README.ja.md`

## Test Commands

Run full tests:

```bash
python -m unittest discover -s tests -v
```

Run a focused integration test:

```bash
python -m unittest tests.test_node_integration.NodeIntegrationTests.test_onchain_settlement_relay_queue_persists_items -v
```

Compile-check Python files:

```bash
python - <<'PY'
from pathlib import Path
import py_compile
paths = list(Path("agentcoin").glob("*.py")) + list(Path("tests").glob("*.py"))
for path in paths:
    py_compile.compile(str(path), doraise=True)
print(f"compiled {len(paths)} files")
PY
```

## Git Notes

Typical push command used in this environment:

```bash
git -c http.version=HTTP/1.1 -c http.proxy=http://127.0.0.1:10809 -c https.proxy=http://127.0.0.1:10809 push origin main
```

## Constraints To Preserve

- Keep the project lightweight and cross-platform.
- Prefer Python standard library for the local node unless a dependency is justified.
- Preserve Windows/macOS/Linux/WSL compatibility.
- Do not replace Git with a custom VCS abstraction; keep Git as the code-facts layer.
- Keep bridge layer and runtime adapter layer separate.
- Keep offline-first and weak-network recovery behavior intact.
- Avoid reverting unrelated local changes.
- Do not commit the two research source documents unless explicitly requested.

## Related Docs

- `README.md`
- `docs/project/overview.md`
- `docs/architecture/mvp.md`
- `docs/architecture/implementation-roadmap.md`
- `docs/architecture/poaw-settlement-policy.md`
- `docs/architecture/dispatch-scoring.md`
- `docs/architecture/agent-adapters.md`
- `docs/architecture/onchain-roadmap.md`
- `docs/architecture/alignment-gap.md`
- `docs/testing/strategy.md`
