"""Permission tiers and destructive-action markers for the Action Layer.

Every tool carries a :class:`PermissionTier` and a ``destructive`` flag at
registration time (see ``ultron/tools/base.py``). The :class:`PermissionGate`
(Day 4) enforces the tier policy and requires spoken confirmation for
destructive actions before any tool executes.
"""

from __future__ import annotations

from enum import Enum


class PermissionTier(Enum):
    """Least-privilege ordering of tool side effects."""

    READ = "read"  # list files, read content, query system state — no side effects
    WRITE = "write"  # create/modify files, write memory, non-destructive changes
    EXECUTE = "execute"  # run scripts/commands, launch/quit apps
    SYSTEM = "system"  # System Settings, network config, another user's data

    def __le__(self, other: PermissionTier) -> bool:
        """Order tiers so permission checks can use ``tool.tier <= allowed``."""
        order = [PermissionTier.READ, PermissionTier.WRITE,
                 PermissionTier.EXECUTE, PermissionTier.SYSTEM]
        return order.index(self) <= order.index(other)


# Actions that always require spoken confirmation regardless of tier because
# of their blast radius. Names map to the registry's real tool names.
DESTRUCTIVE_ACTIONS = {
    "run_command",
    "write_file",
    "git_commit",
    "quit_application",
    "self_modify_code",
    "install_package",
}
