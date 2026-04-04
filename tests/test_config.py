from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentcoin.config import load_config, persist_peer_identity_config, preview_peer_identity_config_update


class ConfigTests(unittest.TestCase):
    def test_load_config_bootstraps_local_identity_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "node.json"
            config_path.write_text(
                json.dumps(
                    {
                        "node_id": "bootstrap-node",
                        "auth_token": "token-bootstrap",
                        "database_path": "./var/agentcoin.db",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config(str(config_path))

            self.assertEqual(config.identity_principal, "bootstrap-node")
            self.assertTrue(Path(str(config.identity_private_key_path)).exists())
            self.assertTrue(Path(f"{config.identity_private_key_path}.pub").exists())
            self.assertTrue(str(config.resolved_identity_public_key or "").startswith("ssh-ed25519 "))
            self.assertTrue(str(config.resolved_local_did or "").startswith("did:agentcoin:ssh-ed25519:"))

    def test_load_config_sets_resolved_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "node.json"
            config_path.write_text(
                json.dumps(
                    {
                        "node_id": "config-node",
                        "auth_token": "token-config",
                        "peers": [
                            {
                                "peer_id": "peer-b",
                                "name": "Peer B",
                                "url": "http://127.0.0.1:8081",
                                "identity_principal": "peer-b",
                                "identity_public_key": "ssh-ed25519 AAAATESTOLD peer-b",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config(str(config_path))

            self.assertEqual(config.node_id, "config-node")
            self.assertEqual(config.config_path, str(config_path.resolve()))
            self.assertEqual(len(config.peers), 1)
            self.assertEqual(config.peers[0].peer_id, "peer-b")

    def test_load_config_accepts_allowed_frontend_origins_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "node.json"
            config_path.write_text(
                json.dumps(
                    {
                        "node_id": "cors-node",
                        "auth_token": "token-cors",
                        "ALLOWED_FRONTEND_ORIGINS": [
                            "https://app.agentcoin.network",
                            "http://127.0.0.1:3000",
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config(str(config_path))

            self.assertEqual(
                config.allowed_frontend_origins,
                ["https://app.agentcoin.network", "http://127.0.0.1:3000"],
            )
            self.assertEqual(
                config.effective_cors_allowed_origins,
                ["https://app.agentcoin.network", "http://127.0.0.1:3000"],
            )
            self.assertEqual(
                config.cors_allowed_origins,
                ["https://app.agentcoin.network", "http://127.0.0.1:3000"],
            )

    def test_persist_peer_identity_config_updates_target_peer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "node.json"
            config_path.write_text(
                json.dumps(
                    {
                        "node_id": "config-node",
                        "auth_token": "token-config",
                        "peers": [
                            {
                                "peer_id": "peer-b",
                                "name": "Peer B",
                                "url": "http://127.0.0.1:8081",
                                "identity_principal": "peer-b",
                                "identity_public_key": "ssh-ed25519 AAAATESTOLD peer-b",
                            },
                            {
                                "peer_id": "peer-c",
                                "name": "Peer C",
                                "url": "http://127.0.0.1:8082",
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            result = persist_peer_identity_config(
                str(config_path),
                peer_id="peer-b",
                principal="peer-b-next",
                trusted_public_keys=[
                    "ssh-ed25519 AAAATESTNEW peer-b",
                    "ssh-ed25519 AAAATESTNEXT peer-b-next",
                ],
                revoked_public_keys=["ssh-ed25519 AAAATESTOLD peer-b"],
            )

            self.assertEqual(result["config_path"], str(config_path.resolve()))
            stored = json.loads(config_path.read_text(encoding="utf-8"))
            peer_b = [item for item in stored["peers"] if item["peer_id"] == "peer-b"][0]
            peer_c = [item for item in stored["peers"] if item["peer_id"] == "peer-c"][0]

            self.assertEqual(peer_b["identity_principal"], "peer-b-next")
            self.assertEqual(peer_b["identity_public_key"], "ssh-ed25519 AAAATESTNEW peer-b")
            self.assertEqual(peer_b["identity_public_keys"], ["ssh-ed25519 AAAATESTNEXT peer-b-next"])
            self.assertEqual(peer_b["identity_revoked_public_keys"], ["ssh-ed25519 AAAATESTOLD peer-b"])
            self.assertNotIn("identity_public_key", peer_c)

    def test_preview_peer_identity_config_update_returns_diff_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "node.json"
            original_payload = {
                "node_id": "config-node",
                "auth_token": "token-config",
                "peers": [
                    {
                        "peer_id": "peer-b",
                        "name": "Peer B",
                        "url": "http://127.0.0.1:8081",
                        "identity_principal": "peer-b",
                        "identity_public_key": "ssh-ed25519 AAAATESTOLD peer-b",
                    }
                ],
            }
            config_path.write_text(json.dumps(original_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            preview = preview_peer_identity_config_update(
                str(config_path),
                peer_id="peer-b",
                principal="peer-b-next",
                trusted_public_keys=[
                    "ssh-ed25519 AAAATESTNEW peer-b",
                    "ssh-ed25519 AAAATESTNEXT peer-b-next",
                ],
                revoked_public_keys=["ssh-ed25519 AAAATESTOLD peer-b"],
            )

            self.assertTrue(preview["changed"])
            self.assertEqual(preview["before_peer"]["identity_public_key"], "ssh-ed25519 AAAATESTOLD peer-b")
            self.assertEqual(preview["after_peer"]["identity_public_key"], "ssh-ed25519 AAAATESTNEW peer-b")
            self.assertIn("identity_public_keys", preview["diff"])
            self.assertIn("identity_revoked_public_keys", preview["diff"])

            stored = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(stored, original_payload)


if __name__ == "__main__":
    unittest.main()
