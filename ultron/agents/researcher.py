"""Research Agent for searching web, memory, and documentation."""

from __future__ import annotations

from ultron.agents.base import Agent, AgentContext, AgentResult, Task
from ultron.tools.base import ToolCall


class ResearchAgent(Agent):
    """Research Agent: Gathers information from search, memory, and web."""

    name = "researcher"
    description = "Searches web, documentation, and memory for information."
    capabilities = ["research", "google search", "memory search", "fact finding"]

    def can_handle(self, task: Task) -> float:
        text = task.description.lower()
        if any(
            w in text
            for w in ("search", "find", "lookup", "research", "what is", "who is")
        ):
            return 0.8
        return 0.2

    def handle(self, task: Task, ctx: AgentContext) -> AgentResult:
        query = task.description
        # Try memory recall first
        mem_ctx = ctx.memory.build_context(query)

        # Also perform google search if requested
        if "google" in query.lower() or "search web" in query.lower():
            search_query = query.replace("google", "").replace("search web", "").strip()
            ctx.tools.execute(ToolCall("search_google", search_query))
            output = f"Google Search launched for '{search_query}'.\n"
            if mem_ctx:
                output += f"Memory Context:\n{mem_ctx}"
            return AgentResult(success=True, output=output)

        prompt = (
            f"You are Ultron's Research Agent. Answer this query concisely:\n"
            f"Query: {query}\n"
            f"Memory Context:\n{mem_ctx or '(none)'}"
        )
        try:
            reply = ctx.llm.chat([{"role": "user", "content": prompt}])
            return AgentResult(success=True, output=reply)
        except Exception as exc:
            return AgentResult(
                success=False, output="", error=f"Research failed: {exc}"
            )
