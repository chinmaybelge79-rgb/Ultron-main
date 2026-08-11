"""Memory Agent for explicit memory storage, recall, and management."""

from __future__ import annotations

from ultron.agents.base import Agent, AgentContext, AgentResult, Task


class MemoryAgent(Agent):
    """Memory Agent: Manages user facts, preferences, and semantic recall."""

    name = "memory_agent"
    description = "Manages long-term facts, preferences, goals, and vector memory."
    capabilities = ["remember", "recall", "preferences", "facts", "goals"]

    def can_handle(self, task: Task) -> float:
        text = task.description.lower()
        if any(
            w in text
            for w in ("remember", "recall", "preference", "what do i", "about me")
        ):
            return 0.9
        return 0.1

    def handle(self, task: Task, ctx: AgentContext) -> AgentResult:
        text = task.description
        stored = ctx.memory.extract_and_store(text)
        if stored:
            return AgentResult(success=True, output=f"Remembered: {', '.join(stored)}")

        context = ctx.memory.build_context(text)
        if context:
            return AgentResult(
                success=True, output=f"Here is what I remember:\n{context}"
            )

        return AgentResult(
            success=True,
            output="I don't have any relevant memories stored for that yet, sir.",
        )
