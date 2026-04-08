from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentcoin.discovery import LocalAgentDiscovery


class LocalAgentDiscoveryTests(unittest.TestCase):
    def test_windows_copilot_prefers_real_executable_over_bat_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            local_appdata = root / "AppData" / "Local"
            home = root / "home"
            wrapper = root / "shim" / "copilot.BAT"
            wrapper.parent.mkdir(parents=True, exist_ok=True)
            wrapper.write_text("", encoding="utf-8")
            executable = local_appdata / "GitHub CLI" / "copilot" / "copilot.exe"
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("", encoding="utf-8")

            package_json = local_appdata / "copilot" / "pkg" / "win32-x64" / "1.0.17" / "package.json"
            package_json.parent.mkdir(parents=True, exist_ok=True)
            package_json.write_text(
                json.dumps({"name": "@github/copilot", "version": "1.0.17"}),
                encoding="utf-8",
            )

            def fake_runner(command: list[str]) -> tuple[int, str, str]:
                if command[0] == str(wrapper):
                    return 1, "", "interactive wrapper prompt"
                if command[0] == str(executable) and command[-1] == "--help":
                    return 0, "GitHub Copilot CLI\n  --acp  Start as Agent Client Protocol server\n", ""
                if command[0] == str(executable) and command[-1] == "--version":
                    return 0, "1.0.17", ""
                return 1, "", "unsupported"

            discovery = LocalAgentDiscovery(
                env={"LOCALAPPDATA": str(local_appdata)},
                home=home,
                system_name="Windows",
                which=lambda name: str(wrapper) if name == "copilot" else None,
                command_runner=fake_runner,
            )

            items = discovery.discover()
            cli_item = [item for item in items if item["id"] == "github-copilot-cli"][0]
            self.assertEqual(cli_item["executable_path"], str(executable))
            self.assertIn("acp", cli_item["protocols"])
            self.assertTrue(cli_item["agentcoin_compatibility"]["attachable_today"])
            self.assertEqual(cli_item["agentcoin_compatibility"]["preferred_integration"], "acp-bridge")
            self.assertEqual(cli_item["agentcoin_compatibility"]["launch_hint"], [str(executable), "--acp"])

    def test_discovers_windows_copilot_cli_and_vscode_agent_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            local_appdata = root / "AppData" / "Local"
            program_files = root / "Program Files"
            home = root / "home"
            executable = local_appdata / "GitHub CLI" / "copilot" / "copilot.exe"
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("", encoding="utf-8")
            claude_executable = local_appdata / "Programs" / "Claude Code" / "claude.exe"
            claude_executable.parent.mkdir(parents=True, exist_ok=True)
            claude_executable.write_text("", encoding="utf-8")
            codex_executable = program_files / "nodejs" / "codex.cmd"
            codex_executable.parent.mkdir(parents=True, exist_ok=True)
            codex_executable.write_text("", encoding="utf-8")

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
                if command[0] == str(claude_executable) and command[-1] == "--help":
                    return 0, "Claude Code CLI\n  --mcp  Start Model Context Protocol transport\n", ""
                if command[0] == str(claude_executable) and command[-1] == "--version":
                    return 0, "0.9.3", ""
                if command[0] == str(codex_executable) and command[-1] == "--help":
                    return 0, "Codex CLI\n  mcp-server  Start Codex as an MCP server (stdio)\n", ""
                if command[0] == str(codex_executable) and command[-1] == "--version":
                    return 0, "codex-cli 0.118.0", ""
                if command[-1] == "--help":
                    return 0, "GitHub Copilot CLI\n  --acp  Start as Agent Client Protocol server\n", ""
                if command[-1] == "--version":
                    return 0, "1.0.17", ""
                return 1, "", "unsupported"

            discovery = LocalAgentDiscovery(
                env={"LOCALAPPDATA": str(local_appdata), "PROGRAMFILES": str(program_files)},
                home=home,
                system_name="Windows",
                which=lambda name: (
                    str(executable)
                    if name == "copilot"
                    else (str(claude_executable) if name == "claude" else (str(codex_executable) if name in {"codex", "codex.cmd"} else None))
                ),
                command_runner=fake_runner,
            )
            items = discovery.discover()
            ids = {item["id"] for item in items}
            self.assertIn("github-copilot-cli", ids)
            self.assertIn("openai-codex-cli", ids)
            self.assertIn("claude-code-cli", ids)
            self.assertIn("github-copilot-chat-vscode", ids)
            self.assertIn("openai-codex-vscode", ids)
            self.assertIn("cline-vscode", ids)

            cli_item = [item for item in items if item["id"] == "github-copilot-cli"][0]
            self.assertEqual(cli_item["version"], "1.0.17")
            self.assertIn("acp", cli_item["protocols"])
            self.assertEqual(cli_item["agentcoin_compatibility"]["preferred_integration"], "acp-bridge")
            self.assertEqual(cli_item["agentcoin_compatibility"]["launch_hint"][0], str(executable))
            codex_cli_item = [item for item in items if item["id"] == "openai-codex-cli"][0]
            self.assertEqual(codex_cli_item["version"], "codex-cli 0.118.0")
            self.assertIn("mcp", codex_cli_item["protocols"])
            self.assertEqual(codex_cli_item["publisher"], "OpenAI")
            self.assertEqual(codex_cli_item["agentcoin_compatibility"]["preferred_integration"], "mcp-host-adapter")
            self.assertEqual(codex_cli_item["agentcoin_compatibility"]["launch_hint"], [str(codex_executable), "mcp-server"])
            claude_item = [item for item in items if item["id"] == "claude-code-cli"][0]
            self.assertEqual(claude_item["version"], "0.9.3")
            self.assertIn("mcp", claude_item["protocols"])
            self.assertEqual(claude_item["agentcoin_compatibility"]["preferred_integration"], "mcp-host-adapter")
            self.assertEqual(claude_item["agentcoin_compatibility"]["launch_hint"][0], str(claude_executable))
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
            claude_executable = home / ".local" / "bin" / "claude"
            claude_executable.parent.mkdir(parents=True, exist_ok=True)
            claude_executable.write_text("", encoding="utf-8")

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
                which=lambda name: str(claude_executable) if name == "claude" else None,
                command_runner=lambda command: (0, "Claude Code CLI\n", "") if command[0] == str(claude_executable) and command[-1] == "--help" else ((0, "0.9.3", "") if command[0] == str(claude_executable) and command[-1] == "--version" else (1, "", "not-found")),
            )
            items = discovery.discover()
            ids = {item["id"] for item in items}
            self.assertIn("github-copilot-cli", ids)
            self.assertIn("claude-code-cli", ids)
            self.assertIn("github-copilot-chat-vscode", ids)
            self.assertIn("openai-codex-vscode", ids)

            cli_item = [item for item in items if item["id"] == "github-copilot-cli"][0]
            self.assertTrue(cli_item["wsl"])
            self.assertFalse(cli_item["agentcoin_compatibility"]["attachable_today"])
            claude_item = [item for item in items if item["id"] == "claude-code-cli"][0]
            self.assertTrue(claude_item["wsl"])
            self.assertEqual(claude_item["agentcoin_compatibility"]["preferred_integration"], "cli-wrapper")


if __name__ == "__main__":
    unittest.main()
