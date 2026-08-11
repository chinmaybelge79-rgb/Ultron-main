"""The Autonomy Loop: acting without being asked.

Turns probe events (Day 3) and the already-built-but-dormant goals/tasks schema
into an actual proactive decision-maker. Every action this loop decides to take
still routes through the Day 4 PermissionGate — autonomy is a *decider*, never
a bypass.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from ultron.agents.base import Task
from ultron.autonomy.priority import ACTION_THRESHOLD, OBSERVE_THRESHOLD, score


@dataclass
class Candidate:
    """One thing the loop might act on.

    Attributes:
        source: ``probe_event`` | ``pending_goal`` | ``pending_task``.
        description: Human-readable reason for the candidate.
        urgency: 0–10 from the priority scoring rules.
        payload: Kind-specific data.
    """

    source: str
    description: str
    urgency: int
    payload: dict


class AutonomyLoop:
    """Ranks candidates and dispatches high-urgency work.

    Args:
        memory: The shared MemoryStore (goals/tasks are its first real callers).
        orchestrator: The :class:`Orchestrator` used for execution.
        kill_switch: Consulted before every tick (belt & suspenders).
        permission_gate: Passed for awareness/audit; actual enforcement happens
            inside the tool registry the orchestrator's agents use.
        self_improve: Optional :class:`SelfImprovementEngine` whose success
            rates feed priority ranking.
        ctx_factory: Callable() -> AgentContext used to build an execution
            context for the orchestrator.
        speaker: Optional speaker for surfacing low-urgency observations.
        min_confidence: Reserved threshold (kept for tuning flexibility).
    """

    def __init__(
        self,
        memory,
        orchestrator,
        kill_switch,
        permission_gate,
        self_improve=None,
        ctx_factory=None,
        speaker=None,
        min_confidence: float = 0.6,
    ) -> None:
        self._memory = memory
        self._orchestrator = orchestrator
        self._kill_switch = kill_switch
        self._gate = permission_gate
        self._self_improve = self_improve
        self._ctx_factory = ctx_factory
        self._speaker = speaker
        self._min_confidence = min_confidence
        self._inbox: list[Candidate] = []
        self._lock = threading.Lock()
        self._log = logging.getLogger("ultron.autonomy")

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def on_probe_event(self, event) -> None:
        """Queue a probe event as a scored candidate."""
        urgency = score(event.kind, self._agent_success_rate())
        candidate = Candidate(
            source="probe_event",
            description=self._describe_event(event),
            urgency=urgency,
            payload=getattr(event, "payload", {}),
        )
        self._log.info("Probe event queued: %s (urgency=%d)", event.kind, urgency)
        with self._lock:
            self._inbox.append(candidate)

    def _describe_event(self, event) -> str:
        if event.kind == "idle":
            return f"System idle for {event.payload.get('seconds', 0):.0f}s."
        if event.kind == "resource_pressure":
            return f"CPU pressure at {event.payload.get('cpu_percent', '?')}%."
        if event.kind == "network_changed":
            return f"Network changed to {event.payload.get('ssid')}."
        if event.kind == "app_launched":
            return f"Application launched: {event.payload.get('app')}."
        if event.kind == "app_quit":
            return f"Application quit: {event.payload.get('app')}."
        return f"System event: {event.kind}."
    # ------------------------------------------------------------------
    # Decision tick
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """Score pending goals/tasks, pick the best candidate, and act."""
        if self._kill_switch.is_active():
            return
        with self._lock:
            self._inbox.extend(self._score_pending_goals_and_tasks())
            if not self._inbox:
                return
            best = max(self._inbox, key=lambda c: c.urgency)
            self._inbox.clear()
        if best.urgency < ACTION_THRESHOLD:
            return  # not worth interrupting anyone or spending a step budget on

        task = Task(id=f"auto-{int(time.time())}", description=best.description)
        ctx = self._ctx_factory() if self._ctx_factory else None
        self._dispatch(best, task, ctx)

    def _score_pending_goals_and_tasks(self) -> list[Candidate]:
        candidates: list[Candidate] = []
        try:
            for gid, title, description, priority in self._memory.get_active_goals():
                candidates.append(
                    Candidate(
                        source="pending_goal",
                        description=description or title,
                        urgency=score("pending_goal", self._agent_success_rate()),
                        payload={"goal_id": gid, "priority": priority},
                    )
                )
            for tid, title, description in self._memory.get_pending_tasks():
                candidates.append(
                    Candidate(
                        source="pending_task",
                        description=description or title,
                        urgency=score("pending_task", self._agent_success_rate()),
                        payload={"task_id": tid},
                    )
                )
        except Exception as exc:  # noqa: BLE001 - never let memory break a tick
            self._log.warning("Could not read goals/tasks: %s", exc)
        return candidates

    def _dispatch(self, best: Candidate, task: Task, ctx) -> None:
        """Split by tier: observe low-urgency probe events, act on the rest."""
        if best.source == "probe_event" and best.urgency < OBSERVE_THRESHOLD:
            self._observe(best.description)
            return
        if ctx is None:
            self._log.warning(
                "No AgentContext factory provided; cannot dispatch '%s'.",
                best.description,
            )
            return
        result = self._orchestrator.handle(task, ctx)
        self._log.info(
            "Autonomy task '%s' -> success=%s", best.description, result.success
        )
        try:
            self._memory.store_reasoning_trace(task.id, result.trace)
        except Exception as exc:  # noqa: BLE001
            self._log.debug("Could not store reasoning trace: %s", exc)

    def _observe(self, observation: str) -> None:
        """Surface a low-urgency signal as a spoken observation, no tools."""
        self._log.info("Autonomy observation: %s", observation)
        if self._speaker is not None:
            self._speaker.speak(observation)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _agent_success_rate(self) -> float | None:
        if self._self_improve is not None:
            try:
                return self._self_improve.get_agent_stats(
                    "orchestrator"
                ).success_rate
            except Exception:  # noqa: BLE001
                return None
        return None

