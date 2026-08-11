"""The PermissionGate and KillSwitch — the safety spine of Ultron.

Every tool invocation in the system must pass through
:meth:`PermissionGate.invoke` (Day 4 acceptance: zero direct ``fn`` calls
outside this module). The gate:

1. Refuses everything while the KillSwitch is active.
2. Enforces the configured allowed tiers (least privilege by default).
3. Requires spoken confirmation for destructive actions.
4. Records every attempt — allowed or blocked — in the AuditLog.
"""

from __future__ import annotations

import time
from pathlib import Path

from ultron.action.audit import AuditLog
from ultron.action.permissions import PermissionTier


class PermissionDenied(RuntimeError):
    """Raised when a tool invocation is blocked by the gate."""


class KillSwitch:
    """A sentinel file that, when present, blocks all tool execution.

    Checked in three places (belt and suspenders): daemon startup, the
    PermissionGate hot path, and the Autonomy Loop decision step.
    """

    def __init__(self, sentinel_path: Path | str) -> None:
        self._path = Path(sentinel_path)

    def is_active(self) -> bool:
        return self._path.exists()

    def engage(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch()

    def release(self) -> None:
        self._path.unlink(missing_ok=True)


class PermissionGate:
    """Single choke point for tool execution.

    Args:
        audit_log: The :class:`AuditLog` every attempt is written to.
        kill_switch: The :class:`KillSwitch` consulted before every call.
        confirm_fn: Callable(text) -> bool used for destructive actions
            (e.g. a spoken \"Are you sure, sir?\"). Include this when the
            VoiceLoop is present; a stub that returns False is safe by default.
        allowed_tiers: The set of tiers this source may execute. Defaults to
            ``{READ, WRITE}`` (least privilege per Day 7).
    """

    def __init__(
        self,
        audit_log: AuditLog,
        kill_switch: KillSwitch,
        confirm_fn,
        allowed_tiers=None,
    ) -> None:
        self._audit = audit_log
        self._kill = kill_switch
        self._confirm = confirm_fn
        self._allowed = set(allowed_tiers) if allowed_tiers else {
            PermissionTier.READ,
            PermissionTier.WRITE,
        }

    def set_allowed_tiers(self, tiers) -> None:
        """Opt into additional tiers (e.g. EXECUTE/SYSTEM after a trial run)."""
        self._allowed = set(tiers)

    def allowed_tiers(self):
        """Return the currently permitted tiers."""
        return set(self._allowed)

    def invoke(self, tool, args: dict, source: str = "voice"):
        """Execute ``tool`` with ``args`` after gate checks.

        Args:
            tool: A :class:`Tool` (has ``name``, ``tier``, ``destructive``,
                ``fn``/``run``).
            args: Keyword args forwarded to the tool.
            source: ``voice`` | ``autonomy_loop`` | ``coding_agent`` |
                ``self_modify`` — always recorded.

        Raises:
            PermissionDenied: If blocked by the kill switch, tier policy, or
                declined destructive confirmation.
        """
        if self._kill.is_active():
            self._audit.record(tool.name, args, source, "BLOCKED_KILL_SWITCH")
            raise PermissionDenied("Kill switch is active.")

        if tool.tier not in self._allowed:
            self._audit.record(tool.name, args, source, "BLOCKED_TIER")
            raise PermissionDenied(
                f"{tool.tier.value} not permitted for source={source}."
            )

        if getattr(tool, "destructive", False):
            approved = self._confirm(
                f"About to {tool.name} with {args}. Confirm."
            )
            if not approved:
                self._audit.record(tool.name, args, source, "DENIED_BY_USER")
                raise PermissionDenied("User declined confirmation.")

        started = time.time()
        try:
            result = tool.fn(**args) if hasattr(tool, "fn") else tool.run(**args)
            self._audit.record(
                tool.name, args, source, "SUCCESS",
                duration=time.time() - started,
            )
            return result
        except Exception as exc:  # noqa: BLE001 - audit then re-raise
            self._audit.record(
                tool.name, args, source, f"ERROR:{exc}",
                duration=time.time() - started,
            )
            raise
