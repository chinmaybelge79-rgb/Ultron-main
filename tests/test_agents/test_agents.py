"""Tests for agent framework, registry, and orchestrator dispatch."""

from __future__ import annotations

import logging

from ultron.agents.base import AgentContext, Task
from ultron.agents.coder import CoderAgent
from ultron.agents.orchestrator import Orchestrator
from ultron.agents.planner import PlannerAgent
from ultron.agents.registry import AgentRegistry
from ultron.agents.terminal import TerminalAgent
from ultron.tools.registry import ToolRegistry


class DummyLLM:
    def chat(self, messages):
        return "Dummy response"


def _make_context(config, memory):
    return AgentContext(
        config=config,
        memory=memory,
        llm=DummyLLM(),
        tools=ToolRegistry.build_default(config, memory, logging.getLogger("test")),
    )


def test_registry_registration():
    registry = AgentRegistry()
    planner = PlannerAgent()
    registry.register(planner)

    assert registry.get("planner") == planner
    assert len(registry.list_agents()) == 1


def test_registry_find_best_agent():
    registry = AgentRegistry()
    registry.register(PlannerAgent())
    registry.register(CoderAgent())
    registry.register(TerminalAgent())

    task = Task(id="1", description="Fix bug in python code")
    best = registry.find_best_agent(task)
    assert best is not None
    assert best.name == "coder"


def test_orchestrator_dispatch(config, memory):
    ctx = _make_context(config, memory)
    orchestrator = Orchestrator()

    result = orchestrator.dispatch_text("Plan a new web app", ctx)
    assert result.success is True
    assert "Plan for" in result.output
