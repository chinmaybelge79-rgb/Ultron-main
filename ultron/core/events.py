"""Event bus for inter-agent communication and system observability."""

from __future__ import annotations

import enum
import logging
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_EVENT_HISTORY_LIMIT = 500


class EventType(enum.Enum):
    """System event types."""

    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"

    REASONING_STEP = "reasoning_step"
    AGENT_DISPATCH = "agent_dispatch"

    TOOL_CALLED = "tool_called"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"

    MEMORY_STORED = "memory_stored"
    VOICE_SPOKEN = "voice_spoken"


@dataclass(frozen=True)
class Event:
    """A system event.

    Attributes:
        type: Event classification.
        source: Entity emitting the event (e.g. 'orchestrator', 'coder_agent').
        data: Payload metadata.
        timestamp: Event creation timestamp.
    """

    type: EventType
    source: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    """Publish-subscribe event bus for Ultron agents and subsystems."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._subscribers: dict[EventType, list[Callable[[Event], None]]] = defaultdict(
            list
        )
        self._log = logger or logging.getLogger("ultron.events")
        self._history: deque[Event] = deque(maxlen=_EVENT_HISTORY_LIMIT)

    def subscribe(
        self, event_type: EventType, callback: Callable[[Event], None]
    ) -> None:
        """Subscribe a callback to an event type."""
        self._subscribers[event_type].append(callback)

    def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        self._history.append(event)
        self._log.debug(
            "Event [%s] from %s: %s", event.type.value, event.source, event.data
        )
        for callback in self._subscribers.get(event.type, []):
            try:
                callback(event)
            except Exception as exc:
                self._log.warning(
                    "Event listener error (%s): %s", event.type.value, exc
                )

    def get_history(self, limit: int = 50) -> list[Event]:
        """Return recent event history (most recent last)."""
        return list(self._history)[-limit:]
