"""Coding Agent for software development, debugging, and code editing."""

from __future__ import annotations

from ultron.agents.base import Agent, AgentContext, AgentResult, Task
from ultron.tools.base import ToolCall


class CoderAgent(Agent):
    """Coder Agent: Reads, edits, generates, and debugs code."""

    name = "coder"
    description = "Software development, code editing, refactoring, and debugging."
    capabilities = [
        "python",
        "javascript",
        "typescript",
        "git",
        "code edit",
        "debugging",
        "code search",
    ]

    def can_handle(self, task: Task) -> float:
        text = task.description.lower()
        if any(
            w in text
            for w in (
                "code",
                "function",
                "fix bug",
                "refactor",
                "write script",
                "python",
                "git",
                "edit file",
            )
        ):
            return 0.95
        return 0.2

    def handle(self, task: Task, ctx: AgentContext) -> AgentResult:
        # Search code tools or run edit/read tools as needed
        if "search" in task.description.lower():
            tool_call = ToolCall("code_search", task.description)
            res = ctx.tools.execute(tool_call)
            return AgentResult(success=res.success, output=res.output)
        elif (
            "git status" in task.description.lower()
            or "git" in task.description.lower()
        ):
            tool_call = ToolCall("git_status", "")
            res = ctx.tools.execute(tool_call)
            return AgentResult(success=res.success, output=res.output)

        # Standard LLM coding prompt
        prompt = (
            f"You are Ultron's Lead Coder Agent. Help the user with this request:\n"
            f"{task.description}\n\n"
            f"Be precise, clean, and safe."
        )
        try:
            reply = ctx.llm.chat([{"role": "user", "content": prompt}])
            return AgentResult(success=True, output=reply)
        except Exception as exc:
            return AgentResult(
                success=False, output="", error=f"Coding agent failed: {exc}"
            )
