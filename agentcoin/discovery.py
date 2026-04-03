from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable


CommandRunner = Callable[[list[str]], tuple[int, str, str]]


def _default_command_runner(command: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return int(completed.returncode), str(completed.stdout or ""), str(completed.stderr or "")


class LocalAgentDiscovery:
    def __init__(
        self,
        *,
        env: dict[str, str] | None = None,
        home: Path | None = None,
        system_name: str | None = None,
        which: Callable[[str], str | None] | None = None,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.env = dict(env or os.environ)
        self.home = Path(home or Path.home())
        self.system_name = str(system_name or platform.system() or "").strip() or "Unknown"
        self.which = which or shutil.which
        self.command_runner = command_runner or _default_command_runner

    @property
    def is_wsl(self) -> bool:
        if str(self.env.get("WSL_DISTRO_NAME") or "").strip():
            return True
        release = str(self.env.get("WSL_INTEROP") or "").strip()
        if release:
            return True
        try:
            text = platform.release()
        except Exception:
            return False
        return "microsoft" in str(text).lower()

    def discover(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        items.extend(self._discover_copilot_cli())
        items.extend(self._discover_vscode_copilot_chat())
        items.sort(key=lambda item: (str(item.get("family") or ""), str(item.get("title") or ""), str(item.get("id") or "")))
        return items

    def _discover_copilot_cli(self) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        executable_path = self.which("copilot")
        if executable_path:
            evidence.append({"kind": "which", "path": executable_path})
        for candidate in self._copilot_cli_candidates():
            normalized = str(candidate).strip()
            if normalized and not any(item.get("path") == normalized for item in evidence):
                evidence.append({"kind": "path", "path": normalized})

        package_version = ""
        package_path = ""
        for package_json in self._copilot_package_json_candidates():
            if not package_json.is_file():
                continue
            try:
                payload = json.loads(package_json.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(payload.get("name") or "").strip() != "@github/copilot":
                continue
            package_version = str(payload.get("version") or "").strip()
            package_path = str(package_json)
            evidence.append({"kind": "package-json", "path": package_path, "version": package_version})
            break

        if not evidence:
            return []

        resolved_executable = next((str(item.get("path") or "").strip() for item in evidence if item.get("kind") in {"which", "path"}), "")
        help_text = ""
        version_text = package_version
        supports_acp = False
        if resolved_executable:
            return_code, stdout, stderr = self._safe_run([resolved_executable, "--help"])
            help_text = f"{stdout}\n{stderr}".strip()
            supports_acp = "--acp" in help_text
            version_code, version_stdout, version_stderr = self._safe_run([resolved_executable, "--version"])
            if version_code == 0:
                version_text = str(version_stdout or version_stderr).strip() or version_text
            evidence.append(
                {
                    "kind": "probe",
                    "path": resolved_executable,
                    "supports_acp": supports_acp,
                    "probe_ok": return_code == 0,
                }
            )

        return [
            {
                "id": "github-copilot-cli",
                "family": "github-copilot",
                "title": "GitHub Copilot CLI",
                "type": "local-cli-agent",
                "publisher": "GitHub",
                "discovery_platform": self.system_name.lower(),
                "wsl": self.is_wsl,
                "version": version_text,
                "executable_path": resolved_executable or None,
                "package_path": package_path or None,
                "protocols": ["acp"] if supports_acp else [],
                "capabilities": [
                    "interactive-chat",
                    "non-interactive-prompt",
                    "code-editing",
                    "shell-execution",
                ],
                "agentcoin_compatibility": {
                    "discovered": True,
                    "attachable_today": False,
                    "preferred_integration": "acp-bridge" if supports_acp else "cli-wrapper",
                    "integration_candidates": ["acp-bridge", "cli-wrapper"] if supports_acp else ["cli-wrapper"],
                    "launch_hint": [resolved_executable, "--acp"] if resolved_executable and supports_acp else [],
                    "notes": [
                        "Detected locally, but AgentCoin does not yet expose a first-class ACP bridge runtime.",
                        "ACP is the cleanest future join path for Copilot CLI if a bridge is added.",
                    ],
                },
                "evidence": evidence,
                "help_summary": "GitHub Copilot CLI with ACP support detected." if supports_acp else "GitHub Copilot CLI detected.",
            }
        ]

    def _discover_vscode_copilot_chat(self) -> list[dict[str, Any]]:
        for root in self._vscode_extension_roots():
            if not root.exists():
                continue
            for extension_dir in root.glob("github.copilot-chat-*"):
                package_json = extension_dir / "package.json"
                if not package_json.is_file():
                    continue
                try:
                    payload = json.loads(package_json.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if str(payload.get("name") or "").strip() != "copilot-chat":
                    continue
                return [
                    {
                        "id": "github-copilot-chat-vscode",
                        "family": "github-copilot",
                        "title": "GitHub Copilot Chat VS Code Extension",
                        "type": "editor-extension",
                        "publisher": str(payload.get("publisher") or "GitHub"),
                        "discovery_platform": self.system_name.lower(),
                        "wsl": self.is_wsl,
                        "version": str(payload.get("version") or "").strip(),
                        "extension_path": str(extension_dir),
                        "protocols": [],
                        "capabilities": ["editor-chat", "workspace-tools"],
                        "agentcoin_compatibility": {
                            "discovered": True,
                            "attachable_today": False,
                            "preferred_integration": "vscode-host-adapter",
                            "integration_candidates": ["vscode-host-adapter", "mcp-host-adapter"],
                            "notes": [
                                "Detected as a VS Code extension, not a standalone AgentCoin node.",
                                "This needs a host-side adapter rather than direct peer registration.",
                            ],
                        },
                        "evidence": [
                            {
                                "kind": "vscode-extension",
                                "path": str(extension_dir),
                            }
                        ],
                    }
                ]
        return []

    def _copilot_cli_candidates(self) -> list[str]:
        candidates: list[str] = []
        if self.system_name.lower() == "windows":
            local_appdata = Path(str(self.env.get("LOCALAPPDATA") or "").strip() or self.home / "AppData" / "Local")
            candidates.extend(
                [
                    str(local_appdata / "GitHub CLI" / "copilot" / "copilot.exe"),
                    str(local_appdata / "Programs" / "GitHub CLI" / "copilot.exe"),
                ]
            )
        elif self.system_name.lower() == "darwin":
            app_support = self.home / "Library" / "Application Support"
            candidates.extend(
                [
                    str(app_support / "GitHub CLI" / "copilot" / "copilot"),
                    str(app_support / "copilot" / "bin" / "copilot"),
                    str(self.home / ".local" / "bin" / "copilot"),
                    "/usr/local/bin/copilot",
                    "/opt/homebrew/bin/copilot",
                ]
            )
        else:
            candidates.extend(
                [
                    str(self.home / ".local" / "share" / "GitHub CLI" / "copilot" / "copilot"),
                    str(self.home / ".local" / "bin" / "copilot"),
                    str(self.home / ".copilot" / "bin" / "copilot"),
                    "/usr/local/bin/copilot",
                    "/usr/bin/copilot",
                ]
            )
        return [candidate for candidate in candidates if candidate]

    def _copilot_package_json_candidates(self) -> list[Path]:
        roots: list[Path] = []
        system = self.system_name.lower()
        if system == "windows":
            roots.append(Path(str(self.env.get("LOCALAPPDATA") or "").strip() or self.home / "AppData" / "Local") / "copilot" / "pkg")
        elif system == "darwin":
            roots.extend(
                [
                    self.home / "Library" / "Application Support" / "copilot" / "pkg",
                    self.home / ".local" / "share" / "copilot" / "pkg",
                ]
            )
        else:
            roots.extend(
                [
                    self.home / ".local" / "share" / "copilot" / "pkg",
                    self.home / ".copilot" / "pkg",
                ]
            )
        package_jsons: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            package_jsons.extend(root.glob("*/*/package.json"))
        return package_jsons

    def _vscode_extension_roots(self) -> list[Path]:
        roots = [self.home / ".vscode" / "extensions"]
        if self.is_wsl:
            roots.append(self.home / ".vscode-server" / "extensions")
        return roots

    def _safe_run(self, command: list[str]) -> tuple[int, str, str]:
        try:
            return self.command_runner(command)
        except Exception as exc:
            return 1, "", str(exc)
