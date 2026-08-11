"""Planner Agent for decomposing complex goals into sub-tasks."""

from __future__ import annotations

import json

from ultron.agents.base import Agent, AgentContext, AgentResult, Task


class PlannerAgent(Agent):
    """Planner Agent: Breaks down user goals into ordered tasks."""

    name = "planner"
    description = "Breaks down goals into multi-step execution plans."
    capabilities = ["planning", "task decomposition", "workflow design"]

    def can_handle(self, task: Task) -> float:
        text = task.description.lower()
        if any(
            w in text
            for w in ("plan", "break down", "roadmap", "steps to", "how to build")
        ):
            return 0.9
        return 0.3

    def handle(self, task: Task, ctx: AgentContext) -> AgentResult:
        prompt = (
            "You are the Planner Agent for Ultron. Break down this goal into "
            "3-5 distinct, ordered steps.\n"
            f"Goal: {task.description}\n\n"
            f'Reply with a JSON list of step strings, example: ["step 1", "step 2"]'
        )
        try:
            reply = ctx.llm.chat([{"role": "user", "content": prompt}])
            # Parse steps if JSON, else split by line
            if reply.startswith("[") and reply.endswith("]"):
                steps = json.loads(reply)
            else:
                steps = [
                    line.strip("- *123456789. ")
                    for line in reply.split("\n")
                    if line.strip()
                ]

            output = f"Plan for '{task.description}':\n" + "\n".join(
                f"{i + 1}. {s}" for i, s in enumerate(steps)
            )
            return AgentResult(success=True, output=output, artifacts={"steps": steps})
        except Exception as exc:
            return AgentResult(
                success=False, output="", error=f"Planning failed: {exc}"
            )
