"""Memory data types for Ultron.

Defines the structured types used across the memory subsystem:
memory entries, facts, preferences, conversation summaries,
and the memory type taxonomy.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone


class MemoryType(enum.Enum):
    """Classification of memory entries."""

    SHORT_TERM = "short_term"
    CONVERSATION = "conversation"
    LONG_TERM = "long_term"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    PROJECT = "project"
    CODEBASE = "codebase"
    PREFERENCE = "preference"
    GOAL = "goal"
    TASK = "task"
    SCHEDULE = "schedule"


@dataclass(frozen=True)
class MemoryEntry:
    """A single memory entry with metadata.

    Attributes:
        content: The text content of the memory.
        memory_type: Classification of this memory.
        source: Where this memory came from (user, agent, system).
        importance: Importance score from 0.0 to 1.0.
        embedding: Optional vector embedding for semantic search.
        created_at: When this memory was created.
        tags: Optional tags for categorization.
    """

    content: str
    memory_type: MemoryType = MemoryType.LONG_TERM
    source: str = "user"
    importance: float = 0.5
    embedding: list[float] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: tuple[str, ...] = ()

    @property
    def age_seconds(self) -> float:
        """Seconds since this memory was created."""
        return (datetime.now(timezone.utc) - self.created_at).total_seconds()


@dataclass(frozen=True)
class Fact:
    """A remembered fact.

    Attributes:
        id: Database row ID.
        fact: The fact text.
        source: Origin of the fact.
        created_at: ISO timestamp.
    """

    id: int
    fact: str
    source: str = "user"
    created_at: str = ""


@dataclass(frozen=True)
class Preference:
    """A user preference key-value pair.

    Attributes:
        key: Preference key.
        value: Preference value.
        updated_at: ISO timestamp of last update.
    """

    key: str
    value: str
    updated_at: str = ""


@dataclass(frozen=True)
class ConversationSummary:
    """A compact summary of a past exchange.

    Attributes:
        id: Database row ID.
        summary: One-line summary text.
        created_at: ISO timestamp.
    """

    id: int
    summary: str
    created_at: str = ""
