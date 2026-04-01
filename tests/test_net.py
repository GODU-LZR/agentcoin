from __future__ import annotations

import unittest

from agentcoin.net import OutboundNetworkConfig, OutboundTransport


class OutboundTransportTests(unittest.TestCase):
    def test_loopback_and_no_proxy_rules_bypass_proxy(self) -> None:
        transport = OutboundTransport(
            OutboundNetworkConfig(
                http_proxy="http://127.0.0.1:10809",
                https_proxy="http://127.0.0.1:10809",
                no_proxy_hosts=["127.0.0.1", ".tailnet.internal", "100.64.0.0/10"],
                use_environment_proxies=False,
            )
        )

        self.assertTrue(transport.should_bypass_proxy("http://127.0.0.1:8080"))
        self.assertTrue(transport.should_bypass_proxy("http://agentcoin-a.tailnet.internal:8080"))
        self.assertTrue(transport.should_bypass_proxy("http://100.64.0.9:8080"))
        self.assertFalse(transport.should_bypass_proxy("https://example.com"))

    def test_proxy_config_uses_explicit_proxy_for_external_targets(self) -> None:
        transport = OutboundTransport(
            OutboundNetworkConfig(
                http_proxy="http://127.0.0.1:10809",
                https_proxy="http://127.0.0.1:10809",
                no_proxy_hosts=["127.0.0.1", "localhost", "::1"],
                use_environment_proxies=False,
            )
        )

        proxies = transport.proxy_config_for_url("https://rpc.bnbchain.org")
        self.assertEqual(proxies["https"], "http://127.0.0.1:10809")
        self.assertEqual(transport.proxy_config_for_url("http://127.0.0.1:8080"), {})


if __name__ == "__main__":
    unittest.main()
