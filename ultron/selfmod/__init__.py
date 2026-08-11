"""Self-modification safety (Day 6): git-guarded, lock-protected, gated edits.

Ultron may propose changes to its own codebase, but never silently: every
self-edit runs under :class:`EditLock` (no conflicts with your coding agent),
takes a git snapshot before writing, and is rolled back automatically if the
test suite fails. The whole operation is a ``SYSTEM``-tier, ``destructive``
tool routed through the Day 4 :class:`PermissionGate`.
"""

from ultron.selfmod.edit_lock import EditLock
from ultron.selfmod.git_guard import GitGuard
from ultron.selfmod.self_modify import SelfModifyTool

__all__ = ["EditLock", "GitGuard", "SelfModifyTool"]
