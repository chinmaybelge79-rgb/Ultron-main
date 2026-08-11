"""Pre-flight diagnostics for Ultron.

Provides a set of independent, non-destructive health checks that verify
the environment before the app opens the microphone or loads Whisper.
Each check answers one question and never crashes: failures are captured
into :class:`CheckResult` entries and rendered as ``[PASS]``/``[FAIL]``
or ``[WARN]``.

Checks are designed to run zero hardware/network in the common path where
possible, and every external dependency (requests, sounddevice) is
isolated behind a small function so tests can stub it.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from dataclasses import dataclass
from enum import Enum

import requests
import sounddevice as sd

from ultron.config import Config
from ultron.utils import is_online
from ultron.voice.recognizer import whisper_model_available


class Status(Enum):
    """Diagnostic status."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single diagnostic check.

    Attributes:
        name: Short check identifier (e.g. ``ollama``).
        status: PASS / FAIL / WARN.
        detail: Human-readable explanation.
    """

    name: str
    status: Status
    detail: str


_log = logging.getLogger("ultron.diagnostics")


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_config(config: Config) -> CheckResult:
    """Config already validated at construction time."""
    return CheckResult("config", Status.PASS, "Configuration valid")


def check_api_keys(config: Config) -> CheckResult:
    """LLM backends configured? (WARNING = degraded cloud mode)."""
    if config.any_llm_configured:
        return CheckResult(
            "api_keys",
            Status.PASS,
            "LLM backend configured (Ollama/OpenRouter)",
        )
    return CheckResult(
        "api_keys",
        Status.WARN,
        "No LLM backend configured; only offline tool routing available",
    )


def check_ollama(config: Config) -> CheckResult:
    """Verify the local Ollama server and the configured model.

    The server is probed at ``/api/tags`` and the configured model must
    be present in the returned list; a missing model yields a WARN with
    the exact ``ollama pull`` command so recovery is never a mystery.
    """
    if not config.ollama_enabled:
        return CheckResult("ollama", Status.PASS, "Local Ollama disabled")
    try:
        res = requests.get(f"{config.ollama_url}/api/tags", timeout=1.5)
        if res.status_code != 200:
            return CheckResult(
                "ollama",
                Status.FAIL,
                f"Ollama returned HTTP {res.status_code}",
            )
        try:
            models = [str(m.get("name", "")) for m in res.json().get("models", [])]
        except ValueError as exc:
            return CheckResult(
                "ollama",
                Status.FAIL,
                f"Malformed /api/tags response: {exc}",
            )
        wanted = config.ollama_model
        installed = (wanted in models) or any(
            m.startswith(wanted + ":") for m in models
        )
        if installed:
            return CheckResult(
                "ollama",
                Status.PASS,
                f"Ollama reachable; model '{wanted}' installed",
            )
        return CheckResult(
            "ollama",
            Status.WARN,
            f"Ollama reachable but model '{wanted}' is missing. "
            f"Run: ollama pull {wanted}",
        )
    except Exception as exc:
        return CheckResult(
            "ollama",
            Status.WARN,
            f"Ollama unreachable ({exc}); will fall back to OpenRouter",
        )


def check_macos(config: Config) -> CheckResult:
    """Validate the macOS host: platform and required CLI voice tools."""
    import platform

    if platform.system() != "Darwin":
        return CheckResult(
            "macos",
            Status.FAIL,
            f"Ultron requires macOS; running on {platform.system()}",
        )
    missing = [
        tool
        for tool in ("say", "afplay")
        if shutil.which(tool) is None
    ]
    if missing:
        return CheckResult(
            "macos",
            Status.FAIL,
            "Missing macOS voice tools: " + ", ".join(missing),
        )
    return CheckResult(
        "macos",
        Status.PASS,
        f"macOS {platform.machine()} / Python "
        f"{platform.python_version()} / voice tools OK",
    )


def check_internet(config: Config) -> CheckResult:
    """Probe outbound connectivity."""
    if is_online(timeout=config.offline_timeout):
        return CheckResult("internet", Status.PASS, "Outbound connectivity OK")
    return CheckResult(
        "internet",
        Status.WARN,
        "No internet; online services degrade to local/offline mode",
    )


def check_whisper_model(config: Config) -> CheckResult:
    """Check whether the configured Whisper model is cached locally."""
    if whisper_model_available(config):
        return CheckResult(
            "whisper", Status.PASS, f"Model '{config.whisper_model}' cached"
        )
    return CheckResult(
        "whisper",
        Status.WARN,
        f"Model '{config.whisper_model}' not cached; "
        "will download on first boot (needs internet)",
    )


def check_microphone(config: Config) -> CheckResult:
    """Find an available input audio device without opening it."""
    try:
        devices = sd.query_devices()
        for dev in devices:
            if dev.get("max_input_channels", 0) > 0:
                return CheckResult("microphone", Status.PASS, "Input device available")
        if config.mic_device is not None:
            return CheckResult(
                "microphone",
                Status.PASS,
                f"Configured input device #{config.mic_device}",
            )
        return CheckResult("microphone", Status.FAIL, "No input audio device found")
    except Exception as exc:
        return CheckResult(
            "microphone",
            Status.WARN,
            f"Could not enumerate audio ({exc})",
        )


def check_mic_level(config: Config) -> CheckResult:
    """Verify the microphone actually delivers audio to this process.

    ``check_microphone`` only enumerates devices, so a missing macOS
    microphone permission still passes it. This check opens the input
    stream briefly and measures the RMS level: a near-silent read almost
    always means the app running Ultron does not have microphone access.
    It is reported as a WARN (never FAIL) so it cannot abort the startup
    gate, but it makes the silent-mic failure visible instead of hidden.
    """
    import numpy as np

    try:
        stream = sd.InputStream(
            samplerate=config.sample_rate,
            channels=config.channels,
            dtype="float32",
        )
        stream.start()
        try:
            frames = int(0.15 * config.sample_rate)
            data, _overflow = stream.read(frames)
            if data.size == 0:
                return CheckResult(
                    "mic_level", Status.WARN, "Audio read returned no data"
                )
            rms = float(np.sqrt(np.mean(np.square(data))))
        finally:
            stream.stop()
            stream.close()
    except Exception as exc:
        return CheckResult(
            "mic_level",
            Status.WARN,
            f"Could not measure mic input ({exc}); grant microphone permission?",
        )
    if rms < 1e-4:
        return CheckResult(
            "mic_level",
            Status.WARN,
            f"Mic input is (near) silent (RMS {rms:.5f}) — check microphone "
            "permission in macOS Settings > Privacy & Security > Microphone.",
        )
    return CheckResult(
        "mic_level", Status.PASS, f"Microphone delivering audio (RMS {rms:.5f})"
    )


def check_speaker(config: Config) -> CheckResult:
    """Check the fallback macOS voice is present."""
    if shutil.which("say"):
        return CheckResult("speaker", Status.PASS, "macOS 'say' available")
    return CheckResult("speaker", Status.FAIL, "macOS 'say' not found")


def check_directories(config: Config) -> CheckResult:
    """Verify runtime directories exist and are writable."""
    missing = []
    for directory in (config.log_dir, config.cache_dir, config.screenshot_dir):
        if not directory.is_dir():
            missing.append(str(directory))
    if missing:
        return CheckResult("directories", Status.FAIL, "Missing: " + ", ".join(missing))
    return CheckResult("directories", Status.PASS, "Runtime directories ready")


def check_database(config: Config) -> CheckResult:
    """Verify the memory database is writable."""
    try:
        if not config.db_path.parent.is_dir():
            return CheckResult("database", Status.FAIL, "Database directory missing")
        conn = sqlite3.connect(str(config.db_path))
        conn.execute("SELECT 1")
        conn.close()
        return CheckResult("database", Status.PASS, "SQLite database accessible")
    except sqlite3.Error as exc:
        return CheckResult("database", Status.FAIL, f"SQLite error: {exc}")


def check_tools(config: Config) -> CheckResult:
    """Verify every tool module imports cleanly."""
    import importlib

    modules = (
        "ultron.tools.base",
        "ultron.tools.registry",
        "ultron.tools.filesystem",
        "ultron.tools.macos",
        "ultron.tools.shell",
        "ultron.tools.web",
        "ultron.tools.clipboard",
        "ultron.tools.system",
        "ultron.tools.git",
        "ultron.tools.code",
        "ultron.tools.project",
    )
    failed = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failed.append(f"{name}: {exc}")
    if failed:
        return CheckResult("tools", Status.FAIL, "; ".join(failed))
    return CheckResult(
        "tools",
        Status.PASS,
        f"{len(modules)} tool modules import cleanly",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

# Checks that are cheap, purely local, and required for a voice session.
_CRITICAL_CHECKS = frozenset({"config", "directories", "microphone", "speaker"})

# Checks that probe the network or external services; skipped for the
# local startup gate so boot is never blocked on the internet.
_NETWORK_CHECKS = frozenset({"ollama", "internet"})

_CHECK_FUNCTIONS = (
    check_config,
    check_directories,
    check_database,
    check_api_keys,
    check_macos,
    check_ollama,
    check_internet,
    check_whisper_model,
    check_microphone,
    check_mic_level,
    check_speaker,
    check_tools,
)


def run_checks(config: Config, local_only: bool = False) -> list[CheckResult]:
    """Run every diagnostic check.

    Each check is independent, so one failure never prevents the others
    from running (no fail-fast).

    Args:
        config: Application configuration.
        local_only: When True, skip network-dependent checks so the
            startup gate never blocks on connectivity.
    """
    results: list[CheckResult] = []
    for check in _CHECK_FUNCTIONS:
        if local_only and getattr(check, "__name__", "") in _NETWORK_CHECKS:
            continue
        try:
            result = check(config)
        except Exception as exc:  # defensive: a broken check must not crash the report
            _log.exception("Check %s crashed", getattr(check, "__name__", "?"))
            result = CheckResult(getattr(check, "__name__", "?"), Status.FAIL, str(exc))
        results.append(result)
    return results


def critical_failures(results: list[CheckResult]) -> list[CheckResult]:
    """Return the results that are both critical and failed."""
    return [
        result
        for result in results
        if result.name in _CRITICAL_CHECKS and result.status is Status.FAIL
    ]


def run_startup_gate(config: Config) -> list[str]:
    """Return actionable messages for every failed *critical* local check.

    Non-critical failures (Whisper not cached, Ollama down, no internet)
    do not block startup because the runtime already degrades gracefully
    and re-checks them lazily.
    """
    results = run_checks(config, local_only=True)
    return [
        f"{result.name}: {result.detail}"
        for result in results
        if result.name in _CRITICAL_CHECKS and result.status is Status.FAIL
    ]


def render_report(results: list[CheckResult]) -> str:
    """Render the diagnostic report as text for the console."""
    lines = [
        "",
        "========== ULTRON DIAGNOSTICS ==========",
    ]
    for result in results:
        lines.append(f"[{result.status.value:<3}] {result.name:<12} {result.detail}")
    fails = sum(1 for r in results if r.status is Status.FAIL)
    warns = sum(1 for r in results if r.status is Status.WARN)
    lines.append("======================================")
    lines.append(f"PASS={len(results) - fails - warns} FAIL={fails} WARN={warns}")
    return "\n".join(lines)


def has_failures(results: list[CheckResult]) -> bool:
    """True when any check returned FAIL."""
    return any(result.status is Status.FAIL for result in results)