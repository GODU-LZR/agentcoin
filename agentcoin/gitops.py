from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any


class GitWorkspace:
    def __init__(self, repo_path: str) -> None:
        self.repo_path = Path(repo_path).resolve()
        if not self.repo_path.exists():
            raise ValueError(f"git_root does not exist: {self.repo_path}")
        self.root = Path(self._git("rev-parse", "--show-toplevel")).resolve()

    def _git_result(self, *args: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result

    def _git(self, *args: str) -> str:
        result = self._git_result(*args)
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "git command failed"
            raise ValueError(stderr)
        return result.stdout.strip()

    def _git_optional(self, *args: str) -> str | None:
        result = self._git_result(*args)
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    @staticmethod
    def _sha256_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _changed_files_from_diff_output(output: str) -> list[str]:
        files: list[str] = []
        seen: set[str] = set()
        for line in output.splitlines():
            if not line.startswith("diff --git "):
                continue
            parts = line.split(" ")
            if len(parts) < 4:
                continue
            right = parts[3]
            if right.startswith("b/"):
                right = right[2:]
            if right not in seen:
                files.append(right)
                seen.add(right)
        return files

    def ref_sha(self, ref: str | None) -> str | None:
        if not ref:
            return None
        return self._git_optional("rev-parse", f"{ref}^{{commit}}")

    def merge_base(self, left_ref: str | None, right_ref: str | None) -> str | None:
        if not left_ref or not right_ref:
            return None
        return self._git_optional("merge-base", left_ref, right_ref)

    def _is_ancestor(self, ancestor_ref: str | None, descendant_ref: str | None) -> bool | None:
        if not ancestor_ref or not descendant_ref:
            return None
        result = self._git_result("merge-base", "--is-ancestor", ancestor_ref, descendant_ref)
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        return None

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

    def diff_hash(self, base_ref: str = "HEAD", target_ref: str | None = None) -> str:
        diff = self.diff(base_ref=base_ref, target_ref=target_ref, name_only=False)
        return self._sha256_text(str(diff["output"] or ""))

    def mergeability_snapshot(
        self,
        base_ref: str,
        target_ref: str,
        *,
        base_sha: str | None = None,
        target_sha: str | None = None,
        merge_base_sha: str | None = None,
    ) -> dict[str, Any]:
        base_sha = base_sha or self.ref_sha(base_ref)
        target_sha = target_sha or self.ref_sha(target_ref)
        merge_base_sha = merge_base_sha or self.merge_base(base_ref, target_ref)
        base_is_ancestor = self._is_ancestor(base_ref, target_ref)
        target_is_ancestor = self._is_ancestor(target_ref, base_ref)
        mergeable = None
        if base_is_ancestor is True or target_is_ancestor is True:
            mergeable = True
        return {
            "base_ref": base_ref,
            "target_ref": target_ref,
            "base_sha": base_sha,
            "target_sha": target_sha,
            "merge_base_sha": merge_base_sha,
            "base_is_ancestor_of_target": base_is_ancestor,
            "target_is_ancestor_of_base": target_is_ancestor,
            "mergeable": mergeable,
            "conflict_hint": None,
            "merge_tree_hash": None,
        }

    def task_context(self, base_ref: str = "HEAD", target_ref: str | None = None) -> dict[str, Any]:
        head_ref = self._git("symbolic-ref", "--short", "HEAD")
        refs = self._git_result(
            "rev-parse",
            "HEAD",
            f"{base_ref}^{{commit}}",
            *( [f"{target_ref}^{{commit}}"] if target_ref else [] ),
        )
        if refs.returncode != 0:
            stderr = refs.stderr.strip() or refs.stdout.strip() or "git command failed"
            raise ValueError(stderr)
        ref_lines = [line.strip() for line in refs.stdout.splitlines() if line.strip()]
        if len(ref_lines) < 2:
            raise ValueError("unable to resolve git refs")

        head_sha = ref_lines[0]
        base_sha = ref_lines[1]
        effective_target_ref = target_ref or head_ref
        target_sha = ref_lines[2] if target_ref and len(ref_lines) > 2 else head_sha

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

        diff_output = self.diff(base_ref=base_ref, target_ref=target_ref, name_only=False)["output"]
        changed_files = self._changed_files_from_diff_output(diff_output)
        merge_base_sha = self.merge_base(base_ref, target_ref) if target_ref else None
        return {
            "repo_root": str(self.root),
            "branch": head_ref,
            "head": head_sha,
            "head_ref": head_ref,
            "head_sha": head_sha,
            "commit_sha": head_sha,
            "base_ref": base_ref,
            "base_sha": base_sha,
            "target_ref": effective_target_ref,
            "target_sha": target_sha,
            "merge_base_sha": merge_base_sha,
            "is_dirty": bool(staged or unstaged or untracked),
            "changed_files": changed_files,
            "diff_hash": self._sha256_text(str(diff_output or "")),
            "mergeability": (
                self.mergeability_snapshot(
                    base_ref,
                    target_ref,
                    base_sha=base_sha,
                    target_sha=target_sha,
                    merge_base_sha=merge_base_sha,
                )
                if target_ref
                else None
            ),
        }

    def merge_proof_context(
        self,
        *,
        base_ref: str,
        target_ref: str,
        parent_contexts: list[dict[str, Any]] | None = None,
        parent_task_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        context = self.task_context(base_ref=base_ref, target_ref=target_ref)
        context["proof_bundle"] = {
            "kind": "git-proof-bundle",
            "repo_root": context["repo_root"],
            "base_ref": context["base_ref"],
            "base_sha": context["base_sha"],
            "head_ref": context["head_ref"],
            "head_sha": context["head_sha"],
            "target_ref": context["target_ref"],
            "target_sha": context["target_sha"],
            "merge_base_sha": context["merge_base_sha"],
            "diff_hash": context["diff_hash"],
            "changed_files": list(context["changed_files"]),
            "parent_task_ids": list(parent_task_ids or []),
            "parent_contexts": list(parent_contexts or []),
            "mergeability": dict(context["mergeability"] or {}),
        }
        return context
