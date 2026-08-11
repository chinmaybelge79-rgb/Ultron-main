"""Tests for the Day 3 system probes and the ProbeBus aggregator."""

from __future__ import annotations

import subprocess

import pytest

from ultron.probes.app_probe import AccessibilityError, AppProbe
from ultron.probes.probe_bus import ProbeBus
from ultron.probes.system_probe import SystemProbe

# ---------------------------------------------------------------------------
# SystemProbe
# ---------------------------------------------------------------------------


def test_system_probe_sample_with_psutil():
    probe = SystemProbe()
    if not probe.available():
        pytest.skip("psutil not installed")
    sample = probe.sample()
    assert "cpu_percent" in sample
    assert "memory_percent" in sample


# ---------------------------------------------------------------------------
# AppProbe
# ---------------------------------------------------------------------------


class _FakePopen:
    def __init__(self, output, returncode=0, stderr=""):
        self._output = output
        self._returncode = returncode
        self._stderr = stderr

    @property
    def stdout(self):
        return self._output

    @property
    def returncode(self):
        return self._returncode

    @property
    def stderr(self):
        return self._stderr


def test_app_probe_diff_running_apps(monkeypatch):
    calls = iter(
        [
            _FakePopen("Safari, Finder, Terminal,\n"),
            _FakePopen("Safari, Finder\n"),
        ]
    )
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: next(calls)
    )
    probe = AppProbe()
    # First diff seeds state -> no events.
    assert probe.diff_running_apps() == (set(), set())
    # Terminal quit.
    launched, quit_apps = probe.diff_running_apps()
    assert launched == set()
    assert quit_apps == {"Terminal"}


def test_app_probe_accessibility_error_loud(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _FakePopen("", returncode=1, stderr="osascript error"),
    )
    probe = AppProbe()
    with pytest.raises(AccessibilityError) as exc:
        probe.diff_running_apps()
    assert "Accessibility" in str(exc.value)


# ---------------------------------------------------------------------------
# NetworkProbe
# ---------------------------------------------------------------------------


def test_network_probe_detects_change(monkeypatch):
    import ultron.probes.network_probe as np_mod

    results = iter(
        [
            _FakePopen("Current Wi-Fi Network: HomeNet\n"),
            _FakePopen("Current Wi-Fi Network: OfficeNet\n"),
        ]
    )
    monkeypatch.setattr(np_mod.subprocess, "run", lambda *a, **k: next(results))
    probe = np_mod.NetworkProbe()
    # First call seeds state, no change.
    changed, ssid = probe.diff()
    assert changed is False and ssid == "HomeNet"
    changed, ssid = probe.diff()
    assert changed is True and ssid == "OfficeNet"


def test_network_probe_no_wifi(monkeypatch):
    import ultron.probes.network_probe as np_mod

    monkeypatch.setattr(
        np_mod.subprocess, "run", lambda *a, **k: _FakePopen("")
    )
    probe = np_mod.NetworkProbe()
    assert probe.diff() == (False, None)


# ---------------------------------------------------------------------------
# ProbeBus
# ---------------------------------------------------------------------------


class _StubApp:
    """Configurable stub for the app probe."""

    def __init__(self, diffs):
        self._diffs = list(diffs)

    def diff_running_apps(self):
        if self._diffs:
            return self._diffs.pop(0)
        return set(), set()


class _StubIdle:
    def __init__(self, seconds):
        self._seconds = list(seconds)

    def seconds_idle(self):
        return self._seconds.pop(0)


class _StubNetwork:
    def __init__(self, diffs):
        self._diffs = list(diffs)

    def diff(self):
        return self._diffs.pop(0)


class _StubSystem:
    def __init__(self, cpu):
        self._cpu = cpu

    def sample(self):
        return {"cpu_percent": self._cpu}


def _run_bus(probes, polls=1):
    events = []

    def on_event(event):
        events.append(event)

    bus = ProbeBus(*probes, on_event=on_event)
    for _ in range(polls):
        bus.poll_once()
    return events, bus


def test_probe_bus_emits_app_launch():
    app = _StubApp([({"Safari"}, set())])
    events, _ = _run_bus(
        (_StubSystem(20), app, _StubIdle([10]), _StubNetwork([(False, None)]))
    )
    kinds = [e.kind for e in events]
    assert kinds == ["app_launched"]
    assert events[0].payload == {"app": "Safari"}


def test_probe_bus_idle_debounced(tmp_path=None):
    # 360s idle => one idle event even across two polls (debounced).
    app = _StubApp([])
    events, _ = _run_bus(
        (
            _StubSystem(20),
            app,
            _StubIdle([360, 360]),
            _StubNetwork([(False, None), (False, None)]),
        ),
        polls=2,
    )
    assert [e.kind for e in events] == ["idle"]


def test_probe_bus_idle_resets_after_activity():
    # idle -> active -> idle again should emit twice.
    app = _StubApp([])
    events, _ = _run_bus(
        (
            _StubSystem(20),
            app,
            _StubIdle([360, 10, 360]),
            _StubNetwork([(False, None)] * 3),
        ),
        polls=3,
    )
    assert [e.kind for e in events] == ["idle", "idle"]


def test_probe_bus_resource_pressure():
    app = _StubApp([])
    events, _ = _run_bus(
        (
            _StubSystem(95),
            app,
            _StubIdle([10]),
            _StubNetwork([(False, None)]),
        )
    )
    assert [e.kind for e in events] == ["resource_pressure"]


def test_probe_bus_network_changed():
    app = _StubApp([])
    events, _ = _run_bus(
        (
            _StubSystem(20),
            app,
            _StubIdle([10]),
            _StubNetwork([(True, "OfficeNet")]),
        )
    )
    assert [e.kind for e in events] == ["network_changed"]
