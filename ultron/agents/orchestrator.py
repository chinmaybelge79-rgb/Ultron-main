"""Executive Orchestrator Agent for multi-agent workflows and task dispatch."""

from __future__ import annotations

import logging
import uuid

from ultron.agents.base import Agent, AgentContext, AgentResult, Task
from ultron.agents.browser import BrowserAgent
from ultron.agents.coder import CoderAgent
from ultron.agents.memory_agent import MemoryAgent
from ultron.agents.planner import PlannerAgent
from ultron.agents.registry import AgentRegistry
from ultron.agents.researcher import ResearchAgent
from ultron.agents.terminal import TerminalAgent
from ultron.agents.vision import VisionAgent
from ultron.core.events import Event, EventBus, EventType
from ultron.core.reasoning import ReasoningEngine, ReasoningPhase


class Orchestrator(Agent):
    """Executive Orchestrator Agent: Directs tasks to specialized sub-agents."""

    name = "orchestrator"
    description = "Executive coordinator for Ultron multi-agent system."
    capabilities = ["orchestration", "multi-agent coordination", "executive assistant"]

    def __init__(
        self,
        registry: AgentRegistry | None = None,
        reasoning: ReasoningEngine | None = None,
        event_bus: EventBus | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.registry = registry or AgentRegistry()
        self.reasoning = reasoning or ReasoningEngine()
        self.event_bus = event_bus
        self._log = logger or logging.getLogger("ultron.agents.orchestrator")
        self._register_default_agents()

    def _register_default_agents(self) -> None:
        """Register all default specialized agents if registry is empty."""
        if not self.registry.list_agents():
            self.registry.register(PlannerAgent())
            self.registry.register(CoderAgent())
            self.registry.register(TerminalAgent())
            self.registry.register(ResearchAgent())
            self.registry.register(MemoryAgent())
            self.registry.register(BrowserAgent())
            self.registry.register(VisionAgent())

    def can_handle(self, task: Task) -> float:
        return 1.0  # Orchestrator can coordinate any task

    def handle(self, task: Task, ctx: AgentContext) -> AgentResult:
        """Route task through Reasoning Engine and dispatch to best agent(s)."""
        trace = self.reasoning.start_trace(task.description)

        if self.event_bus:
            self.event_bus.publish(
                Event(
                    type=EventType.TASK_STARTED,
                    source=self.name,
                    data={"task_id": task.id, "description": task.description},
                )
            )

        # 1. UNDERSTAND
        self.reasoning.record_step(
            trace, ReasoningPhase.UNDERSTAND, f"Analyzing task: '{task.description}'"
        )

        # 2. SELECT AGENT
        best_agent = self.registry.find_best_agent(task)
        if best_agent and best_agent.name != self.name:
            self.reasoning.record_step(
                trace,
                ReasoningPhase.THINK,
                f"Selected specialized agent '{best_agent.name}' for execution.",
            )

            if self.event_bus:
                self.event_bus.publish(
                    Event(
                        type=EventType.AGENT_DISPATCH,
                        source=self.name,
                        data={"agent": best_agent.name, "task_id": task.id},
                    )
                )

            # 3. EXECUTE VIA AGENT
            self.reasoning.record_step(
                trace, ReasoningPhase.EXECUTE, f"Dispatching to {best_agent.name}"
            )
            result = best_agent.handle(task, ctx)

            # 4. VERIFY & REFLECT
            self.reasoning.record_step(
                trace,
                ReasoningPhase.VERIFY,
                f"Agent {best_agent.name} returned success={result.success}",
                observation=result.output[:200] if result.output else None,
            )

            self.reasoning.finalize(trace, result.success, result.output)

            if self.event_bus:
                event_type = (
                    EventType.TASK_COMPLETED
                    if result.success
                    else EventType.TASK_FAILED
                )
                self.event_bus.publish(
                    Event(
                        type=event_type,
                        source=self.name,
                        data={"task_id": task.id, "output": result.output},
                    )
                )

            return result

        # Fallback to direct execution using LLM
        self.reasoning.record_step(
            trace, ReasoningPhase.EXECUTE, "Handling request directly via LLM brain."
        )
        try:
            reply = ctx.llm.chat([{"role": "user", "content": task.description}])
            self.reasoning.finalize(trace, True, reply)
            return AgentResult(success=True, output=reply)
        except Exception as exc:
            self.reasoning.finalize(trace, False, str(exc))
            return AgentResult(success=False, output="", error=str(exc))

    def dispatch_text(self, user_text: str, ctx: AgentContext) -> AgentResult:
        """Convenience method to dispatch raw user text as a task."""
        task = Task(id=str(uuid.uuid4())[:8], description=user_text)
        return self.handle(task, ctx)
