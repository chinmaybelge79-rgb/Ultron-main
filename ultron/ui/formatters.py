"""Output formatters for terminal display and rich logging."""

from __future__ import annotations


def format_status_header(status: str = "ONLINE") -> str:
    """Return a stylized status header."""
    return f"🤖 ULTRON OS v0.2.0 | Mode: Local-First | Status: [{status}]"


def format_reasoning_step(phase: str, thought: str) -> str:
    """Format a reasoning step for terminal display."""
    return f"🧠 [{phase.upper()}] {thought}"


def format_agent_action(agent_name: str, action: str) -> str:
    """Format an agent action line."""
    return f"⚡ Agent [{agent_name.upper()}]: {action}"
