"""macOS-specific tools: application management, screenshots, Spotlight."""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from ultron.tools.base import Tool, ToolResult

_log = logging.getLogger("ultron.tools.macos")


_APPLESCRIPT_UNSAFE = ("\"", "\\", ";", "\n", "\r", "\t", "&")

def _applescript_literal(value: str) -> str | None:
    """Return a value safe to embed in an AppleScript string literal.

    AppleScript string literals are double-quoted and support ``\\``
    escapes; embedding user input without escaping allows prompt-
    injection payloads to execute arbitrary AppleScript. Returns None
    when the value contains characters that cannot be safely escaped.
    """
    if any(char in value for char in _APPLESCRIPT_UNSAFE):
        return None
    return value


class OpenApplicationTool(Tool):
    """Open an application by name."""

    name = "open_application"
    description = "Open a macOS application by name. Example: open_application(Safari)"
    result_is_final = True

    def run(self, arg: str) -> ToolResult:
        app = arg.strip().rstrip(".app")
        if not app:
            return ToolResult(False, "No application name given.")
        result = subprocess.run(
            ["open", "-a", app],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            return ToolResult(True, f"Opened {app}.")
        found = _find_application(app)
        if found:
            result = subprocess.run(
                ["open", str(found)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if result.returncode == 0:
                return ToolResult(True, f"Opened {found.stem}.")
        return ToolResult(False, f"Could not find application {app}.")


class QuitApplicationTool(Tool):
    """Quit an application by name."""

    name = "quit_application"
    description = (
        "Quit a running macOS application by name. Example: quit_application(Safari)"
    )
    result_is_final = True

    def run(self, arg: str) -> ToolResult:
        app = arg.strip().rstrip(".app")
        if not app:
            return ToolResult(False, "No application name given.")
        safe = _applescript_literal(app)
        if safe is None:
            return ToolResult(False, "Invalid application name.")
        script = f'quit app "{safe}"'
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            return ToolResult(True, f"Quit {app}.")
        return ToolResult(False, f"Could not quit {app}: {result.stderr.strip()}")


class TakeScreenshotTool(Tool):
    """Capture the screen to a timestamped PNG file.

    Args:
        screenshot_dir: Directory where screenshots are saved.
    """

    name = "take_screenshot"
    description = (
        "Take a screenshot of the screen and save it as a PNG file. "
        "Example: take_screenshot()"
    )
    result_is_final = True

    def __init__(self, screenshot_dir: Path) -> None:
        self._directory = screenshot_dir

    def run(self, arg: str) -> ToolResult:
        directory = self._directory
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = directory / f"ultron_screenshot_{stamp}.png"
        result = subprocess.run(
            ["screencapture", "-x", str(target)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0 and target.exists():
            return ToolResult(True, f"Screenshot saved to {target}.")
        return ToolResult(False, f"Screenshot failed: {result.stderr.strip()}")


class SystemInfoTool(Tool):
    """Return system information: CPU, RAM, disk, battery."""

    name = "system_info"
    description = (
        "Get macOS system information (CPU, memory, disk, battery). "
        "Example: system_info()"
    )
    result_is_final = True

    def run(self, arg: str) -> ToolResult:
        parts: list[str] = []
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                parts.append(f"CPU: {result.stdout.strip()}")
        except OSError as exc:
            _log.debug("sysctl cpu unavailable: %s", exc)
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                gb = int(result.stdout.strip()) / (1024**3)
                parts.append(f"RAM: {gb:.0f} GB")
        except (OSError, ValueError) as exc:
            _log.debug("sysctl memsize unavailable: %s", exc)
        try:
            result = subprocess.run(
                ["df", "-h", "/"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if len(lines) >= 2:
                    parts.append(f"Disk: {lines[1]}")
        except OSError as exc:
            _log.debug("df unavailable: %s", exc)
        try:
            result = subprocess.run(
                ["pmset", "-g", "batt"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                parts.append(f"Battery: {result.stdout.strip()}")
        except OSError as exc:
            _log.debug("pmset unavailable: %s", exc)
        if not parts:
            return ToolResult(False, "Could not retrieve system information.")
        return ToolResult(True, "\n".join(parts))


class NotificationTool(Tool):
    """Send a macOS notification."""

    name = "notify"
    description = (
        "Send a macOS notification. Example: notify(Build completed successfully)"
    )
    result_is_final = True

    def run(self, arg: str) -> ToolResult:
        message = arg.strip()
        if not message:
            return ToolResult(False, "No notification message given.")
        safe = _applescript_literal(message)
        if safe is None:
            return ToolResult(False, "Invalid notification message.")
        script = (
            f'display notification "{safe}" with title "Ultron" sound name "Glass"'
        )
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return ToolResult(True, f"Notification sent: {message}")
        return ToolResult(False, f"Notification failed: {result.stderr.strip()}")


def _find_application(name: str) -> Path | None:
    """Locate an application bundle by fuzzy name match.

    Exact matches win; among substring matches the shortest stem wins
    (so "Music" beats "Music Memos"), with ties resolved by order.
    """
    roots = [
        Path("/Applications"),
        Path.home() / "Applications",
        Path("/System/Applications"),
        Path("/System/Applications/Utilities"),
    ]
    lowered = name.lower()
    for root in roots:
        try:
            candidates = list(root.glob("*.app"))
        except OSError:
            continue
        for candidate in candidates:
            if candidate.stem.lower() == lowered:
                return candidate
        substring_matches = [
            candidate for candidate in candidates if lowered in candidate.stem.lower()
        ]
        if substring_matches:
            return min(
                substring_matches,
                key=lambda candidate: len(candidate.stem),
            )
    return None
