"""Shell command execution tool with layered safety checks.

Safety model (safe by default):
    - Hard block: commands that would destroy the host (wipe filesystems,
      brick the system, fork bombs, raw device writes) are refused outright.
    - Confirmable: commands that are risky but sometimes legitimate
      (recursive deletes, sudo, force rewrites, downloaded scripts) require
      an explicit confirmation callback before running. Without a callback
      they are refused.
    - Detection normalizes whitespace and case first so spacing tricks
      cannot bypass the policy.
"""

from __future__ import annotations

import logging
import re
import subprocess

from ultron.tools.base import Tool, ToolResult
from ultron.utils import truncate

_MAX_OUTPUT = 4000

# ---------------------------------------------------------------------------
# Safety policy
# ---------------------------------------------------------------------------

_DESTRUCTIVE_FORBIDDEN = (
    "rm -rf /",
    "rm -fr /",
    "rm --no-preserve-root",
    "sudo rm -rf",
    "sudo rm -fr",
    "sudo rm --no-preserve-root",
    "chmod -r 000 /",
    "chown -r /",
    "> /dev/sd",
    ">/dev/sd",
    "> /dev/disk",
    ">/dev/disk",
    ":(){",
    "dd if=",
)

# Destructive verbs that are only blocked when used as the command itself
# (or after a shell separator), never when they appear inside arguments
# like ``echo shutdown`` or ``echo halt``.
_DESTRUCTIVE_VERBS = ("mkfs", "fdisk", "shutdown", "halt", "poweroff")

_WS_RE = re.compile(r"\s+")


def _matches_destructive(collapsed: str) -> str | None:
    """Return the destructive rule matched by a normalized command, if any."""
    for phrase in _DESTRUCTIVE_FORBIDDEN:
        if phrase in collapsed:
            return phrase
    for verb in _DESTRUCTIVE_VERBS:
        if re.search(rf"(?:^|[;&|]\s*){verb}\b", collapsed):
            return verb
    return None

_WS_RE = re.compile(r"\s+")

# Dangerous-but-occasionally-legitimate commands. These need a
# confirmation callback; without one they are refused.
_CONFIRM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\s+-\w*r\w*\s", re.IGNORECASE),  # rm -r / -R (recursive)
    re.compile(r"\brm\s+-\w*f\w*\s", re.IGNORECASE),  # rm -f (force)
    re.compile(r"\bsudo\b", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--\s*hard\b", re.IGNORECASE),
    re.compile(r"\bgit\s+push\s+(-\w*f\b|--\s*force\b)", re.IGNORECASE),
    re.compile(r"\b(killall|pmap|pkill)\s+-?9?\b", re.IGNORECASE),
    re.compile(r"\bkill\s+-9\b", re.IGNORECASE),
    re.compile(r"\b(?:curl|wget)\b.*\|\s*(?:ba?sh|sh)\b", re.IGNORECASE),
    re.compile(r"\bdiskutil\s+erase\b", re.IGNORECASE),
    re.compile(r"\bunmount\b", re.IGNORECASE),
)


def _collapse_whitespace(command: str) -> str:
    """Collapse repeated whitespace to single spaces, lowercased."""
    return _WS_RE.sub(" ", command).strip().lower()


class RunTerminalCommandTool(Tool):
    """Run a shell command and return its output.

    Args:
        command_timeout: Maximum execution time in seconds.
        logger: Logger used to record executions and blocks.
        confirm: Optional callback that decides whether a dangerous
            command may run. Receives the original command; return True
            to allow, False to refuse.
    """

    name = "run_command"
    description = (
        "Run a terminal command in a shell and return its output. "
        "Example: run_command(ls -la)"
    )

    def __init__(
        self,
        command_timeout: float,
        logger: logging.Logger | None = None,
        confirm_callback: object | None = None,  # Callable[[str], bool]
    ) -> None:
        self._timeout = command_timeout
        self._log = logger or logging.getLogger("ultron.tools.shell")
        self._confirm_callback = confirm_callback

    def run(self, arg: str) -> ToolResult:
        command = arg.strip()
        if not command:
            return ToolResult(False, "No command given.")
        collapsed = _collapse_whitespace(command)

        destructive = _matches_destructive(collapsed)
        if destructive is not None:
            self._log.warning("Blocked destructive command: %r", command)
            return ToolResult(False, f"Command blocked for safety: {destructive}")

        if self._needs_confirmation(collapsed):
            allowed = self._confirm_allowed(command)
            if not allowed:
                self._log.warning(
                    "Refused dangerous command without confirmation: %r", command
                )
                return ToolResult(
                    False,
                    "That command could damage your system, so I'll need your "
                    "confirmation to run it.",
                )
            self._log.info("Confirmed dangerous command: %r", command)

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, f"Command timed out after {self._timeout}s.")
        except OSError as exc:
            return ToolResult(False, f"Failed to run command: {exc}")
        output = (result.stdout + result.stderr).strip()
        output = truncate(output, _MAX_OUTPUT) if output else "(no output)"
        self._log.info(
            "Command executed: %r (exit=%d) output_len=%d",
            command,
            result.returncode,
            len(output),
        )
        if result.returncode == 0:
            return ToolResult(True, output)
        return ToolResult(False, f"Exit code {result.returncode}: {output}")

    # ------------------------------------------------------------------
    # Policy helpers
    # ------------------------------------------------------------------

    def _needs_confirmation(self, collapsed: str) -> bool:
        """Return True when a normalized command matches a dangerous pattern."""
        return any(pattern.search(collapsed) for pattern in _CONFIRM_PATTERNS)

    def _confirm_allowed(self, command: str) -> bool:
        if self._confirm_callback is None:
            return False
        try:
            return bool(self._confirm_callback(command))
        except Exception as exc:
            self._log.warning("Confirmation callback failed: %s", exc)
            return False