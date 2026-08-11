"""Tool registry: holds all tools, provides descriptions, routes calls."""

from __future__ import annotations

import logging
import re
import time

from ultron.action.gate import PermissionDenied
from ultron.action.permissions import PermissionTier
from ultron.memory.store import MemoryStore
from ultron.monitoring import Metrics, get_metrics
from ultron.tools.base import Tool, ToolCall, ToolResult
from ultron.tools.clipboard import CopyClipboardTool, PasteClipboardTool
from ultron.tools.filesystem import (
    ListDirectoryTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)
from ultron.tools.macos import (
    NotificationTool,
    OpenApplicationTool,
    QuitApplicationTool,
    SystemInfoTool,
    TakeScreenshotTool,
)
from ultron.tools.shell import RunTerminalCommandTool
from ultron.tools.web import OpenWebsiteTool, SearchGoogleTool
from ultron.utils import ToolError, normalize

_WRITE_SEPARATOR = " :: "

# Day 4: every registered tool must declare its permission tier and whether it
# is destructive. This single mapping is the source of truth applied in
# ``build_default``; a test enforces that no tool slips through untagged.
_TOOL_PERMISSIONS: dict[str, tuple[PermissionTier, bool]] = {
    "open_application": (PermissionTier.EXECUTE, False),
    "quit_application": (PermissionTier.EXECUTE, True),
    "open_website": (PermissionTier.EXECUTE, False),
    "search_google": (PermissionTier.READ, False),
    "take_screenshot": (PermissionTier.WRITE, False),
    "copy_clipboard": (PermissionTier.WRITE, False),
    "paste_clipboard": (PermissionTier.READ, False),
    "run_command": (PermissionTier.EXECUTE, True),
    "read_file": (PermissionTier.READ, False),
    "write_file": (PermissionTier.WRITE, True),
    "list_directory": (PermissionTier.READ, False),
    "search_files": (PermissionTier.READ, False),
    "system_info": (PermissionTier.READ, False),
    "notify": (PermissionTier.WRITE, False),
    "remember": (PermissionTier.WRITE, False),
    "recall": (PermissionTier.READ, False),
    "git_status": (PermissionTier.READ, False),
    "git_diff": (PermissionTier.READ, False),
    "git_log": (PermissionTier.READ, False),
    "git_commit": (PermissionTier.EXECUTE, True),
    "git_branch": (PermissionTier.READ, False),
    "code_search": (PermissionTier.READ, False),
    "code_edit": (PermissionTier.WRITE, True),
    "self_modify_code": (PermissionTier.SYSTEM, True),
    "project_scan": (PermissionTier.READ, False),
    "project_deps": (PermissionTier.READ, False),
    "todo_scan": (PermissionTier.READ, False),
    "process_list": (PermissionTier.READ, False),
    "disk_usage": (PermissionTier.READ, False),
    "uptime": (PermissionTier.READ, False),
}


class _RememberTool(Tool):
    """Store a fact in memory (used by the assistant and LLM)."""

    name = "remember"
    description = (
        "Store a fact the user wants remembered. "
        "Example: remember(the user's dog is named Rex)"
    )
    result_is_final = True

    def __init__(self, memory: MemoryStore) -> None:
        self._memory = memory

    def run(self, arg: str) -> ToolResult:
        fact = arg.strip()
        if not fact:
            return ToolResult(False, "Nothing to remember.")
        self._memory.remember_fact(fact)
        return ToolResult(True, "Remembered.")


class _RecallTool(Tool):
    """Retrieve stored memories relevant to a query."""

    name = "recall"
    description = (
        "Retrieve memories (facts, preferences, past conversations) "
        "relevant to a query. Example: recall(what do I like?)"
    )
    result_is_final = True

    def __init__(self, memory: MemoryStore) -> None:
        self._memory = memory

    def run(self, arg: str) -> ToolResult:
        context = self._memory.build_context(arg)
        if not context:
            return ToolResult(True, "No relevant memories found.")
        return ToolResult(True, context)


