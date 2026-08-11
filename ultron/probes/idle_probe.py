"""Idle-time sensing via macOS Quartz event timestamps.

Uses ``pyobjc-framework-Quartz``'s
``CGEventSourceSecondsSinceLastEventType`` to report how long the machine has
been idle (no keyboard/mouse input). Degrades to ``0.0`` (assumed active) if
Quartz is unavailable so the probe loop never crashes on import.
"""

from __future__ import annotations

import logging

try:
    import Quartz  # type: ignore
except Exception:  # pragma: no cover - dependency not installed
    Quartz = None

_log = logging.getLogger("ultron.probes.idle")


class IdleProbe:
    """Reports seconds since the last HID input event."""

    def seconds_idle(self) -> float:
        """Return seconds since the last keyboard/mouse input (0.0 if unknown)."""
        if Quartz is None:
            return 0.0
        try:
            return float(
                Quartz.CGEventSourceSecondsSinceLastEventType(
                    Quartz.kCGEventSourceStateHIDSystemState,
                    Quartz.kCGAnyInputEventType,
                )
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("IdleProbe failed: %s", exc)
            return 0.0
