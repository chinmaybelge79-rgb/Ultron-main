"""Filesystem tools: read, write, search files."""

from __future__ import annotations

import logging
from pathlib import Path

from ultron.tools.base import Tool, ToolResult
from ultron.utils import truncate

_MAX_FILE_READ = 100_000
_MAX_OUTPUT = 4000
_WRITE_SEPARATOR = " :: "

_log = logging.getLogger("ultron.tools.filesystem")


class ReadFileTool(Tool):
    """Read a text file and return its contents."""

    name = "read_file"
    description = (
        "Read a text file from disk and return its contents. "
        "Example: read_file(/Users/me/notes.txt) or read_file(notes.txt)"
    )

    def run(self, arg: str) -> ToolResult:
        path = resolve_path(arg)
        if not path:
            return ToolResult(False, "No file path given.")
        if not path.exists():
            return ToolResult(False, f"File not found: {path}")
        if not path.is_file():
            return ToolResult(False, f"Not a file: {path}")
        try:
            size = path.stat().st_size
            if size > _MAX_FILE_READ:
                return ToolResult(False, f"File too large to read ({size} bytes).")
            contents = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult(False, f"Could not read {path}: {exc}")
        return ToolResult(True, truncate(contents, _MAX_OUTPUT))


class WriteFileTool(Tool):
    """Write text to a file (path :: content)."""

    name = "write_file"
    description = (
        "Write text content to a file. Argument format: "
        "<path> :: <content>. Example: write_file(notes.txt :: Buy milk tomorrow)"
    )

    def run(self, arg: str) -> ToolResult:
        if _WRITE_SEPARATOR not in arg:
            return ToolResult(False, f"Expected '<path>{_WRITE_SEPARATOR}<content>'.")
        raw_path, content = arg.split(_WRITE_SEPARATOR, 1)
        path = resolve_path(raw_path.strip())
        if not path:
            return ToolResult(False, "No file path given.")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(False, f"Could not write {path}: {exc}")
        return ToolResult(
            True, f"Wrote {len(content.encode('utf-8'))} bytes to {path}."
        )


class ListDirectoryTool(Tool):
    """List contents of a directory."""

    name = "list_directory"
    description = (
        "List files and subdirectories in a directory. "
        "Example: list_directory(/Users/me/projects)"
    )

    def run(self, arg: str) -> ToolResult:
        path = resolve_path(arg)
        if not path:
            return ToolResult(False, "No directory path given.")
        if not path.exists():
            return ToolResult(False, f"Directory not found: {path}")
        if not path.is_dir():
            return ToolResult(False, f"Not a directory: {path}")
        try:
            entries = sorted(path.iterdir())
            lines: list[str] = []
            for entry in entries[:100]:
                prefix = "[dir]" if entry.is_dir() else "[file]"
                size = ""
                if entry.is_file():
                    try:
                        size = f" ({entry.stat().st_size} bytes)"
                    except OSError as exc:
                        _log.debug("stat failed for %s: %s", entry, exc)
                lines.append(f"{prefix} {entry.name}{size}")
            if len(entries) > 100:
                lines.append(f"... and {len(entries) - 100} more entries")
            return ToolResult(True, "\n".join(lines))
        except OSError as exc:
            return ToolResult(False, f"Could not list {path}: {exc}")


class SearchFilesTool(Tool):
    """Search for files matching a pattern."""

    name = "search_files"
    description = (
        "Search for files matching a glob pattern in a directory. "
        "Example: search_files(/Users/me/project :: *.py)"
    )

    def run(self, arg: str) -> ToolResult:
        if _WRITE_SEPARATOR not in arg:
            # Try treating the whole arg as a path with glob
            path = resolve_path(arg)
            if path and path.parent.exists():
                pattern = path.name
                search_dir = path.parent
            else:
                return ToolResult(False, "Expected '<directory> :: <pattern>'.")
        else:
            raw_path, pattern = arg.split(_WRITE_SEPARATOR, 1)
            search_dir = resolve_path(raw_path.strip())
            pattern = pattern.strip()
            if not search_dir:
                return ToolResult(False, "No directory path given.")

        if not search_dir.exists():
            return ToolResult(False, f"Directory not found: {search_dir}")
        try:
            matches = list(search_dir.rglob(pattern))[:50]
            if not matches:
                return ToolResult(True, f"No files matching '{pattern}' found.")
            lines = [str(m.relative_to(search_dir)) for m in matches]
            return ToolResult(True, "\n".join(lines))
        except OSError as exc:
            return ToolResult(False, f"Search failed: {exc}")


# Filesystem scope enforcement (Day 7). Off by default so unit tests that
# operate in tmp_path outside the home directory keep working; the daemon
# enables it at startup via ``enable_scope_enforcement``.
_SCOPE_ENFORCED = False
_EXTRA_ROOTS: tuple = ()


def enable_scope_enforcement(extra_roots: tuple = ()) -> None:
    """Turn on Day 7 filesystem-scope validation for all path resolution."""
    global _SCOPE_ENFORCED, _EXTRA_ROOTS
    _SCOPE_ENFORCED = True
    _EXTRA_ROOTS = tuple(extra_roots)


def resolve_path(raw: str) -> Path | None:
    """Resolve a possibly-relative path against the project directory.

    When scope enforcement is enabled (Day 7), absolute paths that resolve
    outside the allowed roots are rejected by raising ``ScopeViolation``.
    """
    raw = raw.strip().strip('"')
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent.parent / path
    if _SCOPE_ENFORCED:
        from ultron.security import validate_fs_path

        path = validate_fs_path(path, extra_roots=_EXTRA_ROOTS)
    return path
