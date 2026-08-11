"""Clipboard tools: copy and paste via macOS pbcopy/pbpaste."""

from __future__ import annotations

import subprocess

from ultron.tools.base import Tool, ToolResult
from ultron.utils import truncate


class CopyClipboardTool(Tool):
    """Copy text to the system clipboard."""

    name = "copy_clipboard"
    description = (
        "Copy text to the macOS clipboard. Example: copy_clipboard(Hello world)"
    )
    result_is_final = True

    def run(self, arg: str) -> ToolResult:
        text = arg if arg else ""
        try:
            result = subprocess.run(
                ["pbcopy"],
                input=text,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except OSError as exc:
            return ToolResult(False, f"pbcopy failed: {exc}")
        if result.returncode == 0:
            return ToolResult(True, "Copied to clipboard.")
        return ToolResult(False, f"Copy failed: {result.stderr.strip()}")


class PasteClipboardTool(Tool):
    """Read text from the system clipboard."""

    name = "paste_clipboard"
    description = (
        "Read the current contents of the macOS clipboard and return them. "
        "Example: paste_clipboard()"
    )
    result_is_final = True

    def run(self, arg: str) -> ToolResult:
        try:
            result = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except OSError as exc:
            return ToolResult(False, f"pbpaste failed: {exc}")
        if result.returncode != 0:
            return ToolResult(False, f"Paste failed: {result.stderr.strip()}")
        contents = result.stdout.strip()
        if not contents:
            return ToolResult(False, "Clipboard is empty.")
        return ToolResult(True, f"Clipboard contents: {truncate(contents, 500)}")
