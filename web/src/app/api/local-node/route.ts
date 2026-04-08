import { readFile } from "node:fs/promises";
import path from "node:path";

import { NextRequest, NextResponse } from "next/server";

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

type LocalNodeProxyConfig = {
  authToken?: string;
  endpoint?: string;
};

type CachedLocalClientSession = {
  authorization: string;
  expiresAtMs?: number;
};

export const dynamic = "force-dynamic";
export const revalidate = 0;

let localNodeProxyConfigPromise: Promise<LocalNodeProxyConfig> | null = null;
const localClientSessionCache = new Map<string, CachedLocalClientSession>();
const LOCAL_CLIENT_SESSION_EXPIRY_SKEW_MS = 30_000;
const PROXY_LOCAL_CLIENT_PRINCIPAL = "agentcoin-local-node-proxy";
const PROXY_LOCAL_CLIENT_PUBLIC_KEY =
  "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAGENTCOINLOCALNODEPROXYSESSION agentcoin-local-node-proxy";

function normalizeEndpoint(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function effectivePort(url: URL): string {
  if (url.port) return url.port;
  return url.protocol === "https:" ? "443" : "80";
}

function validateEndpoint(endpoint: string): URL {
  const parsed = new URL(normalizeEndpoint(endpoint));
  if (!/^https?:$/.test(parsed.protocol)) {
    throw new Error("unsupported-endpoint-protocol");
  }
  if (!LOOPBACK_HOSTS.has(parsed.hostname)) {
    throw new Error("only-loopback-endpoints-are-allowed");
  }
  return parsed;
}

function cacheKeyForEndpoint(endpoint: URL): string {
  return `${endpoint.protocol}//${endpoint.hostname}:${effectivePort(endpoint)}`;
}

function parseExpiresAtMs(value: unknown): number | undefined {
  const normalized = String(value || "").trim();
  if (!normalized) return undefined;
  const parsed = Date.parse(normalized);
  if (!Number.isFinite(parsed)) return undefined;
  return parsed;
}

function isLocalAgentSessionPath(pathname: string): boolean {
  return pathname.startsWith("/v1/discovery/local-agents");
}

function getCachedLocalClientSession(endpoint: URL): string | undefined {
  const cached = localClientSessionCache.get(cacheKeyForEndpoint(endpoint));
  if (!cached) return undefined;
  if (cached.expiresAtMs && cached.expiresAtMs - LOCAL_CLIENT_SESSION_EXPIRY_SKEW_MS <= Date.now()) {
    localClientSessionCache.delete(cacheKeyForEndpoint(endpoint));
    return undefined;
  }
  return cached.authorization;
}

function clearCachedLocalClientSession(endpoint: URL): void {
  localClientSessionCache.delete(cacheKeyForEndpoint(endpoint));
}

function endpointFromConfig(payload: Record<string, unknown>, fallbackEndpoint?: string): string | undefined {
  const advertised = String(payload.advertise_url || payload.base_url || fallbackEndpoint || "").trim();
  if (advertised) return normalizeEndpoint(advertised);

  const host = String(payload.host || "").trim();
  const port = Number(payload.port || 0);
  if (!host || !Number.isFinite(port) || port <= 0) return undefined;
  return normalizeEndpoint(`http://${host}:${port}`);
}

async function loadLocalNodeProxyConfig(): Promise<LocalNodeProxyConfig> {
  if (!localNodeProxyConfigPromise) {
    localNodeProxyConfigPromise = (async () => {
      const envToken = String(process.env.AGENTCOIN_LOCAL_NODE_AUTH_TOKEN || "").trim();
      const envEndpoint = String(process.env.AGENTCOIN_LOCAL_NODE_ENDPOINT || "").trim();
      const configPaths = [
        path.resolve(process.cwd(), "../configs/node.frontend-local.json"),
        path.resolve(process.cwd(), "configs/node.frontend-local.json"),
      ];

      for (const filePath of configPaths) {
        try {
          const raw = await readFile(filePath, "utf8");
          const parsed = JSON.parse(raw) as unknown;
          if (!parsed || typeof parsed !== "object") continue;

          const record = parsed as Record<string, unknown>;
          const authToken = String(record.auth_token || envToken || "").trim();
          const endpoint = endpointFromConfig(record, envEndpoint);

          return {
            authToken: authToken || undefined,
            endpoint,
          };
        } catch {
          continue;
        }
      }

      return {
        authToken: envToken || undefined,
        endpoint: envEndpoint ? normalizeEndpoint(envEndpoint) : undefined,
      };
    })();
  }

  return localNodeProxyConfigPromise;
}

async function resolveManagedAuthorizationHeader(requestedEndpoint: URL): Promise<string | undefined> {
  const proxyConfig = await loadLocalNodeProxyConfig();
  if (!proxyConfig.authToken || !proxyConfig.endpoint) return undefined;

  try {
    const configuredEndpoint = validateEndpoint(proxyConfig.endpoint);
    if (
      configuredEndpoint.protocol !== requestedEndpoint.protocol ||
      effectivePort(configuredEndpoint) !== effectivePort(requestedEndpoint)
    ) {
      return undefined;
    }
  } catch {
    return undefined;
  }

  return `Bearer ${proxyConfig.authToken}`;
}

async function issueLocalClientSession(requestedEndpoint: URL, options?: { forceRefresh?: boolean }): Promise<string | undefined> {
  if (!options?.forceRefresh) {
    const cachedAuthorization = getCachedLocalClientSession(requestedEndpoint);
    if (cachedAuthorization) return cachedAuthorization;
  } else {
    clearCachedLocalClientSession(requestedEndpoint);
  }

  const challengeUrl = new URL("/v1/auth/challenge", `${requestedEndpoint.toString()}/`);
  const verifyUrl = new URL("/v1/auth/verify", `${requestedEndpoint.toString()}/`);

  try {
    const challengeResponse = await fetch(challengeUrl, { cache: "no-store" });
    if (!challengeResponse.ok) return undefined;
    const challengePayload = (await challengeResponse.json()) as Record<string, unknown>;
    const challenge = challengePayload?.challenge as Record<string, unknown> | undefined;
    const challengeId = String(challenge?.challenge_id || "").trim();
    if (!challengeId) return undefined;

    const verifyResponse = await fetch(verifyUrl, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      cache: "no-store",
      body: JSON.stringify({
        challenge_id: challengeId,
        principal: PROXY_LOCAL_CLIENT_PRINCIPAL,
        public_key: PROXY_LOCAL_CLIENT_PUBLIC_KEY,
      }),
    });
    if (!verifyResponse.ok) return undefined;

    const verifyPayload = (await verifyResponse.json()) as Record<string, unknown>;
    const session = verifyPayload?.session as Record<string, unknown> | undefined;
    const sessionToken = String(session?.session_token || "").trim();
    if (!sessionToken) return undefined;

    const authorization = `Agentcoin-Session ${sessionToken}`;
    localClientSessionCache.set(cacheKeyForEndpoint(requestedEndpoint), {
      authorization,
      expiresAtMs: parseExpiresAtMs(session?.expires_at),
    });
    return authorization;
  } catch {
    return undefined;
  }
}

