"""Code analysis and editing tools for Ultron."""

from __future__ import annotations

import subprocess

from ultron.tools.base import Tool, ToolResult
from ultron.tools.filesystem import resolve_path
from ultron.utils import truncate

_MAX_OUTPUT = 4000


class CodeSearchTool(Tool):
    """Search codebases with ripgrep-style pattern matching."""

    name = "code_search"
    description = (
        "Search for a pattern in code files using grep. "
        "Format: <pattern> :: <directory>. "
        "Example: code_search(def handle_command :: /Users/me/project)"
    )

    def run(self, arg: str) -> ToolResult:
        if " :: " in arg:
            pattern, raw_dir = arg.split(" :: ", 1)
            pattern = pattern.strip()
            search_dir = resolve_path(raw_dir.strip())
        else:
            pattern = arg.strip()
            search_dir = resolve_path(".")

        if not pattern:
            return ToolResult(False, "No search pattern given.")
        if not search_dir or not search_dir.exists():
            return ToolResult(False, f"Directory not found: {search_dir}")

        # Try ripgrep first, fall back to grep
        for cmd in [
            [
                "rg",
                "--no-heading",
                "--line-number",
                "--color=never",
                "-m",
                "30",
                pattern,
                str(search_dir),
            ],
            [
                "grep",
                "-rn",
                "--include=*.py",
                "--include=*.js",
                "--include=*.ts",
                "--include=*.go",
                "--include=*.rs",
                "--include=*.java",
                "--include=*.cpp",
                "--include=*.c",
                "--include=*.h",
                "--include=*.swift",
                "--include=*.rb",
                "-m",
                "30",
                pattern,
                str(search_dir),
            ],
        ]:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                if result.returncode <= 1:  # 0 = found, 1 = not found (both valid)
                    output = result.stdout.strip()
                    if not output:
                        return ToolResult(True, f"No matches for '{pattern}'.")
                    return ToolResult(True, truncate(output, _MAX_OUTPUT))
            except (OSError, subprocess.TimeoutExpired):
                continue
        return ToolResult(False, "Neither ripgrep nor grep is available.")


class CodeEditTool(Tool):
    """Perform surgical edits on code files (search and replace)."""

    name = "code_edit"
    description = (
        "Edit a code file by replacing text. "
        "Format: <file_path> :: <old_text> :: <new_text>. "
        "Example: code_edit(/path/file.py :: def old_name :: def new_name)"
    )

    def run(self, arg: str) -> ToolResult:
        parts = arg.split(" :: ")
        if len(parts) < 3:
            return ToolResult(False, "Expected '<file> :: <old_text> :: <new_text>'.")
        raw_path = parts[0].strip()
        old_text = parts[1]
        new_text = " :: ".join(parts[2:])  # In case new_text contains ::

        path = resolve_path(raw_path)
        if not path:
            return ToolResult(False, "No file path given.")
        if not path.exists():
            return ToolResult(False, f"File not found: {path}")
        if not path.is_file():
            return ToolResult(False, f"Not a file: {path}")

        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            return ToolResult(False, f"Could not read {path}: {exc}")

        if old_text not in content:
            return ToolResult(
                False, f"Text not found in {path.name}: '{truncate(old_text, 80)}'"
            )

        count = content.count(old_text)
        new_content = content.replace(old_text, new_text)
        try:
            path.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(False, f"Could not write {path}: {exc}")

        return ToolResult(True, f"Replaced {count} occurrence(s) in {path.name}.")
