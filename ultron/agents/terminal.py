"""Terminal Agent for executing shell commands and managing environments safely."""

from __future__ import annotations

from ultron.agents.base import Agent, AgentContext, AgentResult, Task
from ultron.tools.base import ToolCall


class TerminalAgent(Agent):
    """Terminal Agent: Safely runs commands and inspects process state."""

    name = "terminal"
    description = "Executes shell commands, inspects files, and manages environments."
    capabilities = ["bash", "zsh", "shell", "run command", "terminal", "processes"]

    def can_handle(self, task: Task) -> float:
        text = task.description.lower()
        if any(
            w in text
            for w in ("run", "execute", "ls", "grep", "shell", "terminal", "process")
        ):
            return 0.85
        return 0.1

    def handle(self, task: Task, ctx: AgentContext) -> AgentResult:
        cmd = task.description
        if cmd.lower().startswith("run ") or cmd.lower().startswith("execute "):
            cmd = cmd.split(" ", 1)[1].strip()

        tool_call = ToolCall("run_command", cmd)
        res = ctx.tools.execute(tool_call)
        return AgentResult(
            success=res.success,
            output=res.output,
            error=None if res.success else res.output,
        )
