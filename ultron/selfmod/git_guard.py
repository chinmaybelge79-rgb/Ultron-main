"""Git as the safety net for self-modification, not just version control.

Every self-edit cycle commits *before* editing so rollback is always one
command (or one ``rollback_to``) away.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_PRE_TAG = "[ultron-self-edit] pre"


class GitGuard:
    """Snapshot/rollback helpers around the Ultron repository.

    Args:
        repo_path: Root of the git repository to guard (the project dir).
    """

    def __init__(self, repo_path: Path) -> None:
        self._repo = Path(repo_path)

    @property
    def repo(self) -> Path:
        """The guarded repository root."""
        return self._repo

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self._repo,
            capture_output=True,
            text=True,
            check=check,
        )

    def snapshot(self, label: str) -> str:
        """Commit the current tree and return the new HEAD sha.

        ``--allow-empty`` keeps the safety net intact even when nothing
        changed, so the returned sha is always a valid rollback target.
        """
        self._git("add", "-A")
        self._git(
            "commit",
            "-m",
            f"{_PRE_TAG}: {label}",
            "--allow-empty",
        )
        return self._git("rev-parse", "HEAD").stdout.strip()

    def rollback_to(self, commit_sha: str) -> None:
        """Hard-reset the working tree to ``commit_sha``.

        Discards whatever the failed self-edit wrote; the pre-edit snapshot
        is always reachable because it was committed before the write.
        """
        self._git("reset", "--hard", commit_sha)
