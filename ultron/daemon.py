"""Headless daemon entry point for Ultron.

Runs Ultron as a persistent, no-TTY background process supervised by
``launchd`` (see ``packaging/com.ultron.agent.plist``). Responsibilities:

- Acquire a single-instance lock (``fcntl.flock`` on ``/tmp/ultron.lock``)
  so a second daemon copy refuses to start.
- Check the kill-switch sentinel (``data/DISABLED``) before starting any
  subsystem; if present, log and exit cleanly.
- Run three concurrent loop threads — Voice, System Probe, Autonomy — that
  share one in-memory ``MemoryStore``/``Config`` instance. Each loop is
  fault-isolated: an exception in one loop logs and keeps running while the
  other loops are unaffected.

Per Day 1 of the architecture roadmap the three loops are *stubs*: they are
empty-but-callable entry points that Days 3–5 fill in with real logic. The
Action Layer (Day 4) is the single path to tool execution for all three.

Run directly with::

    python -m ultron.daemon
"""

from __future__ import annotations

import fcntl
import logging
import os
import sys
import threading
from pathlib import Path

from ultron.config import Config
from ultron.logger import close_logging, configure_logging
from ultron.monitoring import Metrics
from ultron.utils import AudioError
from ultron.voice.listener import delete_wav

_LOCK_PATH = Path("/tmp/ultron.lock")
_DISABLED_PATH = "data/DISABLED"
# Cadence (seconds) between heartbeat ticks of each loop while it has no
# work to do. Real loops override this per their own scheduling needs.
_DEFAULT_TICK = 5.0


class SingleInstanceLock:
    """Ensure only one daemon runs at a time using an advisory file lock.

    The lock file lives in ``/tmp`` and is released automatically when the
    process exits, so a crashed daemon is never left permanently locked.
    """

    def __init__(self, path: Path = _LOCK_PATH) -> None:
        self._path = path
        self._fh = None

    def acquire(self) -> bool:
        """Try to take the lock. Returns True if acquired, False if held."""
        try:
            self._fh = self._path.open("a+")
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fh.seek(0)
            self._fh.truncate()
            self._fh.write(f"{os.getpid()}\n")
            self._fh.flush()
            return True
        except (OSError, BlockingIOError):
            self._fh = None
            return False

    def release(self) -> None:
        """Release the lock and close the file handle."""
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None

    @property
    def held(self) -> bool:
        return self._fh is not None
class _Loop:
    """Fault-isolated background thread running a ``run_once()`` body.

    On any exception the loop logs it, catches it, and continues after the
    interval — a single bad tick must never take down the other loops or the
    whole daemon.
    """

    name = "loop"

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        stop_event: threading.Event,
        interval: float = _DEFAULT_TICK,
    ) -> None:
        self._config = config
        self._log = logger
        self._stop = stop_event
        self._interval = interval
        self._thread: threading.Thread | None = None

    # Subclasses override this with their real logic (Days 2–6).
    def run_once(self) -> None:
        """One tick of work. Empty stub until its relevant day is built."""

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._body, name=self.name, daemon=True
        )
        self._thread.start()

    def _body(self) -> None:
        self._log.info("Loop '%s' started.", self.name)
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001 - isolation by design
                self._log.exception(
                    "Loop '%s' tick failed: %s", self.name, exc
                )
            self._stop.wait(self._interval)
        self._log.info("Loop '%s' stopped.", self.name)


