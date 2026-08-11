"""Frontmost-app + app launch/quit detection via AppleScript.

Relies on AppleScript ``System Events``, which requires the Accessibility
permission. Instead of failing silently, a missing/inaccessible permission is
reported with a clear, specific message (per Day 3).
"""

from __future__ import annotations

import logging
import subprocess

_log = logging.getLogger("ultron.probes.app")

_FRONTMOST_SCRIPT = """
tell application "System Events"
    set frontApp to name of first application process whose frontmost is true
end tell
return frontApp
"""

_RUNNING_APPS_SCRIPT = """
tell application "System Events"
    return name of every application process whose background only is false
end tell
"""

_ACCESSIBILITY_HINT = (
    "Accessibility permission required — System Settings > Privacy & Security "
    "> Accessibility"
)


class AccessibilityError(RuntimeError):
    """Raised when AppleScript System Events cannot run (permission issue)."""


class AppProbe:
    """Watches the frontmost app and diffs the set of running apps."""

    def __init__(self) -> None:
        self._last_running: set[str] = set()

    def _run(self, script: str) -> str:
        try:
            out = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except Exception as exc:  # noqa: BLE001
            raise AccessibilityError(
                f"AppleScript failed ({exc}). {_ACCESSIBILITY_HINT}"
            ) from exc
        if out.returncode != 0:
            error = out.stderr.strip() or "unknown"
            raise AccessibilityError(
                f"AppleScript error {out.returncode}: {error}. "
                f"{_ACCESSIBILITY_HINT}"
            )
        return out.stdout.strip()

    def frontmost(self) -> str:
        """Return the name of the frontmost application."""
        return self._run(_FRONTMOST_SCRIPT)

    def diff_running_apps(self) -> tuple[set[str], set[str]]:
        """Return (launched, quit) app-name sets since the last diff.

        Launched-on-first-sample is suppressed so a freshly started probe
        doesn't report every currently-running app as \"launched\".
        """
        raw = self._run(_RUNNING_APPS_SCRIPT)
        current = {name.strip() for name in raw.split(",") if name.strip()}
        if not self._last_running:
            self._last_running = current
            return set(), set()
        launched = current - self._last_running
        quit_apps = self._last_running - current
        self._last_running = current
        return launched, quit_apps
