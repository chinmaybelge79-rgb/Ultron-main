"""Tests for system, project, and browser/vision agents and self-improvement."""

from __future__ import annotations

import logging
import subprocess

from ultron.agents.base import AgentContext, Task
from ultron.agents.browser import BrowserAgent, html_to_text
from ultron.agents.vision import VisionAgent
from ultron.core.self_improve import AgentStats, SelfImprovementEngine
from ultron.tools.registry import ToolRegistry
from ultron.tools.system import DiskUsageTool, ProcessListTool, UptimeTool

# ---------------------------------------------------------------------------
# System tools
# ---------------------------------------------------------------------------


def test_process_list_success(monkeypatch):
    fake = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="PID %CPU %MEM COMMAND\n1 0.0 0.0 python\n"
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
    result = ProcessListTool().run("python")
    assert result.success
    assert "python" in result.output


def test_process_list_empty(monkeypatch):
    fake = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="PID %CPU %MEM COMMAND\n"
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
    result = ProcessListTool().run("no-match-xyz")
    assert result.success
    assert "No processes match" in result.output


def test_process_list_missing_arg():
    result = ProcessListTool().run("")
    assert result.success


def test_disk_usage(monkeypatch):
    fake = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=(
            "Filesystem Size Used Avail Capacity Mounted on\n"
            "/dev/disk1 500G 200G 300G 40% /\n"
        ),
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
    result = DiskUsageTool().run("/")
    assert result.success
    assert "/dev/disk1" in result.output


def test_uptime(monkeypatch):
    fake = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="10:00  up 5 days, 1:02, 3 users\n"
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
    result = UptimeTool().run("")
    assert result.success
    assert "up 5 days" in result.output


# ---------------------------------------------------------------------------
# Project intelligence tools
# ---------------------------------------------------------------------------


def test_project_scan(tmp_path):
    (tmp_path / "mod.py").write_text("# def hi():\n#     pass\n")
    (tmp_path / "mod2.py").write_text("# TODO: fix later\n")
    from ultron.tools.project import ProjectScanTool

    result = ProjectScanTool().run(str(tmp_path))
    assert result.success
    assert "TODO/FIXME markers: 1" in result.output


def test_project_deps(tmp_path):
    (tmp_path / "main.py").write_text("import os\nfrom helper import x\n")
    (tmp_path / "helper.py").write_text("x = 1\n")
    from ultron.tools.project import ProjectDepsTool

    result = ProjectDepsTool().run(str(tmp_path))
    assert result.success
    assert "main.py" in result.output


def test_todo_scan(tmp_path):
    (tmp_path / "a.py").write_text("# TODO: cleanup\n# FIXME: crash\n")
    from ultron.tools.project import TodoScanTool

    result = TodoScanTool().run(str(tmp_path))
    assert result.success
    assert "TODO" in result.output
    assert "FIXME" in result.output


def test_tools_registered(config, memory):
    registry = ToolRegistry.build_default(config, memory, logging.getLogger("test"))
    for name in ("project_scan", "process_list", "todo_scan"):
        assert registry.get_tool(name) is not None


# ---------------------------------------------------------------------------
# Browser agent
# ---------------------------------------------------------------------------


def test_html_to_text_strips_markup():
    html = (
        "<html><body><script>var x=1;</script><h1>Hi</h1><p>A &amp; B</p></body></html>"
    )
    text = html_to_text(html)
    assert "Hi" in text
    assert "A & B" in text
    assert "<" not in text.split("A")[0]


class DummyLLM:
    def chat(self, messages):
        return "research answer"


class _FakeTools:
    def execute(self, call):
        from ultron.tools.base import ToolResult

        return ToolResult(True, "search launched")


def _ctx(config, memory):
    return AgentContext(
        config=config,
        memory=memory,
        llm=DummyLLM(),
        tools=_FakeTools(),
    )


def test_browser_agent_can_handle_url():
    agent = BrowserAgent()
    assert (
        agent.can_handle(Task(id="1", description="Look at https://example.com")) == 0.9
    )


def test_browser_agent_search_routes_to_tool(config, memory):
    agent = BrowserAgent()
    result = agent.handle(
        Task(id="1", description="search for tasty pizza"), _ctx(config, memory)
    )
    assert result.success
    assert "search" in result.output.lower()


def test_browser_agent_fetch_failure(config, memory):
    agent = BrowserAgent(timeout=0.01)
    content = agent.fetch_url("http://127.0.0.1:1/nonexistent")
    assert content is None


# ---------------------------------------------------------------------------
# Vision agent
# ---------------------------------------------------------------------------


def test_vision_agent_routing(config, memory):
    agent = VisionAgent()
    assert agent.can_handle(Task(id="1", description="look at the screen")) == 0.85
    assert agent.can_handle(Task(id="1", description="open safari")) < 0.85


def test_vision_agent_extract_path():
    assert VisionAgent._extract_path("Screenshot saved to /tmp/x.png.") == "/tmp/x.png"
    assert VisionAgent._extract_path("nothing here") is None


def test_vision_agent_no_image(config, memory):
    from ultron.tools.base import ToolResult

    class Tools:
        def execute(self, call):
            return ToolResult(False, "failed")

    ctx = AgentContext(config=config, memory=memory, llm=DummyLLM(), tools=Tools())
    result = VisionAgent().handle(Task(id="1", description="describe screen"), ctx)
    assert result.success is False


# ---------------------------------------------------------------------------
# Self-improvement engine
# ---------------------------------------------------------------------------


def test_agent_stats_success_rate():
    stats = AgentStats(name="coder")
    stats.attempts = 4
    stats.successes = 3
    stats.failures = 1
    assert stats.success_rate == 0.75
    assert stats.avg_latency == 0.0


def test_self_improve_records_and_insights():
    engine = SelfImprovementEngine(logger=logging.getLogger("test"))
    engine.record_agent_result("coder", False, latency=1.0)
    engine.record_agent_result("coder", False, latency=1.0)
    engine.record_agent_result("planner", True, latency=2.0)

    weakest = engine.weakest_agents(min_attempts=2)
    assert weakest[0].name == "coder"
    assert engine.fastest_agents()[0].name == "coder"

    suggestions = engine.suggestions()
    assert any("coder" in idea for idea in suggestions)


def test_self_improve_persist(memory):
    engine = SelfImprovementEngine(memory=memory, logger=logging.getLogger("test"))
    engine.record_agent_result("coder", True)
    engine.persist()
    traces = memory.get_reasoning_traces(limit=5)
    assert len(traces) >= 1
