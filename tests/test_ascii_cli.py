from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentcoin.ascii_cli import render_once
from agentcoin.config import ServiceCapabilityConfig
from agentcoin.onchain import OnchainBindings
from tests.test_node_integration import NodeHarness


class AsciiCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_render_once_includes_ascii_sections_and_service_usage(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            local_controller_address="0x2222222222222222222222222222222222222222",
        )
        node = NodeHarness(
            node_id="ascii-workbench-node",
            token="token-ascii-workbench",
            db_path=str(Path(self.tempdir.name) / "ascii-workbench.db"),
            capabilities=["worker"],
            signing_secret="ascii-workbench-secret",
            payment_required_workflows=["premium-review"],
            services=[
                ServiceCapabilityConfig(
                    service_id="premium-review",
                    description="Premium review",
                    price_per_call=10.5,
                    renter_token_max_uses=2,
                    privacy_level="opaque",
                )
            ],
            onchain=onchain,
        )
        node.start()
        try:
            rendered = render_once(node.base_url, "token-ascii-workbench", "", "en")
            self.assertIn("AgentCoin", rendered)
            self.assertIn("NODE STATUS", rendered)
            self.assertIn("SERVICES", rendered)
            self.assertIn("LOCAL DISCOVERY", rendered)
            self.assertIn("PAYMENT / RENT", rendered)
            self.assertIn("premium-review", rendered)
            self.assertIn("10.5 AGENT", rendered)
            self.assertIn("renter_token_summary", rendered.lower().replace("-", "_"))
        finally:
            node.stop()


if __name__ == "__main__":
    unittest.main()
