# Remote Deployment Readiness

## Status

As of 2026-04-08, this repository is **not yet considered ready** for a fresh-clone remote deployment flow such as:

1. clone from GitHub
2. create a new Python environment
3. start a remote AgentCoin node
4. connect that remote node to OpenClaw or another remote gateway for live integration testing

The project is in a stronger state for local integration than before, but it has not crossed the threshold where remote deployment should be treated as the next primary milestone.

## What Is Already Verified Locally

- the local backend can run and serve the current integration daemon on `127.0.0.1:8080`
- the local workbench proxy path can drive the backend through `/api/local-node`
- GitHub Copilot CLI ACP flows now behave more predictably:
  - `session/load` must finish before `task-request`
  - if a prompt is sent too early, the backend now returns a clear `400` instead of forwarding a bad request
  - after `session/load` completes, the same ACP session can finish a simple HTML demo task successfully
- `/v1/integrations/openclaw/bind` now preserves richer OpenAI-compatible runtime settings:
  - `structured_output`
  - `response_format`
  - `headers`
  - `top_p`
  - `presence_penalty`
  - `frequency_penalty`

These are good local readiness signals, but they do not yet prove remote deployment readiness.

## Why Remote Deployment Should Wait

### 1. The current web attach model is still local-first

The workbench proxy in `web/src/app/api/local-node/route.ts` is intentionally loopback-only.

That is correct for the current safety model, but it also means the current frontend is still primarily a **local node control surface**, not a ready-made remote control plane.

### 2. Fresh-clone deployment has not been validated end-to-end

We do not yet have a confirmed, repeatable runbook for:

- cloning from GitHub onto a clean remote host
- creating the runtime environment from scratch
- materializing config and secrets safely
- starting the node and any worker loops under a durable service manager
- validating restart behavior, logs, and failure recovery

Until that path is exercised from a blank machine, remote deployment remains a guess rather than a tested capability.

### 3. Remote exposure hardening is not complete

The repository has made meaningful progress on operator auth and scoped local access, but the overall posture is still not where we want it for a remotely exposed node.

Before remote rollout, we still need a more explicit answer for:

- which write APIs may be exposed at all
- how operator auth should be provisioned on a remote host
- how secrets should be rotated
- what reverse proxy and TLS termination pattern we recommend
- what minimum safe config looks like outside loopback

### 4. OpenClaw remote integration is only partially validated

The OpenClaw binding path is now in better shape locally, and unit/integration coverage exists around the runtime adapter and bind helper.

What is still missing is a real remote smoke pass against the intended deployment topology, including:

- remote endpoint reachability
- auth token handling outside the local machine
- timeout and retry behavior on a real network
- operator workflow after startup from a clean environment

### 5. We still lack a deployment-grade smoke suite

Right now, local debugging can reproduce the important flows, but there is not yet a single post-deploy check that answers:

- is the node healthy
- is auth configured correctly
- does the chosen runtime bind correctly
- can a simple OpenClaw-backed task complete
- can the operator tell success from partial failure quickly

That smoke suite should exist before remote testing becomes the main track.

### 6. Desktop-local ACP flows should not be confused with remote node readiness

GitHub Copilot CLI ACP testing has been valuable, but it validates a **local desktop bridge** pattern.

It does not by itself validate:

- remote service deployment
- remote gateway routing
- remote node operator experience
- remote multi-host failure handling

So ACP progress is real, but it should not be used as the main proof that remote deployment is ready.

## Exit Criteria Before Remote Deployment

The project should clear these gates before we treat remote deployment as the next step:

1. A fresh-host deployment runbook is written and followed successfully from a blank machine.
2. A dedicated remote config profile exists, rather than relying on local frontend/dev defaults.
3. A post-deploy smoke script validates backend health, auth, runtime binding, and one minimal OpenClaw-backed task.
4. The intended frontend/operator access model for a remote node is explicitly defined.
5. OpenClaw remote integration is exercised against the real target topology, not only local mocks or local bind tests.
6. The team agrees on the minimum acceptable hardening level for exposing the node beyond loopback.

## Recommended Near-Term Focus

Instead of pushing to a remote host now, the next useful work is:

- keep stabilizing local integration behavior
- add a repeatable deployment smoke script
- write the clean-host deployment runbook
- define the remote config and secret model
- decide whether the first remote milestone is:
  - backend-only remote smoke
  - remote OpenClaw gateway binding
  - remote operator UI access

## Decision Record

Current team assessment on 2026-04-08:

- local integration quality has improved enough to continue local backend and frontend hardening
- remote deployment is still premature
- documentation and validation should advance first, so the eventual remote test is intentional and repeatable rather than exploratory