class VoiceLoop(_Loop):
    """Runs the full wake -> command -> reply voice session (Day 7 live path).

    One ``run_once`` is one complete voice interaction. It blocks inside
    ``listen_for_wake`` until the wake phrase is spoken or a stop is
    requested, then acknowledges, records the command, transcribes it, and
    routes it through the assistant — whose every tool call passes through
    the Day 4 PermissionGate. An audio failure is surfaced to the enclosing
    fault-isolated thread loop instead of taking down the daemon.
    """

    name = "voice"

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        stop_event: threading.Event,
        listener=None,
        recognizer=None,
        speaker=None,
        assistant=None,
        interval: float = 0.5,
    ) -> None:
        super().__init__(config, logger, stop_event, interval=interval)
        self._listener = listener
        self._recognizer = recognizer
        self._speaker = speaker
        self._assistant = assistant

    def request_stop(self) -> None:
        """Unblock a listening session so its thread can exit promptly."""
        if self._listener is not None:
            self._listener.request_stop()

    def run_once(self) -> None:
        if self._listener is None:
            self._log.debug("VoiceLoop has no listener; staying silent.")
            return

        try:
            woke = self._listener.listen_for_wake()
        except AudioError as exc:
            self._log.error("Microphone failure: %s", exc)
            if self._listener.recover():
                self._log.info("Microphone recovered; listening again.")
            return  # a dead mic must not take down probes or autonomy
        if not woke:
            return  # stop requested while listening

        import random

        ack = random.choice(self._config.wake_acknowledgements)
        self._speaker.speak(ack)

        command_path = self._listener.record_command()
        if command_path is None:
            self._speaker.speak("I didn't catch that, sir.")
            return
        try:
            text = self._recognizer.transcribe(command_path)
        finally:
            delete_wav(command_path)

        if not text.strip():
            self._speaker.speak("I didn't catch that, sir.")
            return
        self._log.info("Command: %s", text)

        if self._is_shutdown_request(text):
            self._speaker.speak("Very well, sir. Goodbye.")
            self._listener.request_stop()
            self._stop.set()  # graceful exit; launchd KeepAlive respawns
            return

        reply = self._assistant.handle_command(text)
        self._log.info("Reply: %s", reply)
        self._speaker.speak(reply)

    def _is_shutdown_request(self, text: str) -> bool:
        from ultron.utils import normalize

        normalized = normalize(text)
        phrases = {normalize(p) for p in self._config.shutdown_phrases}
        return normalized in phrases


class ProbeLoop(_Loop):
    """Polls the system ProbeBus on a timer and forwards events to the sink.

    Day 3 wires the probes here. Every :class:`ProbeEvent` is emitted into the
    daemon's shared ``on_probe_event`` sink, which Day 5's AutonomyLoop consumes.
    Probes observe only — they never call the Action Layer directly.
    """

    name = "probe"

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        stop_event: threading.Event,
        probe_bus=None,
        interval: float = 15.0,
    ) -> None:
        super().__init__(config, logger, stop_event, interval=interval)
        self._probe_bus = probe_bus

    def run_once(self) -> None:
        if self._probe_bus is not None:
            self._probe_bus.poll_once()
        else:
            self._log.debug("ProbeLoop has no ProbeBus yet; nothing to poll.")


class AutonomyLoop(_Loop):
    """Hosts the real Day 5 :class:`AutonomyLoop` inside a fault-isolated loop.

    The wrapped ``inner`` loop consumes probe events from the shared sink,
    scores pending goals/tasks, and dispatches through the orchestrator — all
    tool execution routed through the Day 4 PermissionGate.
    """

    name = "autonomy"

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        stop_event: threading.Event,
        inner=None,
        interval: float = 5.0,
    ) -> None:
        super().__init__(config, logger, stop_event, interval=interval)
        self._inner = inner

    def run_once(self) -> None:
        if self._inner is not None:
            self._inner.tick()
        else:
            self._log.debug("AutonomyLoop has no inner loop yet; nothing to tick.")


