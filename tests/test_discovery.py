from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentcoin.discovery import LocalAgentDiscovery


class LocalAgentDiscoveryTests(unittest.TestCase):
    def test_discovers_windows_copilot_cli_and_vscode_agent_extensions(self) -> None:
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
            codex_json = home / ".vscode" / "extensions" / "openai.chatgpt-26.5401.11717-win32-x64" / "package.json"
            codex_json.parent.mkdir(parents=True, exist_ok=True)
            codex_json.write_text(
                json.dumps(
                    {
                        "name": "chatgpt",
                        "publisher": "openai",
                        "version": "26.5401.11717",
                        "displayName": "Codex – OpenAI’s coding agent",
                    }
                ),
                encoding="utf-8",
            )
            cline_json = home / ".vscode" / "extensions" / "saoudrizwan.claude-dev-3.77.0" / "package.json"
            cline_json.parent.mkdir(parents=True, exist_ok=True)
            cline_json.write_text(
                json.dumps(
                    {
                        "name": "claude-dev",
                        "publisher": "saoudrizwan",
                        "version": "3.77.0",
                        "displayName": "Cline",
                    }
                ),
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
            self.assertIn("openai-codex-vscode", ids)
            self.assertIn("cline-vscode", ids)

            cli_item = [item for item in items if item["id"] == "github-copilot-cli"][0]
            self.assertEqual(cli_item["version"], "1.0.17")
            self.assertIn("acp", cli_item["protocols"])
            self.assertEqual(cli_item["agentcoin_compatibility"]["preferred_integration"], "acp-bridge")
            self.assertEqual(cli_item["agentcoin_compatibility"]["launch_hint"][0], str(executable))
            codex_item = [item for item in items if item["id"] == "openai-codex-vscode"][0]
            self.assertEqual(codex_item["publisher"], "openai")
            self.assertEqual(codex_item["display_name"], "Codex – OpenAI’s coding agent")
            cline_item = [item for item in items if item["id"] == "cline-vscode"][0]
            self.assertEqual(cline_item["display_name"], "Cline")

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
            codex_json = home / ".vscode-server" / "extensions" / "openai.chatgpt-26.5401.11717-linux-x64" / "package.json"
            codex_json.parent.mkdir(parents=True, exist_ok=True)
            codex_json.write_text(
                json.dumps({"name": "chatgpt", "publisher": "openai", "version": "26.5401.11717"}),
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
            self.assertIn("openai-codex-vscode", ids)

            cli_item = [item for item in items if item["id"] == "github-copilot-cli"][0]
            self.assertTrue(cli_item["wsl"])
            self.assertFalse(cli_item["agentcoin_compatibility"]["attachable_today"])


if __name__ == "__main__":
    unittest.main()