async function buildProxyResponse(upstreamResponse: Response): Promise<NextResponse> {
  const body = await upstreamResponse.text();
  const responseHeaders = new Headers();
  const contentType = upstreamResponse.headers.get("content-type");
  const paymentRequired = upstreamResponse.headers.get("x-agentcoin-payment-required");

  if (contentType) responseHeaders.set("content-type", contentType);
  if (paymentRequired) responseHeaders.set("x-agentcoin-payment-required", paymentRequired);

  return new NextResponse(body, {
    status: upstreamResponse.status,
    headers: responseHeaders,
  });
}

async function proxy(request: NextRequest): Promise<NextResponse> {
  const endpoint = request.nextUrl.searchParams.get("endpoint") || "";
  const path = request.nextUrl.searchParams.get("path") || "";

  if (!endpoint || !path) {
    return NextResponse.json({ error: "endpoint-and-path-are-required" }, { status: 400 });
  }

  let upstreamUrl: URL;
  let validatedEndpoint: URL;
  try {
    validatedEndpoint = validateEndpoint(endpoint);
    upstreamUrl = new URL(path, `${validatedEndpoint.toString()}/`);
  } catch (error) {
    return NextResponse.json({ error: "invalid-local-node-endpoint" }, { status: 400 });
  }

  const headers = new Headers();
  for (const headerName of ["accept", "authorization", "content-type"]) {
    const headerValue = request.headers.get(headerName);
    if (headerValue) headers.set(headerName, headerValue);
  }
  if (!headers.has("authorization")) {
    if (isLocalAgentSessionPath(upstreamUrl.pathname)) {
      const sessionAuthorization = await issueLocalClientSession(validatedEndpoint);
      if (sessionAuthorization) headers.set("authorization", sessionAuthorization);
    }
    if (!headers.has("authorization")) {
      const managedAuthorization = await resolveManagedAuthorizationHeader(validatedEndpoint);
      if (managedAuthorization) headers.set("authorization", managedAuthorization);
    }
  }

  const init: RequestInit = {
    method: request.method,
    headers,
    cache: "no-store",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.text();
  }

  try {
    let upstreamResponse = await fetch(upstreamUrl, init);
    if (
      !request.headers.has("authorization") &&
      isLocalAgentSessionPath(upstreamUrl.pathname) &&
      (upstreamResponse.status === 401 || upstreamResponse.status === 403)
    ) {
      const refreshedAuthorization = await issueLocalClientSession(validatedEndpoint, { forceRefresh: true });
      if (refreshedAuthorization) {
        const retryHeaders = new Headers(headers);
        retryHeaders.set("authorization", refreshedAuthorization);
        upstreamResponse = await fetch(upstreamUrl, {
          ...init,
          headers: retryHeaders,
        });
      }
    }

    return buildProxyResponse(upstreamResponse);
  } catch {
    return NextResponse.json({ error: "local-node-unreachable" }, { status: 502 });
  }
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  return proxy(request);
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  return proxy(request);
}

export async function PUT(request: NextRequest): Promise<NextResponse> {
  return proxy(request);
}

export async function PATCH(request: NextRequest): Promise<NextResponse> {
  return proxy(request);
}

export async function DELETE(request: NextRequest): Promise<NextResponse> {
  return proxy(request);
}
