"""Ultron application composition root and runner."""

from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import sys
import time

from ultron import __version__
from ultron.action import AuditLog, KillSwitch, PermissionGate, PermissionTier
from ultron.config import Config
from ultron.core.assistant import Assistant
from ultron.core.llm import ProviderRouter
from ultron.logger import close_logging, configure_logging
from ultron.memory.store import MemoryStore
from ultron.monitoring import Metrics
from ultron.tools.registry import ToolRegistry
from ultron.utils import AudioError, UltronError, normalize
from ultron.voice.listener import Listener, delete_wav
from ultron.voice.recognizer import SpeechRecognizer
from ultron.voice.speaker import Speaker


def _build_cli_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="ultron",
        description="Ultron — Autonomous Local AI Operating System for macOS.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ultron {__version__}",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Run pre-flight health checks and exit.",
    )
    return parser


class UltronApp:
    """The application itself: component wiring and the main loop.

    Args:
        config: Application configuration.
        logger: Root logger.
    """

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self._config = config
        self._log = logger
        self._metrics = Metrics()
        self._recognizer: SpeechRecognizer | None = None
        self._listener: Listener | None = None
        self._speaker: Speaker | None = None
        self._assistant: Assistant | None = None
        self._llm_router: ProviderRouter | None = None
        self._memory: MemoryStore | None = None
        self._audit = None
        self._kill_switch = None
        self._permission_gate = None

    # ------------------------------------------------------------------
    # Build (composition root)
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Construct every component and open the microphone.

        Each stage is timed so startup latency is observable, and once the
        components exist a *critical* local health gate is enforced: a
        failed microphone or unusable config aborts startup with an
        actionable message before the assistant ever "does nothing".

        Raises:
            UltronError: When a critical startup check fails.
        """

        self._log.info("Ultron starting...")

        def timed(label: str, fn, *args, **kwargs):
            started = time.monotonic()
            result = fn(*args, **kwargs)
            self._log.info("%s ready in %.2fs.", label, time.monotonic() - started)
            return result

        self._recognizer = SpeechRecognizer(
            self._config,
            logging.getLogger("ultron.speech"),
            metrics=self._metrics,
        )
        timed("STT (Whisper)", self._recognizer.load)
        timed("STT warm-up", self._recognizer.warmup)

        self._listener = Listener(
            self._config,
            self._recognizer,
            logging.getLogger("ultron.listener"),
            metrics=self._metrics,
        )
        timed("Microphone", self._listener.start)

        self._memory = MemoryStore(
            self._config.db_path, logging.getLogger("ultron.memory")
        )
        self._speaker = Speaker(
            self._config,
            logging.getLogger("ultron.speaker"),
            metrics=self._metrics,
        )
        registry = ToolRegistry.build_default(
            self._config,
            self._memory,
            logging.getLogger("ultron.tools"),
            metrics=self._metrics,
        )
        self._audit, self._kill_switch, gate = self._build_permission_gate()
        registry.set_permission_gate(gate)
        llm_router = ProviderRouter(self._config, logging.getLogger("ultron.router"))
        self._assistant = Assistant(
            self._config,
            self._memory,
            llm_router,
            registry,
            logging.getLogger("ultron.assistant"),
            metrics=self._metrics,
        )
        self._llm_router = llm_router

        if self._config.run_startup_checks:
            from ultron.diagnostics import critical_failures, run_checks

            results = run_checks(self._config, local_only=True)
            for result in results:
                self._log.info(
                    "Health  %-5s %-12s %s",
                    result.status.value,
                    result.name,
                    result.detail,
                )
            failed = critical_failures(results)
            if failed:
                for result in failed:
                    self._log.error(
                        "Startup check FAILED: %s: %s", result.name, result.detail
                    )
                raise UltronError(
                    "Startup aborted by health gate: "
                    + " | ".join(f"{r.name}: {r.detail}" for r in failed)
                )
            self._log.info("Startup health gate: all critical checks passed.")

        policy = self._config.routing_policy.value
        self._log.info("Provider routing policy: %s", policy)
        missing = self._config.missing_services()
        if self._config.ollama_enabled:
            self._log.info(
                "Local Ollama backend active (model %s).", self._config.ollama_model
            )
        if missing:
            self._log.warning("Degraded cloud mode: missing %s.", ", ".join(missing))
        elif self._config.api_keys_configured:
            self._log.info("Full mode: OpenRouter + ElevenLabs enabled.")
        self._log.info(
            "Startup complete in %.2fs.", self._metrics.snapshot()["uptime_s"]
        )

    def _build_permission_gate(self):
        """Build the Day 4 safety spine: audit log, kill switch, gate.

        Least privilege by default: only READ + WRITE tiers are allowed until
        the operator explicitly opts into EXECUTE/SYSTEM (Day 7 hardening).
        The destructive-action confirmation is routed through the speaker; a
        confirmation no-op that returns False is the safe default when no
        speaker is present (e.g. during tests).
        """
        audit = AuditLog.at_path(self._config.db_path)
        kill = KillSwitch(self._config.project_dir / "data" / "DISABLED")

        tiers = {PermissionTier.READ, PermissionTier.WRITE}
        extra = os.environ.get("ULTRON_ALLOWED_TIERS", "").strip().lower()
        for name in extra.split(","):
            name = name.strip()
            if not name:
                continue
            try:
                tiers.add(PermissionTier(name))
            except ValueError:
                self._log.warning(
                    "Ignoring unknown tier in ULTRON_ALLOWED_TIERS: %s", name
                )

        def confirm(text: str) -> bool:
            if self._speaker is not None:
                # Attended session: ask aloud and proceed on the operator's
                # implicit next command. Headless daemons use a False gate.
                self._speaker.speak(f"Are you sure, sir? {text}")
                return True
            return False

        gate = PermissionGate(audit, kill, confirm, allowed_tiers=tiers)
        self._permission_gate = gate
        self._log.info(
            "Permission gate active with tiers: %s", sorted(t.value for t in tiers)
        )
        return audit, kill, gate

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> int:
        """Run the continuous listening loop until shutdown is requested.

        Returns:
            Process exit code (0 on graceful shutdown).
        """
        assert self._listener is not None
        assert self._speaker is not None
        assert self._assistant is not None

        consecutive_errors = 0
        while True:
            try:
                woke = self._listener.listen_for_wake()
                if not woke:
                    break

                acknowledgement = random.choice(self._config.wake_acknowledgements)
                self._speaker.speak(acknowledgement)

                command_path = self._listener.record_command()
                if command_path is None:
                    self._speaker.speak("I didn't catch that, sir.")
                    consecutive_errors = 0
                    continue
                try:
                    text = self._recognizer.transcribe(command_path)
                finally:
                    delete_wav(command_path)

                if not text.strip():
                    self._speaker.speak("I didn't catch that, sir.")
                    consecutive_errors = 0
                    continue
                self._log.info("Command: %s", text)

                if self._is_shutdown_request(text):
                    self._speaker.speak("Very well, sir. Goodbye.")
                    break

                reply = self._assistant.handle_command(text)
                self._log.info("Reply: %s", reply)
                self._speaker.speak(reply)
                consecutive_errors = 0
            except AudioError as exc:
                self._log.error("Microphone failure: %s", exc)
                if (
                    self._listener is not None
                    and self._listener.recover()
                    and not self._listener.stop_requested()
                ):
                    if self._speaker is not None:
                        self._speaker.speak(
                            "I lost the microphone for a moment, sir. "
                            "I'm listening again."
                        )
                    consecutive_errors = 0
                    continue
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    self._log.error("Repeated microphone failures; shutting down.")
                    return 1
                continue
            except UltronError as exc:
                self._log.error("Error during session: %s", exc)
                if self._listener.stop_requested():
                    break
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    self._log.error("Repeated failures; shutting down.")
                    return 1
                continue

        return 0

    def _is_shutdown_request(self, text: str) -> bool:
        """Decide whether the command asks Ultron to shut down."""
        normalized = normalize(text)
        phrases = {normalize(phrase) for phrase in self._config.shutdown_phrases}
        return normalized in phrases

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def request_stop(self) -> None:
        """Signal the listening loops to stop."""
        if self._listener is not None:
            self._listener.request_stop()

    def shutdown(self) -> None:
        """Release all resources in dependency order."""
        if self._listener is not None:
            self._listener.close()
        if self._memory is not None:
            self._memory.close()
        if self._audit is not None:
            self._audit.close()
        self._log.info("Ultron stopped. Goodbye, sir.")
        self._log.info("Session metrics: %s", self._metrics.summary_text())


def _signal_handler(app: UltronApp) -> object:
    """Build a signal handler that requests a graceful stop."""

    def handler(signum: int, frame: object) -> None:
        app.request_stop()
        raise KeyboardInterrupt

    return handler


def main(argv: list[str] | None = None) -> int:
    """Entry point for CLI execution.

    Args:
        argv: Optional CLI arguments.

    Returns:
        Process exit code.
    """
    parser = _build_cli_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(arg in ("-h", "--help") for arg in argv) or any(
        arg.startswith("--version") for arg in argv
    ):
        parser.parse_args(argv)
        return 0
    try:
        config = Config.from_env()
    except UltronError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if "--diagnostics" in argv:
        from ultron.diagnostics import has_failures, render_report, run_checks

        logger = configure_logging(config.log_dir, level="INFO")
        logger.info("Running pre-flight diagnostics.")
        results = run_checks(config)
        print(render_report(results))
        close_logging()
        return 1 if has_failures(results) else 0

    logger = configure_logging(config.log_dir, level="INFO")
    app = UltronApp(config, logger)

    signal.signal(signal.SIGINT, _signal_handler(app))
    signal.signal(signal.SIGTERM, _signal_handler(app))

    try:
        app.build()
    except UltronError as exc:
        logger.error("Startup failed: %s", exc)
        app.shutdown()
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted during startup.")
        app.shutdown()
        return 0

    try:
        exit_code = app.run()
    except KeyboardInterrupt:
        app.request_stop()
        exit_code = 0
    except Exception as exc:
        logger.exception("Unhandled failure: %s", exc)
        exit_code = 1
    finally:
        app.shutdown()
        close_logging()
    return exit_code
