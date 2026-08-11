"""No-conflict editing: a lock file, not a gentleman's agreement.

A cooperative lock between your coding agent and Ultron's self-edit path.
The coding agent (or you, manually) touches ``.coding-agent-lock`` while
working; Ultron checks for it before any self-edit and refuses to proceed
while it is present.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path


class EditLock:
    """Two-file cooperative lock.

    Args:
        repo_path: Root of the Ultron repository.
    """

    def __init__(self, repo_path: Path) -> None:
        self._ultron_lock = Path(repo_path) / ".ultron-selfedit-lock"
        self._coding_agent_lock = Path(repo_path) / ".coding-agent-lock"

    def coding_agent_active(self) -> bool:
        """True when the coding agent holds the lock (editing right now)."""
        return self._coding_agent_lock.exists()

    @property
    def ultron_lock_path(self) -> Path:
        """Path of Ultron's own lock file (useful in tests)."""
        return self._ultron_lock

    @property
    def coding_agent_lock_path(self) -> Path:
        """Path of the coding agent's lock file (useful in tests)."""
        return self._coding_agent_lock

    @contextmanager
    def ultron_editing(self):
        """Yield with Ultron's lock held; refuse if the agent is editing.

        Raises:
            RuntimeError: If ``.coding-agent-lock`` is present — Ultron will
                not self-edit while your coding agent holds the repo.
        """
        if self.coding_agent_active():
            raise RuntimeError(
                "Coding agent lock held — Ultron will not self-edit right now."
            )
        self._ultron_lock.write_text(str(os.getpid()))
        try:
            yield
        finally:
            self._ultron_lock.unlink(missing_ok=True)