class UltronDaemon:
    """Composition root and lifecycle for the headless daemon."""

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self._config = config
        self._log = logger
        self._lock = SingleInstanceLock()
        self._stop_event = threading.Event()
        self._loops: list[_Loop] = []
        self._memory = None  # shared MemoryStore instance (Days 4–5)
        self._autonomy = None  # real Day 5 AutonomyLoop (probe event sink)

    def start(self) -> int:
        """Start the daemon. Returns exit code 0 clean, 1 on lock collision."""
        if not self._lock.acquire():
            message = (
                "Ultron is already running (lock held by "
                f"{self._lock._path}). Refusing to start a second copy."
            )
            self._log.error("%s", message)
            print(message, file=sys.stderr)
            return 1

        disabled = self._project_dir() / _DISABLED_PATH
        if disabled.exists():
            self._log.warning(
                "Kill switch sentinel %s present — exiting without starting "
                "any subsystem (mic, tools, network untouched).",
                disabled,
            )
            self._lock.release()
            # Signal main() not to block: no subsystems started, exit cleanly.
            self._stop_event.set()
            return 0

        self._log.info("Ultron daemon acquiring resources (headless, no TTY).")
        self._metrics = Metrics()
        self._memory = self._build_memory()
        shared = self._build_shared_plumbing()
        voice = self._build_voice(shared)
        autonomy = self._build_autonomy(shared)
        probe_sink = self._on_probe_event()
        probe_bus = self._build_probe_bus(probe_sink)
        self._loops = [
            VoiceLoop(
                self._config,
                self._log,
                self._stop_event,
                listener=voice[0] if voice else None,
                recognizer=voice[1] if voice else None,
                speaker=voice[2] if voice else None,
                assistant=voice[3] if voice else None,
            ),
            ProbeLoop(
                self._config,
                self._log,
                self._stop_event,
                probe_bus=probe_bus,
                interval=15.0,
            ),
            AutonomyLoop(
                self._config,
                self._log,
                self._stop_event,
                inner=autonomy,
            ),
        ]
        for loop in self._loops:
            loop.start()
        self._log.info(
            "Ultron daemon running with %d loop threads.", len(self._loops)
        )
        return 0

    def _project_dir(self) -> Path:
        return Path(self._config.project_dir)

    def _on_probe_event(self):
        """Return the sink every ProbeBus event is delivered to.

        Every event is logged and forwarded into the AutonomyLoop's inbox so
        the Day 5 decision loop can score and act on it. Probes observe only —
        they never call the Action Layer directly.
        """
        def sink(event):
            self._log.info(
                "PROBE event kind=%s payload=%s ts=%.2f",
                event.kind,
                event.payload,
                event.timestamp,
            )
            if self._autonomy is not None:
                self._autonomy.on_probe_event(event)

        return sink

    def _build_shared_plumbing(self):
        """Build once: audit, kill switch, permission gate, router, registry.

        Returns a tuple ``(audit, kill, gate, router, registry)`` shared by
        the voice path and the autonomy path so there is exactly one
        route to tool execution. Returns None on failure so the daemon
        still starts (with reduced capability).
        """
        try:
            from ultron.action.audit import AuditLog
            from ultron.action.gate import KillSwitch, PermissionGate
            from ultron.action.permissions import PermissionTier
            from ultron.core.llm import ProviderRouter
            from ultron.tools.filesystem import enable_scope_enforcement

            # Day 7: enforce filesystem scope so no tool path can escape the
            # user's home directory (or an explicit allowlist). This is the
            # hard first-line check before the PermissionGate's tier/approve.
            enable_scope_enforcement(extra_roots=(self._config.project_dir,))
            from ultron.tools.registry import ToolRegistry

            audit = AuditLog.at_path(self._config.db_path)
            self._audit = audit
            kill = KillSwitch(self._config.project_dir / _DISABLED_PATH)
            self._kill_switch = kill
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
                # Headless: never auto-confirm destructive actions.
                self._log.warning("Destructive action blocked (headless): %s", text)
                return False

            gate = PermissionGate(audit, kill, confirm, allowed_tiers=tiers)
            self._permission_gate = gate

            router = ProviderRouter(self._config, logging.getLogger("ultron.router"))
            registry = ToolRegistry.build_default(
                self._config,
                self._memory,
                logging.getLogger("ultron.tools"),
                metrics=self._metrics,
            )
            registry.set_permission_gate(gate)
            self._router = router
            self._registry = registry
            self._log.info(
                "Shared plumbing active (allowed tiers: %s).",
                sorted(t.value for t in tiers),
            )
            return audit, kill, gate, router, registry
        except Exception as exc:  # defensive: plumbing must not gate the daemon
            self._log.warning(
                "Shared plumbing unavailable; daemon runs reduced: %s", exc
            )
            return None

    def _build_voice(self, shared):
        """Build the voice pipeline (mic -> Whisper -> assistant -> speaker).

        Returns ``(listener, recognizer, speaker, assistant)`` or None when
        the microphone/Whisper layer is unavailable (no permission, no model):
        the daemon keeps running headless-silent with probes + autonomy.
        """
        if shared is None:
            return None
        _, _, gate, router, registry = shared
        try:
            from ultron.core.assistant import Assistant
            from ultron.voice.listener import Listener
            from ultron.voice.recognizer import SpeechRecognizer
            from ultron.voice.speaker import Speaker

            recognizer = SpeechRecognizer(
                self._config,
                logging.getLogger("ultron.speech"),
                metrics=self._metrics,
            )
            recognizer.load()
            listener = Listener(
                self._config,
                recognizer,
                logging.getLogger("ultron.listener"),
                metrics=self._metrics,
            )
            listener.start()
            speaker = Speaker(
                self._config,
                logging.getLogger("ultron.speaker"),
                metrics=self._metrics,
            )
            assistant = Assistant(
                self._config,
                self._memory,
                router,
                registry,
                logging.getLogger("ultron.assistant"),
                metrics=self._metrics,
            )
            self._listener = listener
            self._speaker = speaker
            self._assistant = assistant
            self._log.info(
                "Voice pipeline active — say '%s'.", self._config.wake_phrase
            )
            return listener, recognizer, speaker, assistant
        except Exception as exc:  # defensive: voice must not gate the daemon
            self._log.warning(
                "Voice unavailable; daemon runs headless-silent: %s", exc
            )
            return None

    def _build_autonomy(self, shared):
        """Build the Day 5 decision machinery: gate, orchestrator, inner loop.

        The real :class:`AutonomyLoop` receives the shared MemoryStore, the
        shared PermissionGate, and a logging speaker for observations.
        Returns None on failure so the daemon still starts.
        """
        self._autonomy = None
        if shared is None:
            return None
        try:
            from ultron.agents.base import AgentContext
            from ultron.agents.orchestrator import Orchestrator
            from ultron.autonomy.loop import AutonomyLoop as RealAutonomyLoop

            _, kill, gate, router, registry = shared

            orchestrator = Orchestrator(logger=logging.getLogger("ultron.orchestrator"))
            ctx_factory = lambda: AgentContext(  # noqa: E731
                config=self._config,
                memory=self._memory,
                llm=router,
                tools=registry,
            )

            log = self._log

            class _LogSpeaker:
                """Headless observation sink: observations land in the log."""

                def speak(self, text: str) -> None:
                    log.info("AUTONOMY OBSERVATION: %s", text)

            inner = RealAutonomyLoop(
                memory=self._memory,
                orchestrator=orchestrator,
                kill_switch=kill,
                permission_gate=gate,
                ctx_factory=ctx_factory,
                speaker=_LogSpeaker(),
            )
            self._log.info(
                "Autonomy machinery active (tiers: %s).",
                sorted(t.value for t in gate.allowed_tiers()),
            )
            return inner
        except Exception as exc:  # defensive: autonomy must not gate the daemon
            self._log.warning(
                "Autonomy machinery unavailable; probes log only: %s", exc
            )
            return None

    def _build_probe_bus(self, on_event):
        """Construct the ProbeBus (Day 3). Returns None if probes unavailable."""
        try:
            from ultron.probes import (
                AppProbe,
                IdleProbe,
                NetworkProbe,
                ProbeBus,
                SystemProbe,
            )

            return ProbeBus(
                SystemProbe(),
                AppProbe(),
                IdleProbe(),
                NetworkProbe(),
                on_event=on_event,
            )
        except Exception as exc:  # defensive: probes must not gate the daemon
            self._log.warning("Probes unavailable; running without sensing: %s", exc)
            return None

    def _build_memory(self):
        """Build the shared in-memory MemoryStore. Days 4/5 wire tools to it."""
        try:
            from ultron.memory.store import MemoryStore

            return MemoryStore(
                db_path=self._config.db_path,
                logger=logging.getLogger("ultron.memory"),
            )
        except Exception as exc:  # defensive: memory must not gate the daemon
            self._log.warning("Memory store unavailable for daemon: %s", exc)
            return None

    def request_stop(self) -> None:
        """Signal every loop thread to stop and join them."""
        self._stop_event.set()
        for loop in self._loops:
            request_stop = getattr(loop, "request_stop", None)
            if request_stop is not None:
                try:
                    request_stop()
                except Exception:  # noqa: BLE001 - a stuck loop must not block
                    pass
            thread = loop._thread
            if thread is not None and thread.is_alive():
                thread.join(timeout=2.0)
        self._stop_event.clear()

    def shutdown(self) -> None:
        """Release the lock and clean up shared resources."""
        listener = getattr(self, "_listener", None)
        if listener is not None:
            try:
                listener.close()
            except Exception as exc:  # noqa: BLE001
                self._log.debug("Listener close ignored: %s", exc)
        if self._memory is not None:
            try:
                self._memory.close()
            except Exception as exc:  # noqa: BLE001
                self._log.debug("Memory close ignored: %s", exc)
        audit = getattr(self, "_audit", None)
        if audit is not None:
            try:
                audit.close()
            except Exception as exc:  # noqa: BLE001
                self._log.debug("Audit close ignored: %s", exc)
        self._lock.release()
        self._log.info("Ultron daemon stopped cleanly.")


def main(argv: list[str] | None = None) -> int:
    """Run the daemon in the foreground of the calling (headless) process."""
    try:
        config = Config.from_env()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    logger = configure_logging(
        config.log_dir, level=os.environ.get("ULTRON_LOG_LEVEL", "INFO")
    )
    daemon = UltronDaemon(config, logger)

    exit_code = daemon.start()
    try:
        if exit_code == 0:
            # Block the main thread while loop threads run. Ctrl-C/SIGTERM
            # stops gracefully below.
            daemon._stop_event.wait()  # type: ignore[attr-defined]
    except KeyboardInterrupt:
        logger.info("Interrupt received; shutting down daemon.")
    finally:
        daemon.request_stop()
        daemon.shutdown()
        close_logging()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
