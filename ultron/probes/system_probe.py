"""CPU / memory / process sensing via ``psutil``.

If ``psutil`` is unavailable the probe degrades gracefully rather than
throwing at import time, so the daemon can start on machines without it.
"""

from __future__ import annotations

import logging

try:
    import psutil
except Exception:  # pragma: no cover - dependency not installed
    psutil = None

_log = logging.getLogger("ultron.probes.system")


class SystemProbe:
    """Samples CPU, memory, battery, and top processes."""

    def available(self) -> bool:
        """True when ``psutil`` is importable on this machine."""
        return psutil is not None

    def sample(self) -> dict:
        """Return a snapshot of system resource state.

        Returns an empty dict with a ``reason`` when ``psutil`` is missing
        (callers should treat that as \"no data\" rather than an error).
        """
        if psutil is None:
            return {"reason": "psutil not installed"}
        try:
            battery = psutil.sensors_battery()
            battery_dict = battery._asdict() if battery is not None else None
            top = sorted(
                (
                    {"name": p.info["name"], "cpu": p.info["cpu_percent"] or 0.0}
                    for p in psutil.process_iter(["name", "cpu_percent"])
                ),
                key=lambda proc: proc["cpu"],
                reverse=True,
            )[:5]
            return {
                "cpu_percent": psutil.cpu_percent(interval=0.5),
                "memory_percent": psutil.virtual_memory().percent,
                "battery": battery_dict,
                "top_processes": top,
            }
        except Exception as exc:  # noqa: BLE001 - never crash the probe loop
            _log.warning("SystemProbe.sample failed: %s", exc)
            return {"reason": str(exc)}