class ToolRegistry:
    """Registry of all tools with LLM descriptions and offline routing.

    Args:
        tools: Iterable of tool instances.
        logger: Logger instance for the registry.
    """

    def __init__(
        self,
        tools: list[Tool],
        logger: logging.Logger,
        metrics: Metrics | None = None,
        permission_gate=None,
    ) -> None:
        self._tools: dict[str, Tool] = {tool.name: tool for tool in tools}
        self._log = logger
        self._metrics = metrics or get_metrics()
        self._permission_gate = permission_gate

    def set_permission_gate(self, gate) -> None:
        """Route every subsequent tool execution through ``gate``.

        When a gate is configured there is exactly one path to a tool's
        ``run`` — through :meth:`PermissionGate.invoke`. Until one is set the
        registry executes directly (useful for tests and tool-less startup).
        """
        self._permission_gate = gate

    @staticmethod
    def _apply_permissions(tool: Tool) -> None:
        """Tag a tool with its declared tier/destructive metadata (Day 4)."""
        tier, destructive = _TOOL_PERMISSIONS.get(
            tool.name, (PermissionTier.READ, False)
        )
        tool.tier = tier
        tool.destructive = destructive
        return tool

    @classmethod
    def build_default(
        cls,
        config: object,
        memory: MemoryStore,
        logger: logging.Logger,
        metrics: Metrics | None = None,
    ) -> ToolRegistry:
        """Construct the default registry with every standard tool.

        Args:
            config: Application configuration.
            memory: Memory store (used by memory tools).
            logger: Logger instance.
            metrics: Optional telemetry collector.

        Returns:
            A fully populated :class:`ToolRegistry`.
        """
        tools: list[Tool] = [
            OpenApplicationTool(),
            QuitApplicationTool(),
            OpenWebsiteTool(),
            SearchGoogleTool(),
            TakeScreenshotTool(config.screenshot_dir),  # type: ignore[attr-defined]
            CopyClipboardTool(),
            PasteClipboardTool(),
            RunTerminalCommandTool(config.tools_command_timeout, logger=logger),  # type: ignore[attr-defined]
            ReadFileTool(),
            WriteFileTool(),
            ListDirectoryTool(),
            SearchFilesTool(),
            SystemInfoTool(),
            NotificationTool(),
            _RememberTool(memory),
            _RecallTool(memory),
        ]

        # Conditionally load git tools
        try:
            from ultron.tools.git import (
                GitBranchTool,
                GitCommitTool,
                GitDiffTool,
                GitLogTool,
                GitStatusTool,
            )

            tools.extend(
                [
                    GitStatusTool(),
                    GitDiffTool(),
                    GitLogTool(),
                    GitCommitTool(),
                    GitBranchTool(),
                ]
            )
        except ImportError as exc:
            logger.debug("Git tools unavailable: %s", exc)

        # Conditionally load code tools
        try:
            from ultron.tools.code import CodeEditTool, CodeSearchTool

            tools.extend(
                [
                    CodeSearchTool(),
                    CodeEditTool(),
                ]
            )
        except ImportError as exc:
            logger.debug("Code tools unavailable: %s", exc)

        # Conditionally load project intelligence tools
        try:
            from ultron.tools.project import (
                ProjectDepsTool,
                ProjectScanTool,
                TodoScanTool,
            )

            tools.extend(
                [
                    ProjectScanTool(),
                    ProjectDepsTool(),
                    TodoScanTool(),
                ]
            )
        except ImportError as exc:
            logger.debug("Project tools unavailable: %s", exc)

        # Conditionally load system tools
        try:
            from ultron.tools.system import DiskUsageTool, ProcessListTool, UptimeTool

            tools.extend(
                [
                    ProcessListTool(),
                    DiskUsageTool(),
                    UptimeTool(),
                ]
            )
        except ImportError as exc:
            logger.debug("System tools unavailable: %s", exc)

        # Self-modification tool (Day 6): git-guarded, gated edits to own code.
        try:
            from ultron.selfmod import EditLock, GitGuard, SelfModifyTool

            repo = config.project_dir
            tools.append(
                SelfModifyTool(
                    repo,
                    git_guard=GitGuard(repo),
                    edit_lock=EditLock(repo),
                    logger=logger,
                )
            )
        except ImportError as exc:
            logger.debug("Self-modification tool unavailable: %s", exc)

        for tool in tools:
            cls._apply_permissions(tool)

        return cls(tools, logger, metrics)

    def register(self, tool: Tool) -> None:
        """Register an additional tool at runtime.

        Args:
            tool: Tool instance to add.
        """
        self._tools[tool.name] = tool
        self._log.info("Registered tool: %s", tool.name)

    def describe_tools(self) -> str:
        """Return a prompt-ready description of every tool."""
        return "\n".join(
            f"- {tool.name}(...): {tool.description}" for tool in self._tools.values()
        )

    def is_final(self, name: str) -> bool:
        """Return True when a tool's result needs no follow-up LLM call."""
        tool = self._tools.get(name)
        return bool(tool) and bool(tool.result_is_final)

    def execute(self, call: ToolCall, source: str = "voice") -> ToolResult:
        """Route a tool call to its implementation.

        When a PermissionGate is configured, the call goes through
        ``gate.invoke`` — the single path to tool execution. Otherwise it
        executes directly (backwards-compatible for tests/startup).

        Args:
            call: Parsed tool call from the LLM.
            source: Origin of the call (``voice``, ``autonomy_loop``, ...).

        Returns:
            The tool's result, or a failure result for unknown/blocked tools.
        """
        tool = self._tools.get(call.name)
        if tool is None:
            self._metrics.increment("tools.unknown")
            return ToolResult(False, f"Unknown tool: {call.name}.")
        self._log.info("Executing tool %s (source=%s).", call.name, source)
        self._metrics.increment("tools.total")
        started = time.monotonic()
        try:
            if self._permission_gate is not None:
                result = self._permission_gate.invoke(
                    tool, {"arg": call.arg}, source=source
                )
            else:
                result = tool.run(call.arg)
        except PermissionDenied as exc:
            result = ToolResult(False, str(exc))
        except PermissionError as exc:
            # Day 7: out-of-scope filesystem path raised before the tool ran.
            self._log.warning("Tool %s blocked by scope policy: %s", call.name, exc)
            result = ToolResult(False, str(exc))
        except ToolError as exc:
            result = ToolResult(False, str(exc))
        except Exception as exc:
            self._log.exception("Tool %s crashed.", call.name)
            result = ToolResult(False, f"Tool {call.name} crashed: {exc}")
        elapsed = time.monotonic() - started
        self._metrics.observe("tools.latency", elapsed)
        outcome = "success" if result.success else "failure"
        self._metrics.increment(f"tools.{call.name}.{outcome}")
        return result

    def get_tool(self, name: str) -> Tool | None:
        """Retrieve a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def route_offline(self, text: str) -> ToolCall | None:
        """Map a user command to a tool call using keyword heuristics.

        Used when the LLM is unreachable so simple requests still work.
        Memory-intent phrases ("remember", "recall", "what ... like/about
        me") are routed before generic reads so they are never swallowed.

        Args:
            text: Raw user command text.

        Returns:
            A :class:`ToolCall` if a heuristic matched, else None.
        """
        lowered = normalize(text)

        if lowered.startswith("remember ") and not lowered.startswith("remember to "):
            return ToolCall("remember", text[len("remember ") :].strip())
        if lowered.startswith("recall "):
            return ToolCall("recall", text[len("recall ") :].strip())
        memory_subjects = ("remember", "like", "preferences", "about me", "my name")
        if "what" in lowered and any(subject in lowered for subject in memory_subjects):
            return ToolCall("recall", text.strip())

        if lowered.startswith("open "):
            target = text[len("open ") :].strip()
            if re.match(r"^[\w.-]+\.[a-z]{2,}$", target) or "://" in target:
                return ToolCall("open_website", target)
            return ToolCall("open_application", target)
        if lowered.startswith("quit ") or lowered.startswith("close "):
            target = text.split(" ", 1)[1].strip()
            return ToolCall("quit_application", target)
        if lowered.startswith("search for "):
            return ToolCall("search_google", text[len("search for ") :].strip())
        if lowered.startswith("google "):
            return ToolCall("search_google", text[len("google ") :].strip())
        if "screenshot" in lowered:
            return ToolCall("take_screenshot", "")
        if lowered.startswith("copy "):
            return ToolCall("copy_clipboard", text[len("copy ") :].strip())
        if lowered == "paste" or ("clipboard" in lowered and "what" in lowered):
            return ToolCall("paste_clipboard", "")
        if lowered.startswith("run ") or lowered.startswith("execute "):
            return ToolCall("run_command", text.split(" ", 1)[1].strip())
        if lowered.startswith("read file "):
            return ToolCall("read_file", text[len("read file ") :].strip())
        if lowered.startswith("read "):
            return ToolCall("read_file", text[len("read ") :].strip())
        if lowered.startswith("list ") or lowered.startswith("ls "):
            return ToolCall("list_directory", text.split(" ", 1)[1].strip())
        if lowered.startswith("write file "):
            remainder = text[len("write file ") :].strip()
            if _WRITE_SEPARATOR in remainder:
                return ToolCall("write_file", remainder)
            if " with " in remainder:
                path, content = remainder.split(" with ", 1)
                return ToolCall("write_file", f"{path}{_WRITE_SEPARATOR}{content}")
        if "system info" in lowered or "system status" in lowered:
            return ToolCall("system_info", "")
        return None
