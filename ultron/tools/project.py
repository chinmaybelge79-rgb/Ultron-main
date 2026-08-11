"""Project Intelligence tools: repository scanning, dependency graphs, TODO scan."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ultron.tools.base import Tool, ToolResult
from ultron.tools.filesystem import resolve_path
from ultron.utils import truncate

_MAX_OUTPUT = 4000
_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "build",
        "dist",
        ".hg",
        ".svn",
    }
)
_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
_SUPPORTED_EXTENSIONS = (
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".swift",
    ".rb",
    ".php",
    ".sh",
    ".md",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
)


def _walk_code_files(root: Path, max_files: int = 500) -> list[Path]:
    """Collect code files under root, respecting ignore rules."""
    files: list[Path] = []
    for current, dirs, names in root.walk():
        dirs[:] = [d for d in dirs if d != ".git" and d.lower() not in _IGNORED_DIRS]
        for name in names:
            path = current / name
            if path.suffix.lower() in _SUPPORTED_EXTENSIONS and path.is_file():
                files.append(path)
            if len(files) >= max_files:
                return files
    return files


class ProjectScanTool(Tool):
    """Summarize a project: file tree, language mix, size, TODO/FIXME count."""

    name = "project_scan"
    description = (
        "Scan a project directory and summarize its structure: top-level "
        "layout, file counts by language, total lines, and TODO/FIXME markers. "
        "Example: project_scan(/Users/me/project)"
    )

    def run(self, arg: str) -> ToolResult:
        raw_dir = arg.strip() or "."
        root = resolve_path(raw_dir)
        if not root or not root.exists():
            return ToolResult(False, f"Directory not found: {root}")
        if not root.is_dir():
            return ToolResult(False, f"Not a directory: {root}")

        try:
            files = _walk_code_files(root)
        except OSError as exc:
            return ToolResult(False, f"project_scan failed: {exc}")

        if not files:
            return ToolResult(True, f"No code files found in {root}.")

        lines: list[str] = [f"Project: {root.name}"]
        lines.append(f"Files: {len(files)}")

        by_ext: dict[str, int] = {}
        total_lines = 0
        todo_count = 0
        for path in files:
            ext = path.suffix.lower() or "(none)"
            by_ext[ext] = by_ext.get(ext, 0) + 1
            try:
                with path.open(encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
                total_lines += content.count("\n") + 1
                todo_count += len(_TODO_RE.findall(content))
            except OSError:
                continue

        lang_counts = ", ".join(
            f"{ext}: {count}"
            for ext, count in sorted(
                by_ext.items(), key=lambda item: item[1], reverse=True
            )[:8]
        )
        lines.append(f"Languages: {lang_counts}")
        lines.append(f"Total lines: {total_lines}")
        lines.append(f"TODO/FIXME markers: {todo_count}")

        return ToolResult(True, truncated_join(lines))


class ProjectDepsTool(Tool):
    """Build a dependency graph for a Python project using AST imports."""

    name = "project_deps"
    description = (
        "Analyze import dependencies in a Python project. "
        "Example: project_deps(/Users/me/project)"
    )

    def run(self, arg: str) -> ToolResult:
        raw_dir = arg.strip() or "."
        root = resolve_path(raw_dir)
        if not root or not root.exists():
            return ToolResult(False, f"Directory not found: {root}")

        imports: dict[str, set[str]] = {}
        for path in _walk_code_files(root):
            if path.suffix.lower() != ".py":
                continue
            rel = str(path.relative_to(root))
            imports.setdefault(rel, set())
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports[rel].add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module:
                        imports[rel].add(module.split(".")[0])

        local_modules = {
            path.stem for path in _walk_code_files(root) if path.suffix.lower() == ".py"
        }
        nodes = sorted(imports)
        if not nodes:
            return ToolResult(True, "No Python modules found.")

        lines: list[str] = [f"Modules: {len(nodes)}"]
        for module in _walk_code_files(root):
            if module.suffix.lower() != ".py":
                continue
            deps = sorted(
                dep
                for dep in imports.get(str(module.relative_to(root)), set())
                if dep in local_modules or dep in {"__main__"}
            )
            if deps:
                lines.append(f"{module.relative_to(root)} -> {', '.join(deps)}")
        return ToolResult(True, truncated_join(lines))


class TodoScanTool(Tool):
    """Find TODO/FIXME markers across a project with file locations."""

    name = "todo_scan"
    description = (
        "Find TODO, FIXME, HACK, and XXX markers in a project. "
        "Example: todo_scan(/Users/me/project)"
    )

    def run(self, arg: str) -> ToolResult:
        raw_dir = arg.strip() or "."
        root = resolve_path(raw_dir)
        if not root or not root.exists():
            return ToolResult(False, f"Directory not found: {root}")

        matches: list[str] = []
        for path in _walk_code_files(root, max_files=300):
            try:
                with path.open(encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError:
                continue
            for line_no, line in enumerate(content.splitlines(), 1):
                if _TODO_RE.search(line):
                    rel = path.relative_to(root)
                    matches.append(f"{rel}:{line_no}: {line.strip()}")
                    if len(matches) >= 100:
                        break
            if len(matches) >= 100:
                break

        if not matches:
            return ToolResult(True, "No TODO/FIXME markers found.")
        return ToolResult(True, truncated_join(matches))


def truncated_join(lines: list[str]) -> str:
    """Join lines and truncate them to the max output limit."""
    text = "\n".join(lines)
    return truncate(text, _MAX_OUTPUT)
