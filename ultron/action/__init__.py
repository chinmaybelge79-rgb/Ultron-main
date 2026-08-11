"""Action Layer: permission gate, audit log, and kill switch.

This is the safety spine of Ultron (Day 4). Every tool invocation anywhere in
the repo must route through :class:`PermissionGate` — there is exactly one
path to tool execution.
"""

from ultron.action.audit import AuditLog
from ultron.action.gate import KillSwitch, PermissionDenied, PermissionGate
from ultron.action.permissions import DESTRUCTIVE_ACTIONS, PermissionTier

__all__ = [
    "AuditLog",
    "DESTRUCTIVE_ACTIONS",
    "KillSwitch",
    "PermissionDenied",
    "PermissionGate",
    "PermissionTier",
]
