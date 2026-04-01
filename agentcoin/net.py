from __future__ import annotations

import ipaddress
import json
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib import request
from urllib.parse import urlparse


@dataclass(slots=True)
class OutboundNetworkConfig:
    http_proxy: str | None = None
    https_proxy: str | None = None
    no_proxy_hosts: list[str] = field(default_factory=lambda: ["127.0.0.1", "localhost", "::1"])
    use_environment_proxies: bool = True

    def to_dict(self, *, redact: bool = False) -> dict[str, Any]:
        payload = asdict(self)
        if redact:
            payload["http_proxy"] = bool(self.http_proxy)
            payload["https_proxy"] = bool(self.https_proxy)
        return payload

    def transport_profile(self) -> dict[str, Any]:
        return {
            "proxy_enabled": bool(self.http_proxy or self.https_proxy or self.use_environment_proxies),
            "explicit_http_proxy": bool(self.http_proxy),
            "explicit_https_proxy": bool(self.https_proxy),
            "use_environment_proxies": self.use_environment_proxies,
            "no_proxy_hosts": list(self.no_proxy_hosts),
        }


class OutboundTransport:
    def __init__(self, config: OutboundNetworkConfig | None = None) -> None:
        self.config = config or OutboundNetworkConfig()

    def should_bypass_proxy(self, url: str) -> bool:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            return True
        if hostname in {"localhost"}:
            return True
        try:
            host_ip = ipaddress.ip_address(hostname)
        except ValueError:
            host_ip = None
        if host_ip and host_ip.is_loopback:
            return True
        for rule in self.config.no_proxy_hosts:
            candidate = str(rule or "").strip().lower()
            if not candidate:
                continue
            if host_ip is not None:
                try:
                    if host_ip in ipaddress.ip_network(candidate, strict=False):
                        return True
                except ValueError:
                    pass
            if hostname == candidate:
                return True
            if candidate.startswith("*.") and hostname.endswith(candidate[1:]):
                return True
            if candidate.startswith(".") and hostname.endswith(candidate):
                return True
        return False

    def proxy_config_for_url(self, url: str) -> dict[str, str]:
        if self.should_bypass_proxy(url):
            return {}
        proxies: dict[str, str] = {}
        if self.config.http_proxy:
            proxies["http"] = self.config.http_proxy
        if self.config.https_proxy:
            proxies["https"] = self.config.https_proxy
        if proxies:
            return proxies
        if self.config.use_environment_proxies:
            discovered = request.getproxies()
            return {key: value for key, value in discovered.items() if key in {"http", "https"}}
        return {}

    def opener_for_url(self, url: str) -> request.OpenerDirector:
        return request.build_opener(request.ProxyHandler(self.proxy_config_for_url(url)))

    def request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10,
    ) -> dict[str, Any]:
        body = None
        req_headers = dict(headers or {})
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        req = request.Request(url, data=body, headers=req_headers, method=method)
        with self.opener_for_url(url).open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
