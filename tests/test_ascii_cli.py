from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentcoin.ascii_cli import AgentcoinAsciiWorkbench, WorkbenchState, render_once
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

    def test_ascii_workbench_supports_workflow_receipt_token_and_reconcile_commands(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            local_controller_address="0x2222222222222222222222222222222222222222",
        )
        node = NodeHarness(
            node_id="ascii-ops-node",
            token="token-ascii-ops",
            db_path=str(Path(self.tempdir.name) / "ascii-ops.db"),
            capabilities=["worker"],
            signing_secret="ascii-ops-secret",
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
            workbench = AgentcoinAsciiWorkbench(
                WorkbenchState(endpoint=node.base_url, token="token-ascii-ops", locale="en")
            )

            self.assertTrue(workbench.handle_command('workflow premium-review "review this secret workflow"'))
            self.assertIsNotNone(workbench.state.last_challenge)
            self.assertIn("payment required:", workbench.logs[-1])

            self.assertTrue(
                workbench.handle_command("issue-receipt did:agentcoin:ssh-ed25519:testpayer 0xabc123")
            )
            self.assertTrue(workbench.state.receipt_id)
            self.assertIsNotNone(workbench.state.last_receipt)
            self.assertIn("receipt issued:", workbench.logs[-1])

            self.assertTrue(workbench.handle_command("issue-renter-token premium-review premium-review 2"))
            self.assertIsNotNone(workbench.state.last_renter_token)
            self.assertIn("renter token issued:", workbench.logs[-1])

            self.assertTrue(workbench.handle_command("token-status"))
            self.assertIn("token status:", workbench.logs[-1])

            self.assertTrue(workbench.handle_command('workflow premium-review "review this secret workflow again"'))
            self.assertIn("workflow accepted:", workbench.logs[-1])

            self.assertTrue(workbench.handle_command("reconcile"))
            self.assertIn("reconcile=", workbench.logs[-1])

            rendered = workbench.render()
            self.assertIn("challenge_id:", rendered)
            self.assertIn("renter_token:", rendered)
            self.assertIn("reconciliation_status:", rendered)
        finally:
            node.stop()

    def test_ascii_workbench_supports_payment_proof_plan_and_queue_commands(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            local_controller_address="0x2222222222222222222222222222222222222222",
        )
        node = NodeHarness(
            node_id="ascii-proof-node",
            token="token-ascii-proof",
            db_path=str(Path(self.tempdir.name) / "ascii-proof.db"),
            capabilities=["worker"],
            signing_secret="ascii-proof-secret",
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
            workbench = AgentcoinAsciiWorkbench(
                WorkbenchState(endpoint=node.base_url, token="token-ascii-proof", locale="en")
            )

            self.assertTrue(workbench.handle_command('workflow premium-review "review this secret workflow"'))
            self.assertTrue(
                workbench.handle_command("issue-receipt did:agentcoin:ssh-ed25519:testpayer 0xabc123")
            )

            self.assertTrue(workbench.handle_command("build-proof"))
            self.assertIsNotNone(workbench.state.last_payment_proof)
            self.assertIn("payment proof:", workbench.logs[-1])

            self.assertTrue(workbench.handle_command("build-plan"))
            self.assertIsNotNone(workbench.state.last_payment_plan)
            self.assertIn("payment plan:", workbench.logs[-1])

            self.assertTrue(workbench.handle_command("queue-relay"))
            self.assertIsNotNone(workbench.state.last_payment_queue_item)
            self.assertIn("queued relay:", workbench.logs[-1])

            self.assertTrue(workbench.handle_command("queue-status"))
            self.assertIn("queue status:", workbench.logs[-1])

            rendered = workbench.render()
            self.assertIn("payment_proof:", rendered)
            self.assertIn("relay_queue_item:", rendered)
        finally:
            node.stop()

    def test_ascii_workbench_supports_latest_failed_and_replay_helper_commands(self) -> None:
        onchain = OnchainBindings(
            enabled=True,
            chain_id=97,
            rpc_url="https://bsc-testnet.example/rpc",
            bounty_escrow_address="0x1111111111111111111111111111111111111111",
            local_controller_address="0x2222222222222222222222222222222222222222",
        )
        node = NodeHarness(
            node_id="ascii-relay-node",
            token="token-ascii-relay",
            db_path=str(Path(self.tempdir.name) / "ascii-relay.db"),
            capabilities=["worker"],
            signing_secret="ascii-relay-secret",
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
            workbench = AgentcoinAsciiWorkbench(
                WorkbenchState(endpoint=node.base_url, token="token-ascii-relay", locale="en")
            )

            self.assertTrue(workbench.handle_command('workflow premium-review "review this secret workflow"'))
            self.assertTrue(
                workbench.handle_command("issue-receipt did:agentcoin:ssh-ed25519:testpayer 0xabc123")
            )
            relay_record = node.node.store.save_payment_relay(
                {
                    "receipt_id": workbench.state.receipt_id,
                    "workflow_name": "premium-review",
                    "completed_steps": 0,
                    "step_count": 1,
                    "stopped_on_error": True,
                    "final_status": "dead-letter",
                    "failures": [{"category": "rpc", "error": "mock relay failure"}],
                }
            )
            self.assertEqual(relay_record["final_status"], "dead-letter")

            self.assertTrue(workbench.handle_command("latest-failed"))
            self.assertIsNotNone(workbench.state.last_payment_failed_relay)
            self.assertIn("latest failed relay:", workbench.logs[-1])

            self.assertTrue(workbench.handle_command("replay-helper"))
            self.assertIsNotNone(workbench.state.last_payment_replay_helper)
            self.assertIn("replay helper:", workbench.logs[-1])

            rendered = workbench.render()
            self.assertIn("latest_failed:", rendered)
        finally:
            node.stop()


if __name__ == "__main__":
    unittest.main()
