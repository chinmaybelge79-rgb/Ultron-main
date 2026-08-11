"""Base agent protocol and data structures."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ultron.core.events import EventBus
from ultron.core.llm import LLMProvider, ProviderRouter
from ultron.memory.store import MemoryStore
from ultron.tools.registry import ToolRegistry


@dataclass
class Task:
    """A task assigned to an agent.

    Attributes:
        id: Task identifier.
        description: Natural language description of what to accomplish.
        goal_id: Optional parent goal ID.
        context: Metadata or background information.
        created_at: Task creation timestamp.
    """

    id: str
    description: str
    goal_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AgentResult:
    """Outcome of an agent's execution.

    Attributes:
        success: Whether the agent completed the task.
        output: Human-readable response or generated output.
        artifacts: Created files, code diffs, or data structures.
        error: Error message if failed.
    """

    success: bool
    output: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class AgentContext:
    """Environment provided to an agent during execution.

    Attributes:
        config: Application configuration.
        memory: Persistent memory store.
        llm: LLM provider or router.
        tools: Tool registry.
        event_bus: System event bus.
    """

    config: Any
    memory: MemoryStore
    llm: ProviderRouter | LLMProvider | Any
    tools: ToolRegistry
    event_bus: EventBus | None = None


class Agent(ABC):
    """Base class for all Ultron autonomous agents."""

    name: str = ""
    description: str = ""
    capabilities: list[str] = []

    @abstractmethod
    def handle(self, task: Task, ctx: AgentContext) -> AgentResult:
        """Execute a task using the agent's reasoning, memory, and tools."""

    def can_handle(self, task: Task) -> float:
        """Return a capability score between 0.0 and 1.0 for handling the task."""
        return 0.5
