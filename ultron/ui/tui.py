"""Rich terminal dashboard UI for Ultron."""

from __future__ import annotations

import logging

from ultron.ui.formatters import (
    format_agent_action,
    format_reasoning_step,
)


class TerminalUI:
    """Renders visual status and agent progress in terminal output."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger("ultron.ui")
        import importlib.util

        self._rich_available = importlib.util.find_spec("rich") is not None

    def print_banner(self) -> None:
        """Display the Ultron startup banner."""
        banner = """
============================================================
           U L T R O N   A I   O P E R A T I N G   S Y S T E M
           Local-First • Privacy-First • Autonomous Agents
============================================================
"""
        print(banner)

    def print_reasoning(self, phase: str, thought: str) -> None:
        """Display a reasoning step."""
        print(format_reasoning_step(phase, thought))

    def print_action(self, agent_name: str, action: str) -> None:
        """Display an agent action."""
        print(format_agent_action(agent_name, action))

    def print_reply(self, reply: str) -> None:
        """Display assistant reply."""
        print(f"\n💬 Ultron: {reply}\n")
