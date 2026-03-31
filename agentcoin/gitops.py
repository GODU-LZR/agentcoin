from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


class GitWorkspace:
    def __init__(self, repo_path: str) -> None:
        self.repo_path = Path(repo_path).resolve()
        if not self.repo_path.exists():
            raise ValueError(f"git_root does not exist: {self.repo_path}")
        self.root = Path(self._git("rev-parse", "--show-toplevel")).resolve()

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "git command failed"
            raise ValueError(stderr)
        return result.stdout.strip()

    def status(self) -> dict[str, Any]:
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        head = self._git("rev-parse", "HEAD")
        porcelain = self._git("status", "--porcelain=1")
        staged: list[str] = []
        unstaged: list[str] = []
        untracked: list[str] = []
        for line in [item for item in porcelain.splitlines() if item.strip()]:
            code = line[:2]
            path = line[2:].strip()
            if code == "??":
                untracked.append(path)
                continue
            if code[0] != " ":
                staged.append(path)
            if code[1] != " ":
                unstaged.append(path)
        return {
            "root": str(self.root),
            "branch": branch,
            "head": head,
            "is_dirty": bool(staged or unstaged or untracked),
            "staged_files": staged,
            "unstaged_files": unstaged,
            "untracked_files": untracked,
        }

    def create_branch(self, name: str, from_ref: str = "HEAD", checkout: bool = False) -> dict[str, Any]:
        branch_name = str(name).strip()
        if not branch_name:
            raise ValueError("branch name is required")
        if checkout:
            self._git("checkout", "-B", branch_name, from_ref)
        else:
            self._git("branch", branch_name, from_ref)
        return {
            "branch": branch_name,
            "from_ref": from_ref,
            "checked_out": checkout,
            "status": self.status(),
        }

    def diff(self, base_ref: str = "HEAD", target_ref: str | None = None, name_only: bool = False) -> dict[str, Any]:
        args = ["diff"]
        if name_only:
            args.append("--name-only")
        args.append(base_ref)
        if target_ref:
            args.append(target_ref)
        output = self._git(*args)
        return {
            "base_ref": base_ref,
            "target_ref": target_ref,
            "name_only": name_only,
            "output": output,
            "files": [line for line in output.splitlines() if line.strip()] if name_only else [],
        }

    def task_context(self, base_ref: str = "HEAD", target_ref: str | None = None) -> dict[str, Any]:
        status = self.status()
        diff_files = self.diff(base_ref=base_ref, target_ref=target_ref, name_only=True)
        return {
            "repo_root": status["root"],
            "branch": status["branch"],
            "head": status["head"],
            "base_ref": base_ref,
            "target_ref": target_ref,
            "is_dirty": status["is_dirty"],
            "changed_files": diff_files["files"],
        }
