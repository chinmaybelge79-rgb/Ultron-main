"""Base classes and data types for the Ultron tool framework.

Defines :class:`Tool` (the abstract base for every tool),
:class:`ToolCall` (a parsed request from the LLM), and
:class:`ToolResult` (the outcome of tool execution).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ultron.action.permissions import PermissionTier

_MAX_OUTPUT = 4000


@dataclass(frozen=True)
class ToolResult:
    """Outcome of a tool execution.

    Attributes:
        success: Whether the tool completed its work.
        output: Human-readable result text.
    """

    success: bool
    output: str


@dataclass(frozen=True)
class ToolCall:
    """A request to run a tool, parsed from LLM output.

    Attributes:
        name: Tool name.
        arg: Single string argument for the tool.
    """

    name: str
    arg: str


class Tool(ABC):
    """Base class for all tools.

    Attributes:
        name: Unique tool identifier used by the LLM.
        description: Help text shown to the LLM.
        result_is_final: When True, the tool's result is its own final
            answer and the assistant must not make a follow-up LLM call.
    """

    name: str = ""
    description: str = ""
    result_is_final: bool = False
    # Day 4: permission metadata enforced by the PermissionGate.
    tier: PermissionTier = PermissionTier.READ
    destructive: bool = False

    @abstractmethod
    def run(self, arg: str) -> ToolResult:
        """Execute the tool with a single argument.

        Args:
            arg: Tool argument provided by the LLM (may be empty).

        Returns:
            A :class:`ToolResult` describing the outcome.
        """
