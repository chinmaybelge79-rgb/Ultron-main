"""Continuous Reasoning Engine for Ultron.

Implements the multi-phase reasoning loop:
Understand -> Think -> Research -> Plan -> Execute -> Verify -> Reflect
-> Improve -> Remember
"""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ultron.core.events import Event, EventBus, EventType
from ultron.memory.store import MemoryStore


class ReasoningPhase(enum.Enum):
    """Phases of the continuous reasoning loop."""

    UNDERSTAND = "understand"
    THINK = "think"
    RESEARCH = "research"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    REFLECT = "reflect"
    IMPROVE = "improve"
    REMEMBER = "remember"


@dataclass
class ReasoningStep:
    """A single step in a reasoning trace."""

    phase: ReasoningPhase
    thought: str
    action: str | None = None
    observation: str | None = None
    confidence: float = 1.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ReasoningTrace:
    """Complete reasoning trace for a goal."""

    goal: str
    steps: list[ReasoningStep] = field(default_factory=list)
    success: bool = False
    final_output: str = ""

    def add_step(
        self,
        phase: ReasoningPhase,
        thought: str,
        action: str | None = None,
        observation: str | None = None,
        confidence: float = 1.0,
    ) -> ReasoningStep:
        step = ReasoningStep(phase, thought, action, observation, confidence)
        self.steps.append(step)
        return step

    def to_json(self) -> str:
        data = {
            "goal": self.goal,
            "success": self.success,
            "final_output": self.final_output,
            "steps": [
                {
                    "phase": step.phase.value,
                    "thought": step.thought,
                    "action": step.action,
                    "observation": step.observation,
                    "confidence": step.confidence,
                }
                for step in self.steps
            ],
        }
        return json.dumps(data)


class ReasoningEngine:
    """Orchestrates structured reasoning across complex tasks."""

    def __init__(
        self,
        memory: MemoryStore | None = None,
        event_bus: EventBus | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._memory = memory
        self._event_bus = event_bus
        self._log = logger or logging.getLogger("ultron.reasoning")

    def start_trace(self, goal: str) -> ReasoningTrace:
        """Initialize a new reasoning trace for a goal."""
        self._log.info("Starting reasoning trace for goal: %s", goal)
        return ReasoningTrace(goal=goal)

    def record_step(
        self,
        trace: ReasoningTrace,
        phase: ReasoningPhase,
        thought: str,
        action: str | None = None,
        observation: str | None = None,
        confidence: float = 1.0,
    ) -> ReasoningStep:
        """Record a reasoning step into the trace and publish event."""
        step = trace.add_step(phase, thought, action, observation, confidence)
        self._log.debug("[%s] %s", phase.value.upper(), thought)

        if self._event_bus:
            self._event_bus.publish(
                Event(
                    type=EventType.REASONING_STEP,
                    source="reasoning_engine",
                    data={
                        "goal": trace.goal,
                        "phase": phase.value,
                        "thought": thought,
                        "action": action,
                        "observation": observation,
                    },
                )
            )

        return step

    def finalize(self, trace: ReasoningTrace, success: bool, final_output: str) -> None:
        """Complete a trace and save to memory if available."""
        trace.success = success
        trace.final_output = final_output
        self._log.info("Finalized trace for '%s': success=%s", trace.goal, success)

        if self._memory:
            try:
                self._memory.store_reasoning_trace(
                    task_description=trace.goal,
                    trace_json=trace.to_json(),
                    outcome="success" if success else "failure",
                )
            except Exception as exc:
                self._log.warning("Could not persist reasoning trace: %s", exc)
