"""Tests for ReasoningEngine and trace logging."""

from __future__ import annotations

import logging

from ultron.core.events import EventBus, EventType
from ultron.core.reasoning import ReasoningEngine, ReasoningPhase


def test_reasoning_trace_flow():
    bus = EventBus()
    engine = ReasoningEngine(event_bus=bus, logger=logging.getLogger("test"))
    trace = engine.start_trace("Build a web scraper")

    engine.record_step(trace, ReasoningPhase.UNDERSTAND, "User wants web scraping")
    engine.record_step(trace, ReasoningPhase.PLAN, "Step 1: fetch HTML, Step 2: parse")
    engine.finalize(trace, success=True, final_output="Done")

    assert len(trace.steps) == 2
    assert trace.success is True
    assert trace.final_output == "Done"
    assert len(bus.get_history()) == 2
    assert bus.get_history()[0].type == EventType.REASONING_STEP
