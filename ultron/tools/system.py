"""System tools: process listing, disk usage, uptime, memory status."""

from __future__ import annotations

import subprocess

from ultron.tools.base import Tool, ToolResult
from ultron.utils import truncate

_MAX_OUTPUT = 4000


class ProcessListTool(Tool):
    """List running processes, optionally filtered by name."""

    name = "process_list"
    description = (
        "List running processes. Optionally filter by process name. "
        "Example: process_list() or process_list(python)"
    )
    result_is_final = True

    def run(self, arg: str) -> ToolResult:
        filter_name = arg.strip()
        cmd = ["ps", "-axo", "pid,pcpu,pmem,comm"]
        if filter_name:
            cmd += ["-r"]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(False, f"process_list failed: {exc}")
        if result.returncode != 0:
            return ToolResult(False, f"process_list failed: {result.stderr.strip()}")

        lines = result.stdout.strip().splitlines()
        if not lines:
            return ToolResult(True, "No processes found.")
        header, *rows = lines
        if filter_name:
            rows = [row for row in rows if filter_name.lower() in row.lower()]
        if not rows:
            return ToolResult(True, f"No processes match '{filter_name}'.")
        output = "\n".join([header, *rows[:60]])
        if len(rows) > 60:
            output += f"\n... and {len(rows) - 60} more"
        return ToolResult(True, truncate(output, _MAX_OUTPUT))


class DiskUsageTool(Tool):
    """Report disk usage for the current or specified mount point."""

    name = "disk_usage"
    description = (
        "Report disk usage for a path. "
        "Example: disk_usage() or disk_usage(/Users/me/projects)"
    )
    result_is_final = True

    def run(self, arg: str) -> ToolResult:
        target = arg.strip() or "/"
        try:
            result = subprocess.run(
                ["df", "-h", target],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(False, f"disk_usage failed: {exc}")
        if result.returncode != 0:
            return ToolResult(False, f"disk_usage failed: {result.stderr.strip()}")
        lines = result.stdout.strip().splitlines()
        if len(lines) < 2:
            return ToolResult(True, result.stdout.strip())
        return ToolResult(True, truncate(result.stdout.strip(), _MAX_OUTPUT))


class UptimeTool(Tool):
    """Report system uptime and load averages."""

    name = "uptime"
    description = (
        "Report how long the system has been running and load averages. "
        "Example: uptime()"
    )
    result_is_final = True

    def run(self, arg: str) -> ToolResult:
        try:
            result = subprocess.run(
                ["uptime"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(False, f"uptime failed: {exc}")
        if result.returncode != 0:
            return ToolResult(False, f"uptime failed: {result.stderr.strip()}")
        return ToolResult(True, result.stdout.strip())
