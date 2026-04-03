from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentcoin.discovery import LocalAgentDiscovery


class LocalAgentDiscoveryTests(unittest.TestCase):
    def test_discovers_windows_copilot_cli_and_vscode_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            local_appdata = root / "AppData" / "Local"
            home = root / "home"
            executable = local_appdata / "GitHub CLI" / "copilot" / "copilot.exe"
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("", encoding="utf-8")

            package_json = local_appdata / "copilot" / "pkg" / "win32-x64" / "1.0.17" / "package.json"
            package_json.parent.mkdir(parents=True, exist_ok=True)
            package_json.write_text(
                json.dumps({"name": "@github/copilot", "version": "1.0.17"}),
                encoding="utf-8",
            )

            extension_json = home / ".vscode" / "extensions" / "github.copilot-chat-0.42.3" / "package.json"
            extension_json.parent.mkdir(parents=True, exist_ok=True)
            extension_json.write_text(
                json.dumps({"name": "copilot-chat", "publisher": "GitHub", "version": "0.42.3"}),
                encoding="utf-8",
            )

            def fake_runner(command: list[str]) -> tuple[int, str, str]:
                if command[-1] == "--help":
                    return 0, "GitHub Copilot CLI\n  --acp  Start as Agent Client Protocol server\n", ""
                if command[-1] == "--version":
                    return 0, "1.0.17", ""
                return 1, "", "unsupported"

            discovery = LocalAgentDiscovery(
                env={"LOCALAPPDATA": str(local_appdata)},
                home=home,
                system_name="Windows",
                which=lambda name: str(executable) if name == "copilot" else None,
                command_runner=fake_runner,
            )
            items = discovery.discover()
            ids = {item["id"] for item in items}
            self.assertIn("github-copilot-cli", ids)
            self.assertIn("github-copilot-chat-vscode", ids)

            cli_item = [item for item in items if item["id"] == "github-copilot-cli"][0]
            self.assertEqual(cli_item["version"], "1.0.17")
            self.assertIn("acp", cli_item["protocols"])
            self.assertEqual(cli_item["agentcoin_compatibility"]["preferred_integration"], "acp-bridge")
            self.assertEqual(cli_item["agentcoin_compatibility"]["launch_hint"][0], str(executable))

    def test_discovers_wsl_vscode_extension_and_linux_package_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            home = root / "home"
            package_json = home / ".local" / "share" / "copilot" / "pkg" / "linux-x64" / "1.0.17" / "package.json"
            package_json.parent.mkdir(parents=True, exist_ok=True)
            package_json.write_text(
                json.dumps({"name": "@github/copilot", "version": "1.0.17"}),
                encoding="utf-8",
            )

            extension_json = home / ".vscode-server" / "extensions" / "github.copilot-chat-0.42.3" / "package.json"
            extension_json.parent.mkdir(parents=True, exist_ok=True)
            extension_json.write_text(
                json.dumps({"name": "copilot-chat", "publisher": "GitHub", "version": "0.42.3"}),
                encoding="utf-8",
            )

            discovery = LocalAgentDiscovery(
                env={"WSL_DISTRO_NAME": "Ubuntu"},
                home=home,
                system_name="Linux",
                which=lambda name: None,
                command_runner=lambda command: (1, "", "not-found"),
            )
            items = discovery.discover()
            ids = {item["id"] for item in items}
            self.assertIn("github-copilot-cli", ids)
            self.assertIn("github-copilot-chat-vscode", ids)

            cli_item = [item for item in items if item["id"] == "github-copilot-cli"][0]
            self.assertTrue(cli_item["wsl"])
            self.assertFalse(cli_item["agentcoin_compatibility"]["attachable_today"])


if __name__ == "__main__":
    unittest.main()
