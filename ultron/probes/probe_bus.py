"""Aggregates every probe into one event stream for the Autonomy Loop.

The Probe Loop in ``ultron/daemon.py`` calls :meth:`ProbeBus.poll_once` on a
timer and feeds every emitted :class:`ProbeEvent` into the Autonomy Loop's
inbox (Day 5). The bus never touches the Action Layer directly.

Events are debounced/deduplicated: an idle event fires once per idle session
(not per poll), and app launch/quit events are inherently self-deduplicating
via the running-app diff.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from ultron.probes.system_probe import SystemProbe

# Tunable thresholds (per Day 3 these are reasonable, legible defaults).
_DEFAULT_IDLE_THRESHOLD_S = 300.0  # 5 minutes of no input
_DEFAULT_CPU_PRESSURE = 90.0  # percent


@dataclass
class ProbeEvent:
    """A single observed system event.

    Attributes:
        kind: ``app_launched`` | ``app_quit`` | ``idle`` |
            ``network_changed`` | ``resource_pressure``
        payload: Kind-specific data.
        timestamp: Unix seconds when the event was observed.
    """

    kind: str
    payload: dict
    timestamp: float


class ProbeBus:
    """Emits deduplicated :class:`ProbeEvent` objects from all probes.

    Args:
        system: A :class:`SystemProbe`.
        app: An app probe with ``diff_running_apps()``.
        idle: An idle probe with ``seconds_idle()``.
        network: A network probe with ``diff()``.
        on_event: Callable receiving each :class:`ProbeEvent`.
    """

    def __init__(
        self,
        system: SystemProbe,
        app,
        idle,
        network,
        on_event: Callable[[ProbeEvent], None],
        idle_threshold: float = _DEFAULT_IDLE_THRESHOLD_S,
        cpu_pressure: float = _DEFAULT_CPU_PRESSURE,
    ) -> None:
        self._system = system
        self._app = app
        self._idle = idle
        self._network = network
        self._on_event = on_event
        self._idle_threshold = idle_threshold
        self._cpu_pressure = cpu_pressure
        self._idle_evented: bool = False

    @staticmethod
    def _emit(on_event, kind: str, payload: dict) -> None:
        on_event(ProbeEvent(kind, payload, time.time()))

    def poll_once(self) -> None:
        """Sample every probe once and emit any resulting events."""
        # App launch/quit.
        launched, quit_apps = self._app.diff_running_apps()
        for name in launched:
            self._emit(self._on_event, "app_launched", {"app": name})
        for name in quit_apps:
            self._emit(self._on_event, "app_quit", {"app": name})

        # Idle (debounced: one event per idle session).
        idle_s = float(self._idle.seconds_idle())
        if idle_s >= self._idle_threshold:
            if not self._idle_evented:
                self._emit(self._on_event, "idle", {"seconds": idle_s})
                self._idle_evented = True
        else:
            self._idle_evented = False

        # Network change.
        changed, ssid = self._network.diff()
        if changed:
            self._emit(
                self._on_event, "network_changed", {"ssid": ssid, "previous": None}
            )

        # Resource pressure.
        sample = self._system.sample()
        cpu = sample.get("cpu_percent")
        if cpu is not None and cpu > self._cpu_pressure:
            self._emit(self._on_event, "resource_pressure", sample)
