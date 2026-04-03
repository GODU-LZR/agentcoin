# Codex Backend Development Roadmap: Supporting the Web4.0 Cypherpunk Frontend

## Vision & Architecture Context
AgentCoin is transitioning into a "Pixel Minimalist / Cypherpunk" Neo-brutalism workspace. The frontend will act as a rich **Console / Workspace** connecting directly to the user's locally running AgentCoin node (`localhost:8000`) and subsequently connecting to remote high-value P2P agents.

To enable this "Local-First Sovereign Client" model and the "Opaque Execution / High-Value Workflow Leasing" business logic, the Python/Node backend requires the following critical upgrades.

---

## 1. Localhost Web Tunnels & CORS (Cross-Origin Resource Sharing)
**Problem:** The future web application (e.g., hosted at `app.agentcoin.network`) cannot currently communicate with the user's local Node (`127.0.0.1:8000`) due to strict browser CORS policies.  
**Requirement:** 
- Implement a robust CORS middleware in FastAPI/LiteLLM node routers.
- The node configuration (`config.py`) must include a new `ALLOWED_FRONTEND_ORIGINS` array.
- Expose basic `/v1/status` and `/v1/peer-health` endpoints explicitly allowing `OPTIONS` preflight requests so the frontend can automatically discover if a local daemon is running upon page load.

## 2. Capabilities & Service Discovery Manifests
**Problem:** Nodes can establish Tailscale/Headscale P2P connections, but lack a standardized schema to broadcast *what* they actually do and *how much* they charge.  
**Requirement:** 
- Add a `/v1/manifest` or `/v1/capabilities` endpoint. 
- Implement a JSON Schema registry where an operator can define their services. Example structure:
  ```json
  {
    "service_id": "legal-contract-analyzer-v1",
    "description": "Professional NDA & Contract Analyzer",
    "price_per_call": 10.5,
    "privacy_level": "opaque"
  }
  ```
- Broadcast this manifest to connected peers upon initial handshake so the React workspace can render "Available Remote Agents" with pricing tags.

## 3. Consumer/Renter Authentication & Payment Gateway
**Problem:** Currently, node security checks verify the "Operator" identity, but no gateway exists to handle "Consumer/Renter" payments before job ingestion.  
**Requirement:**
- Build a Gateway Middleware: When a remote request arrives for a paid capability, the middleware must block the request and demand a cryptographic `Payment Receipt` or `Escrow Signature` tied to `BountyEscrow.sol`.
- Add a "Scoped Bearer Token" issuance system. Once the Ethereum/blockchain lock is verified, issue a short-lived token allowing the renter exactly `N` executions of the specific capability.

## 4. Prompt-Injection Defense & Opaque Sandbox
**Problem:** High-value workflow prompts are trade secrets. External renters must not be able to jailbreak the prompt via the rented `/v1/chat/completions` endpoint.  
**Requirement:**
- `worker.py` must enforce strict I/O typing. If the capability is "Legal Analyzer", the input should only accept `{"contract_text": "...", "focus_areas": [...]}` instead of an open-ended `"messages"` array.
- The core Meta-Prompt must be physically separated and injected at the lowest possible level, isolated from the renter's context window. Implement a guardrail parser (e.g., Llama Guard or programmatic regex checking) prior to LLM submission.
