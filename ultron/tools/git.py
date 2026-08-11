"""Git operations tools for Ultron."""

from __future__ import annotations

import subprocess

from ultron.tools.base import Tool, ToolResult
from ultron.utils import truncate

_MAX_OUTPUT = 4000


class GitStatusTool(Tool):
    """Show the working tree status."""

    name = "git_status"
    description = (
        "Show the git status of the current or specified directory. "
        "Example: git_status(/Users/me/project)"
    )

    def run(self, arg: str) -> ToolResult:
        cwd = arg.strip() or None
        try:
            result = subprocess.run(
                ["git", "status", "--short", "--branch"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                cwd=cwd,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(False, f"git status failed: {exc}")
        if result.returncode != 0:
            return ToolResult(False, f"git status failed: {result.stderr.strip()}")
        return ToolResult(True, truncate(result.stdout.strip(), _MAX_OUTPUT))


class GitDiffTool(Tool):
    """Show uncommitted changes."""

    name = "git_diff"
    description = (
        "Show git diff (uncommitted changes) for the current or specified directory. "
        "Example: git_diff(/Users/me/project)"
    )

    def run(self, arg: str) -> ToolResult:
        cwd = arg.strip() or None
        try:
            result = subprocess.run(
                ["git", "diff", "--stat"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                cwd=cwd,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(False, f"git diff failed: {exc}")
        if result.returncode != 0:
            return ToolResult(False, f"git diff failed: {result.stderr.strip()}")
        output = result.stdout.strip()
        if not output:
            return ToolResult(True, "No uncommitted changes.")
        return ToolResult(True, truncate(output, _MAX_OUTPUT))


class GitLogTool(Tool):
    """Show recent commit history."""

    name = "git_log"
    description = "Show recent git commits. Example: git_log(/Users/me/project)"

    def run(self, arg: str) -> ToolResult:
        cwd = arg.strip() or None
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-20", "--no-decorate"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                cwd=cwd,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(False, f"git log failed: {exc}")
        if result.returncode != 0:
            return ToolResult(False, f"git log failed: {result.stderr.strip()}")
        return ToolResult(True, truncate(result.stdout.strip(), _MAX_OUTPUT))


class GitCommitTool(Tool):
    """Stage all changes and commit with a message."""

    name = "git_commit"
    description = (
        "Stage all changes and create a git commit. "
        "Argument: commit message. "
        "Example: git_commit(fix: resolve null pointer in parser)"
    )
    result_is_final = True

    def run(self, arg: str) -> ToolResult:
        message = arg.strip()
        if not message:
            return ToolResult(False, "No commit message given.")
        try:
            # Stage all changes
            stage = subprocess.run(
                ["git", "add", "-A"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if stage.returncode != 0:
                return ToolResult(False, f"git add failed: {stage.stderr.strip()}")
            # Commit
            commit = subprocess.run(
                ["git", "commit", "-m", message],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if commit.returncode != 0:
                return ToolResult(False, f"git commit failed: {commit.stderr.strip()}")
            return ToolResult(True, f"Committed: {message}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(False, f"git commit failed: {exc}")


class GitBranchTool(Tool):
    """List or create git branches."""

    name = "git_branch"
    description = (
        "List branches (no argument) or create a new branch. "
        "Example: git_branch(feature/new-agent)"
    )

    def run(self, arg: str) -> ToolResult:
        branch_name = arg.strip()
        try:
            if not branch_name:
                result = subprocess.run(
                    ["git", "branch", "-a", "--no-color"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if result.returncode != 0:
                    return ToolResult(
                        False, f"git branch failed: {result.stderr.strip()}"
                    )
                return ToolResult(True, result.stdout.strip())
            else:
                result = subprocess.run(
                    ["git", "checkout", "-b", branch_name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if result.returncode != 0:
                    return ToolResult(
                        False, f"git branch failed: {result.stderr.strip()}"
                    )
                return ToolResult(
                    True, f"Created and switched to branch: {branch_name}"
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(False, f"git branch failed: {exc}")
