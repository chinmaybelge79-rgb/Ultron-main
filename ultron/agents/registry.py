"""Agent registry for dynamic agent lookup and task dispatch."""

from __future__ import annotations

import logging

from ultron.agents.base import Agent, Task


class AgentRegistry:
    """Holds all active agents and routes tasks to the best match."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._agents: dict[str, Agent] = {}
        self._log = logger or logging.getLogger("ultron.agents.registry")

    def register(self, agent: Agent) -> None:
        """Register an agent instance."""
        self._agents[agent.name] = agent
        self._log.info("Registered agent: %s (%s)", agent.name, agent.description)

    def get(self, name: str) -> Agent | None:
        """Retrieve an agent by name."""
        return self._agents.get(name)

    def list_agents(self) -> list[Agent]:
        """Return all registered agents."""
        return list(self._agents.values())

    def find_best_agent(self, task: Task) -> Agent | None:
        """Find the agent with the highest capability score for a task."""
        if not self._agents:
            return None

        best_agent: Agent | None = None
        best_score = -1.0

        for agent in self._agents.values():
            score = agent.can_handle(task)
            if score > best_score:
                best_score = score
                best_agent = agent

        return best_agent
