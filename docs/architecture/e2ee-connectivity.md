# End-to-End Connectivity Without Public IPs

## Recommendation

For the first production-grade transport layer of AgentCoin, use:

- `Tailscale clients` on every agent node
- `Headscale` as the self-hosted control plane
- `DERP relay` enabled for fallback connectivity
- application traffic carried over private tailnet addresses

This is the best near-term choice because it gives AgentCoin:

- end-to-end encrypted connectivity,
- no need for public IPs on agent nodes,
- NAT traversal with relay fallback,
- support for Windows, macOS, Linux, and WSL-hosted workloads,
- low operational complexity compared with building custom NAT traversal first.

## Why This Fits AgentCoin

### No public IP on agent nodes

Agent nodes only need outbound connectivity. They do not need port forwarding or public inbound exposure. This matches laptops, home broadband, office NAT, CGNAT, and cloud private subnets.

### End-to-end encryption

The transport layer is encrypted end-to-end between peers. Relay servers can forward packets when direct paths are not possible, but they do not terminate or decrypt the application traffic.

### Cross-platform

The client support matrix covers Linux, Windows, and macOS. That makes it practical for mixed development and edge environments.

### Better than forcing custom P2P first

AgentCoin still needs application-level protocol design, local durability, retries, and policy enforcement. Solving all of that while also inventing NAT traversal in the first MVP would slow the project down. Headscale plus Tailscale-compatible clients gives us a hardened transport substrate now.

## Proposed Topology

```mermaid
flowchart LR
    A[Agent Node A<br/>Windows/macOS/Linux/WSL] -->|WireGuard-encrypted| H[Headscale Control Plane]
    B[Agent Node B<br/>Windows/macOS/Linux/WSL] -->|WireGuard-encrypted| H
    C[Agent Node C<br/>Windows/macOS/Linux/WSL] -->|WireGuard-encrypted| H

    A <-->|Direct P2P if possible| B
    B <-->|Direct P2P if possible| C
    A <-->|Direct P2P if possible| C

    A -.->|Encrypted relay fallback| D[DERP Relay]
    B -.->|Encrypted relay fallback| D
    C -.->|Encrypted relay fallback| D
```

## Minimum Deployment Example

This example is intentionally limited to a deployment recipe. It is not the later multi-node demo compose. The goal is to show how a self-hosted `Headscale` control plane, `Tailscale-compatible` clients, and two AgentCoin nodes fit together on one encrypted overlay.

Assumptions:

- `Headscale` is reachable at `https://headscale.example.internal`
- MagicDNS names resolve inside the overlay
- AgentCoin node A listens on `agentcoin-a.tailnet.internal:8080`
- AgentCoin node B listens on `agentcoin-b.tailnet.internal:8080`
- overlay addresses come from the usual `100.64.0.0/10` tailnet range

### 1. Bootstrap Headscale

Typical control-plane preparation looks like this:

```bash
headscale users create agentcoin
headscale preauthkeys create --user agentcoin --reusable --expiration 24h
```

Keep the overlay policy narrow. A minimal ACL skeleton is:

```json
{
    "tagOwners": {
        "tag:agentcoin": ["autogroup:admin"]
    },
    "acls": [
        {
            "action": "accept",
            "src": ["tag:agentcoin"],
            "dst": ["tag:agentcoin:8080"]
        }
    ]
}
```

This keeps the control plane self-hosted while allowing only AgentCoin-tagged nodes to reach each other on the node API port.

### 2. Join Each Node To The Overlay

On Linux, macOS, or WSL-hosted nodes, the bootstrap shape is:

```bash
tailscale up \
    --login-server https://headscale.example.internal \
    --auth-key tskey-client-example \
    --hostname agentcoin-a \
    --advertise-tags=tag:agentcoin \
    --accept-dns=false
```

Repeat the same flow for `agentcoin-b` and any later peers. On Windows, use the same login server and auth key through the service or UI, then verify that the node receives the expected tailnet IP and MagicDNS name.

Useful validation commands:

```bash
tailscale status
tailscale ip -4
```

### 3. Configure AgentCoin Nodes For Overlay Routing

Node A can advertise its overlay identity and peer routing like this:

```json
{
    "host": "0.0.0.0",
    "port": 8080,
    "overlay_network": "tailnet",
    "overlay_endpoint": "agentcoin-a.tailnet.internal:8080",
    "overlay_addresses": ["100.64.0.11"],
    "network": {
        "no_proxy_hosts": [
            "127.0.0.1",
            "localhost",
            "::1",
            "100.64.0.0/10",
            ".tailnet.internal"
        ]
    },
    "peers": [
        {
            "peer_id": "agentcoin-peer-b",
            "name": "AgentCoin Peer B",
            "url": "http://100.64.0.12:8080",
            "overlay_endpoint": "agentcoin-b.tailnet.internal:8080"
        }
    ]
}
```

