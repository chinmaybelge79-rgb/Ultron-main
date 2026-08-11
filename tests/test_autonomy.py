"""Tests for the Day 5 Autonomy Loop and its priority scoring."""

from __future__ import annotations

from ultron.autonomy.loop import AutonomyLoop
from ultron.autonomy.priority import score


class _KillSwitch:
    def __init__(self, active=False):
        self._active = active

    def is_active(self):
        return self._active


class _Orchestrator:
    """Records dispatched tasks so the loop's behavior is observable."""

    def __init__(self):
        self.calls = []

    def handle(self, task, ctx):
        self.calls.append((task, ctx))
        return _Result(True, "")


class _Result:
    def __init__(self, success, trace):
        self.success = success
        self.trace = trace
        self.output = ""


class _Speaker:
    def __init__(self):
        self.messages = []

    def speak(self, text):
        self.messages.append(text)


def _event(kind, payload=None, seconds=360):
    class E:
        def __init__(self, k, p, s):
            self.kind = k
            self.payload = p
            self.timestamp = s

    return E(kind, payload or {}, seconds)


# ---------------------------------------------------------------------------
# score()
# ---------------------------------------------------------------------------


def test_score_high_for_pending_task():
    assert score("pending_task", None) == 7


def test_score_low_success_rate_deprioritizes():
    low = score("pending_task", 0.0)
    high = score("pending_task", 1.0)
    # poor track record -> ranked strictly below a perfect one
    assert low < high
    assert score("pending_task", 0.0) < score("pending_task", None)


def test_score_capped_at_ten():
    assert score("pending_task", 1.0) <= 10


# ---------------------------------------------------------------------------
# AutonomyLoop
# ---------------------------------------------------------------------------


def test_tick_dispatches_pending_task(memory):
    memory.add_task("Tidy downloads", "Move the downloads into folders")
    orch = _Orchestrator()
    loop = AutonomyLoop(
        memory,
        orch,
        _KillSwitch(),
        None,
        ctx_factory=lambda: object(),
    )
    loop.tick()
    assert orch.calls, "expected a pending task to be dispatched"
    task, ctx = orch.calls[0]
    assert "folders" in task.description


def test_tick_ignores_below_threshold():
    memory = type("M", (), {"get_active_goals": lambda self: [],
                            "get_pending_tasks": lambda self: [],
                            "store_reasoning_trace": lambda *a, **k: None})()
    orch = _Orchestrator()
    loop = AutonomyLoop(memory, orch, _KillSwitch(), None, ctx_factory=lambda: object())
    # An idle probe event has urgency 2 (< ACTION_THRESHOLD=3) -> no action.
    loop.on_probe_event(_event("idle", {"seconds": 400}))
    loop.tick()
    assert orch.calls == []


def test_probe_event_observed_without_action():
    memory = type("M", (), {"get_active_goals": lambda self: [],
                            "get_pending_tasks": lambda self: [],
                            "store_reasoning_trace": lambda *a, **k: None})()
    orch = _Orchestrator()
    speaker = _Speaker()
    loop = AutonomyLoop(
        memory, orch, _KillSwitch(), None, ctx_factory=lambda: object(), speaker=speaker
    )
    # network_changed urgency 3 (>= ACTION_THRESHOLD, < OBSERVE_THRESHOLD):
    # passed to dispatch but split into a spoken observation, no tool call.
    loop.on_probe_event(_event("network_changed", {"ssid": "OfficeNet"}))
    loop.tick()
    assert speaker.messages, "expected a spoken observation"
    assert orch.calls == []


def test_high_urgency_probe_event_acts():
    memory = type("M", (), {"get_active_goals": lambda self: [],
                            "get_pending_tasks": lambda self: [],
                            "store_reasoning_trace": lambda *a, **k: None})()
    orch = _Orchestrator()
    loop = AutonomyLoop(
        memory, orch, _KillSwitch(), None, ctx_factory=lambda: object()
    )
    # resource_pressure urgency 6 >= OBSERVE_THRESHOLD -> dispatched as action.
    loop.on_probe_event(_event("resource_pressure", {"cpu_percent": 99}))
    loop.tick()
    assert orch.calls
    assert orch.calls[0][0].description  # task routed through orchestrator


def test_kill_switch_blocks_dispatch(memory):
    memory.add_task("Do something", "Do the thing")
    orch = _Orchestrator()
    loop = AutonomyLoop(
        memory, orch, _KillSwitch(active=True), None, ctx_factory=lambda: object()
    )
    loop.on_probe_event(_event("resource_pressure"))
    loop.tick()
    assert orch.calls == []
