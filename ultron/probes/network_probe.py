"""Wi-Fi network change detection by polling ``networksetup``.

Reports the current SSID and whether it changed since the last poll. Polling
``scutil``-adjacent tooling avoids needing any daemon-level entitlement and
keeps the probe purely local.
"""

from __future__ import annotations

import logging
import subprocess

_log = logging.getLogger("ultron.probes.network")


class NetworkProbe:
    """Tracks whether the connected Wi-Fi network has changed."""

    def __init__(self, interface: str = "en0") -> None:
        self._interface = interface
        self._last_ssid: str | None = None

    def current_ssid(self) -> str | None:
        """Return the current Wi-Fi SSID, or None when not on Wi-Fi."""
        try:
            out = subprocess.run(
                ["/usr/sbin/networksetup", "-getairportnetwork", self._interface],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("NetworkProbe command failed: %s", exc)
            return None
        if "Current Wi-Fi Network" not in out.stdout:
            return None
        return out.stdout.split(":", 1)[-1].strip() or None

    def diff(self) -> tuple[bool, str | None]:
        """Return ``(changed, ssid)`` where ``changed`` marks a network switch.

        The very first call never reports a change (it only seeds state), so a
        freshly started probe doesn't emit a spurious network_changed event.
        """
        ssid = self.current_ssid()
        changed = self._last_ssid is not None and ssid != self._last_ssid
        self._last_ssid = ssid
        return changed, ssid
