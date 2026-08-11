"""The self-modification tool (Day 6): scoped, tested, rolled back.

``self_modify_code`` is a ``SYSTEM``-tier, ``destructive=True`` tool, so it
goes through the Day 4 PermissionGate like every other tool — Ultron proposes
a change and states its reasoning; it never silently rewrites itself. The
write itself is protected by three layers:

1. **Scope allowlist** — only files Ultron is allowed to propose edits to.
2. **Edit lock** — refuses to run while the coding agent holds the repo.
3. **Git snapshot + test gate** — a failed test run rolls the file back.

The test runner is injectable so unit tests can substitute a fake; the
default runs ``pytest -q`` in the repository.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from ultron.action.permissions import PermissionTier
from ultron.tools.base import Tool, ToolResult

# Argument format mirrors the other file tools: "<path> :: <reason> :: <content>".
_SEPARATOR = " :: "

# Files Ultron may propose to change on its own (relative to the repo root).
# Kept explicit and auditable — the allowlist check happens before the write,
# not as a documented convention.
_MAY_SELF_EDIT = (
    "ultron/config.py",  # its own config values, within validated ranges
    "ultron/persona/style_rules.py",  # persona style rules
    "ultron/probes/",  # probe thresholds (idle timeout, CPU pressure, ...)
    "ultron/memory/store.py",  # data entries only — never schema migrations
)

# Paths Ultron must never self-edit, even if they match a prefix above.
_MUST_NEVER = (
    "ultron/action/",  # the safety layer itself
    "ultron/selfmod/",  # the machinery that keeps self-edits safe
    "ultron/action/permissions.py",
    ".env",
    "packaging/",  # launchd plist / supervision logic
    "tests/",  # it may run tests, not rewrite them to pass
)


def _resolve_repo_relative(repo_path: Path, raw: str) -> Path:
    """Resolve ``raw`` against the repo root, refusing escapes."""
    candidate = (repo_path / raw).resolve()
    repo_root = repo_path.resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(
            f"Self-edit path {raw!r} escapes the repository — refused."
        ) from exc
    return candidate


def _in_scope(rel: Path | str) -> bool:
    """True when the repository-relative path is on the allowlist."""
    rel = Path(rel)
    if any(rel.is_relative_to(Path(p)) for p in _MUST_NEVER):
        return False
    for allowed in _MAY_SELF_EDIT:
        if rel == Path(allowed) or rel.is_relative_to(Path(allowed)):
            return True
    return False


def _run_pytest(repo_path: Path, logger: logging.Logger) -> tuple[bool, str]:
    """Run the existing test suite; returns (passed, tail-of-output)."""
    result = subprocess.run(
        ["pytest", "-q"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=600,
    )
    tail = (result.stdout or result.stderr)[-500:]
    if result.returncode != 0:
        logger.warning("Self-edit test run failed:\n%s", tail)
        return False, tail
    return True, tail


class SelfModifyTool(Tool):
    """Propose an edit to Ultron's own codebase, safely.

    Argument format: ``"<file_path> :: <reason> :: <new_content>"``.

    Because the tool is tagged ``destructive=True`` the PermissionGate
    requires spoken confirmation before it ever runs.
    """

    name = "self_modify_code"
    description = (
        "Propose a change to Ultron's own codebase. "
        "Format: self_modify_code(file_path :: reason :: new_content). "
        "Only in-scope files are accepted; the change is git-committed before "
        "the write and rolled back if the test suite fails."
    )
    tier = PermissionTier.SYSTEM
    destructive = True

    def __init__(
        self,
        repo_path: Path,
        git_guard=None,
        edit_lock=None,
        run_tests=_run_pytest,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = Path(repo_path)
        self._git_guard = git_guard
        self._edit_lock = edit_lock
        self._run_tests = run_tests
        self._log = logger or logging.getLogger("ultron.selfmod")

    def run(self, arg: str) -> ToolResult:
        if _SEPARATOR not in arg or arg.count(_SEPARATOR) < 2:
            return ToolResult(
                False,
                f"Expected '<file_path>{_SEPARATOR}<reason>{_SEPARATOR}<content>'.",
            )
        raw_path, reason, new_content = arg.split(_SEPARATOR, 2)

        try:
            target = _resolve_repo_relative(self._repo, raw_path.strip())
            rel = target.relative_to(self._repo.resolve())
        except ValueError as exc:
            return ToolResult(False, str(exc))

        if not _in_scope(rel):
            return ToolResult(
                False,
                f"{rel} is outside Ultron's self-edit scope — refused. "
                "Only config values, persona style rules, probe thresholds, "
                "and memory data entries are in scope.",
            )

        try:
            return self._apply(target, reason.strip() or "self-edit", new_content)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller
            self._log.exception("Self-edit failed for %s", target)
            return ToolResult(False, f"Self-edit failed: {exc}")

    def _apply(self, target: Path, reason: str, new_content: str) -> ToolResult:
        git_guard = self._git_guard
        edit_lock = self._edit_lock
        if edit_lock is not None and git_guard is not None:
            # Full safety path: lock -> snapshot -> write -> test -> rollback.
            with edit_lock.ultron_editing():
                pre_sha = git_guard.snapshot(label=reason)
                target.write_text(new_content)
                passed, tail = self._run_tests(self._repo, self._log)
                if not passed:
                    git_guard.rollback_to(pre_sha)
                    return ToolResult(
                        False,
                        "Self-edit failed the test suite and was rolled back. "
                        f"{tail}",
                    )
            return ToolResult(
                True,
                f"Self-edit applied to {target.name} (pre-edit commit {pre_sha[:8]}).",
            )

        # No git guard/lock wired (e.g. repo without git): write without the
        # snapshot safety net but keep the scope check above.
        target.write_text(new_content)
        return ToolResult(
            True, f"Self-edit applied to {target.name} (no git guard available)."
        )
