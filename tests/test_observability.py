"""Tests that components actually emit telemetry through their Metrics."""

from __future__ import annotations

import logging

from ultron.core.assistant import Assistant
from ultron.monitoring import Metrics
from ultron.tools.base import Tool, ToolCall, ToolResult
from ultron.tools.registry import ToolRegistry
from ultron.utils import LLMError
from ultron.voice.speaker import Speaker


class StubLLM:
    def __init__(self, replies, configured=True):
        self._replies = list(replies)
        self.calls = 0
        self._configured = configured

    @property
    def configured(self):
        return self._configured

    def chat(self, messages):
        self.calls += 1
        if not self._replies:
            raise LLMError("no more replies")
        return self._replies.pop(0)


class StubFinalTool(Tool):
    name = "stub_final"
    result_is_final = True

    def run(self, arg):
        return ToolResult(True, "ok")


# ---------------------------------------------------------------------------
# Assistant wiring
# ---------------------------------------------------------------------------


def _assistant(config, memory, llm, metrics):
    registry = ToolRegistry(
        [StubFinalTool()], logging.getLogger("ultron.tools.test")
    )
    logger = logging.getLogger("ultron.assistant.test")
    logger.disabled = True
    return Assistant(config, memory, llm, registry, logger, metrics=metrics)


def test_assistant_records_online_metrics(config, memory, monkeypatch):
    monkeypatch.setattr("ultron.core.assistant.is_online", lambda timeout=2.0: True)
    metrics = Metrics()
    llm = StubLLM(["The sky is blue, sir."])
    asst = _assistant(config, memory, llm, metrics)
    asst.handle_command("what color is the sky?")
    snapshot = metrics.snapshot()
    assert snapshot["counters"]["commands_total"] == 1
    assert snapshot["counters"]["commands_online"] == 1
    assert "llm.chat" in snapshot["histograms"]


def test_assistant_records_llm_errors(config, memory):
    class BrokenLLM(StubLLM):
        def chat(self, messages):
            raise LLMError("server down")

    metrics = Metrics()
    asst = _assistant(config, memory, BrokenLLM(["never"]), metrics)
    asst._handle_online("hello")
    assert metrics.snapshot()["counters"]["llm.errors"] == 1


def test_assistant_records_offline_metrics(config, memory, monkeypatch):
    monkeypatch.setattr("ultron.core.assistant.is_online", lambda timeout=2.0: False)
    metrics = Metrics()
    llm = StubLLM([], configured=False)
    asst = _assistant(config, memory, llm, metrics)
    asst.handle_command("remember that cats are neat")
    snapshot = metrics.snapshot()
    assert snapshot["counters"]["commands_total"] == 1
    assert snapshot["counters"]["commands_offline"] == 1


# ---------------------------------------------------------------------------
# ToolRegistry wiring
# ---------------------------------------------------------------------------


def test_registry_records_tool_metrics(memory):
    metrics = Metrics()
    registry = ToolRegistry(
        [StubFinalTool()], logging.getLogger("ultron.tools.test"), metrics=metrics
    )
    registry.execute(ToolCall("stub_final", "x"))
    snapshot = metrics.snapshot()
    assert snapshot["counters"]["tools.total"] == 1
    assert snapshot["counters"]["tools.stub_final.success"] == 1
    assert "tools.latency" in snapshot["histograms"]


def test_registry_records_unknown_tool(memory):
    metrics = Metrics()
    registry = ToolRegistry([], logging.getLogger("ultron.tools.test"), metrics=metrics)
    registry.execute(ToolCall("nope", ""))
    assert metrics.snapshot()["counters"]["tools.unknown"] == 1


# ---------------------------------------------------------------------------
# Speaker wiring
# ---------------------------------------------------------------------------


def test_speaker_records_fallback(config, monkeypatch):
    object.__setattr__(config, "elevenlabs_api_key", "")
    metrics = Metrics()
    speaker = Speaker(config, logging.getLogger("ultron.speaker.test"), metrics=metrics)

    def fake_say(self, text):
        return None

    monkeypatch.setattr(
        "ultron.voice.speaker.MacOSVoiceEngine.speak", fake_say
    )
    speaker.speak("hello")
    snapshot = metrics.snapshot()
    assert snapshot["counters"]["tts.total"] == 1
    assert snapshot["counters"]["tts.fallback"] == 1