Node B mirrors the same pattern with its own `overlay_endpoint`, `overlay_addresses`, and a peer entry pointing back to node A.

Important conventions for this example:

- keep raw peer `url` values overlay-private, never public internet addresses
- keep `overlay_endpoint` on the stable MagicDNS name even if the concrete tailnet IP changes later
- include `100.64.0.0/10` and `.tailnet.internal` in `no_proxy_hosts` so enterprise proxies do not intercept overlay traffic
- keep the AgentCoin bearer token or stronger app-layer auth enabled even though the transport is already encrypted

### 4. Smoke-Test The Overlay Path

Once both nodes are online, validate the network and application path in order:

```bash
curl http://agentcoin-a.tailnet.internal:8080/healthz
curl http://agentcoin-b.tailnet.internal:8080/healthz
curl -X POST http://agentcoin-a.tailnet.internal:8080/v1/peers/sync -H "Authorization: Bearer change-me"
curl http://agentcoin-a.tailnet.internal:8080/v1/peer-cards -H "Authorization: Bearer change-me"
```

Then test overlay-directed delivery by targeting the peer id rather than a raw URL:

```bash
curl -X POST http://agentcoin-a.tailnet.internal:8080/v1/tasks/dispatch \
    -H "Authorization: Bearer change-me" \
    -H "Content-Type: application/json" \
    -d '{
        "id": "overlay-demo-task-1",
        "kind": "code",
        "deliver_to": "agentcoin-peer-b",
        "required_capabilities": ["worker"]
    }'
```

If the overlay is healthy, node A should resolve `agentcoin-peer-b` from its configured peers, sync peer-card data, and deliver over the private tailnet address.

### 5. Operational Guardrails

- expose public ingress for `Headscale` and optional `DERP`, not for the AgentCoin node API itself
- prefer tailnet IPs or MagicDNS names in peer config, and reserve loopback-only bindings for local single-node development
- keep DERP enabled for difficult NAT paths, but do not treat it as an application trust boundary
- monitor outbox retry and peer-health metrics because overlay encryption does not remove weak-network behavior

This example closes the deployment-example gap for Phase 14. A separate reproducible local topology now exists in `compose.multi-node.yaml` and `docs/project/multi-node-demo.md`; it exercises the same peer-routing model on a Docker bridge network rather than on a real Headscale-managed overlay.

## Application Layer on Top

The transport layer should not define the AgentCoin message protocol by itself. On top of the encrypted tailnet, keep AgentCoin's own protocol explicit:

- `Capability Card` discovery
- `TaskEnvelope` submission
- `Inbox/Outbox` durable delivery
- `Acknowledgement` and retry
- `Checkpoint` synchronization
- `Policy` and `auth` at the application layer

In practice, this means AgentCoin nodes should talk to each other over tailnet IPs or MagicDNS names using:

- HTTPS + JSON for the first MVP
- gRPC or HTTP/2 for richer streaming later
- MCP / A2A bridges as adapters, not as the transport substrate itself

## Weak-Network and Offline Strategy

Even with encrypted overlay networking, weak links still happen. The transport design should therefore be `offline-tolerant`, not only `connected`.

Required behavior:

1. Persist outbound messages locally before network delivery.
2. Assign every message a stable idempotency key.
3. Require explicit acknowledgement for delivery completion.
4. Retry with exponential backoff when a peer is unreachable.
5. Resume synchronization from checkpoints after reconnection.
6. Keep messages compact and incremental to survive poor bandwidth.

This is why the current reference node already keeps `tasks`, `inbox`, and `outbox` in SQLite.

## Security Notes

- Bind services to the tailnet interface or localhost plus a tailnet proxy.
- Keep bearer tokens or mTLS on the application layer even inside the overlay.
- Use ACLs in Headscale/Tailscale to restrict which classes of agents may talk to which services.
- Separate coordination traffic from execution traffic where possible.
- Treat relay fallback as a network convenience, not as a trust boundary.

## When to Move Beyond This

This recommendation is for the first serious implementation phase. Move to a lower-level transport such as `libp2p` when AgentCoin needs one or more of the following:

- protocol-native peer discovery independent of the tailnet,
- custom gossip and pubsub semantics at scale,
- browser-native peers,
- transport pluggability beyond the VPN-style overlay,
- or a fully application-owned P2P stack.

At that stage, `libp2p` is the most credible next candidate because it already provides encrypted connections, relay support, and NAT traversal primitives.

## Practical Decision

The decision for the next implementation step should be:

- `Now`: Headscale + Tailscale-compatible clients as the encrypted transport plane.
- `Now`: AgentCoin HTTP/JSON protocol over private overlay addresses.
- `Later`: optional libp2p transport adapter when the protocol layer is stable.

