"""Microphone capture for Ultron.

The :class:`Listener` runs a continuous microphone stream, detects the
wake phrase in short transcribed windows, and records commands with
silence detection. All PortAudio errors are wrapped in :class:`AudioError`.
"""

from __future__ import annotations

import difflib
import logging
import math
import os
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from ultron.config import Config
from ultron.monitoring import Metrics, get_metrics
from ultron.utils import AudioError, normalize
from ultron.voice.recognizer import SpeechRecognizer

_WAKE_FILE = "wake.wav"
_COMMAND_FILE = "command.wav"
_WAKE_BACKOFF_BASE = 0.5
_WAKE_BACKOFF_MAX = 5.0
# How many consecutive below-gate (silent) wake windows pass before we log
# that the listener is alive but hearing nothing. With 1.5s windows this is
# roughly every ~12s, so a stuck-silent state is never hidden.
_SILENT_LOG_EVERY = 8

_log = logging.getLogger("ultron.listener")


def _rms(block: np.ndarray) -> float:
    """Return the root-mean-square amplitude of an audio block."""
    if block.size == 0:
        return 0.0
    return float(math.sqrt(np.mean(np.square(block))))


def _wake_filename() -> str:
    """Return the pid-suffixed wake recording filename."""
    return f"wake-{os.getpid()}.wav"


def _command_filename() -> str:
    """Return the pid-suffixed command recording filename."""
    return f"command-{os.getpid()}.wav"


class Listener:
    """Continuously listens, detects the wake phrase, and records commands.

    Args:
        config: Application configuration.
        recognizer: Speech recognizer used for wake detection.
        logger: Logger instance for the listener.
    """

    def __init__(
        self,
        config: Config,
        recognizer: SpeechRecognizer,
        logger: logging.Logger,
        metrics: Metrics | None = None,
    ) -> None:
        self._config = config
        self._recognizer = recognizer
        self._log = logger
        self._metrics = metrics or get_metrics()
        self._stream: sd.InputStream | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _resolve_input_device(self) -> int | None:
        """Validate the configured microphone and fall back to the default.

        Returns the validated device index, or None for the system
        default input device.
        """
        try:
            devices = sd.query_devices()
        except Exception as exc:
            self._log.warning(
                "Could not enumerate audio devices (%s); using default.", exc
            )
            return None
        configured = self._config.mic_device
        if configured is not None:
            valid = (
                0 <= configured < len(devices)
                and devices[configured].get("max_input_channels", 0) > 0
            )
            if valid:
                self._log.info("Using configured microphone device #%d", configured)
                return configured
            self._log.warning(
                "Configured microphone #%d is invalid or has no input channels; "
                "falling back to the default input device.",
                configured,
            )
        return None

    def start(self) -> None:
        """Open the microphone stream.

        The configured device index is validated first; an invalid device
        silently falls back to the system default. PortAudio/Permission
        failures surface as an actionable :class:`AudioError`.

        Raises:
            AudioError: If the microphone cannot be opened.
        """
        if self._stream is not None:
            return
        device = self._resolve_input_device()
        try:
            self._stream = sd.InputStream(
                samplerate=self._config.sample_rate,
                channels=self._config.channels,
                dtype="float32",
                blocksize=self._config.block_size,
                device=device,
            )
            self._stream.start()
            actual_rate = self._config.sample_rate
            try:
                device_info = sd.query_devices(device)
                device_name = str(device_info.get("name", device))
                actual_rate = int(device_info.get("default_samplerate", 0))
            except Exception as exc:
                device_name = device if device is not None else "default"
                self._log.debug("Could not read device details: %s", exc)
            self._log.info(
                "Microphone opened: %r (device rate %d Hz; configured %d Hz).",
                device_name,
                actual_rate,
                self._config.sample_rate,
            )
        except sd.PortAudioError as exc:
            raise AudioError(
                f"Could not open microphone: {exc}. Check macOS Settings > "
                "Privacy & Security > Microphone and that PortAudio is installed."
            ) from exc
        except Exception as exc:
            raise AudioError(f"Could not open microphone: {exc}") from exc

    def recover(self) -> bool:
        """Attempt to reopen the microphone stream after a failure (or sleep).

        Used to ride out transient device drops (unplugged mic, macOS
        sleep/wake gaps). Returns True when the stream is healthy again.

        Returns:
            True if the stream was reopened successfully.
        """
        self.close()
        try:
            self.start()
        except AudioError as exc:
            self._log.error("Microphone recovery failed: %s", exc)
            return False
        self._log.info("Microphone recovered.")
        return True

    def close(self) -> None:
        """Stop the microphone stream and release the device."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                self._log.warning("Error closing microphone: %s", exc)
            finally:
                self._stream = None
        self._log.info("Microphone closed.")

    def __enter__(self) -> Listener:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def request_stop(self) -> None:
        """Signal the listening loops to stop at the next opportunity."""
        self._stop_event.set()

    def stop_requested(self) -> bool:
        """Return True when a stop has been requested."""
        return self._stop_event.is_set()

    # ------------------------------------------------------------------
    # Audio primitives
    # ------------------------------------------------------------------

    def _read_block(self, frames: int) -> np.ndarray | None:
        """Read one audio block; None when a stop was requested.

        Raises:
            AudioError: On microphone failure.
        """
        assert self._stream is not None
        try:
            data, _overflow = self._stream.read(frames)
        except sd.PortAudioError as exc:
            raise AudioError(f"Failed to read from microphone: {exc}") from exc
        except Exception as exc:
            if self._stop_event.is_set():
                return None
            raise AudioError(f"Unexpected microphone error: {exc}") from exc
        return data[:, 0]

    def _read_blocks(self, seconds: float) -> np.ndarray | None:
        """Read audio for a duration, accumulating raw blocks.

        Args:
            seconds: Duration to capture.

        Returns:
            Concatenated mono float32 samples, or None if stopped early.
        """
        frames = int(seconds * self._config.sample_rate)
        blocks: list[np.ndarray] = []
        remaining = frames
        while remaining > 0 and not self._stop_event.is_set():
            block = self._read_block(min(self._config.block_size, remaining))
            if block is None:
                return None
            blocks.append(block)
            remaining -= len(block)
        if self._stop_event.is_set():
            return None
        if not blocks:
            return None
        return np.concatenate(blocks)

    def _save_wav(self, audio: np.ndarray, filename: str) -> Path:
        """Persist audio samples as a PCM WAV file in the cache directory."""
        path = self._config.cache_dir / filename
        sf.write(
            str(path),
            audio,
            self._config.sample_rate,
            subtype="PCM_16",
        )
        return path

    # ------------------------------------------------------------------
    # Wake phrase
    # ------------------------------------------------------------------

    def _iter_wake_windows(self):
        """Yield overlapping audio windows for wake detection.

        Reads the mic in small ``step``-sized blocks and slides a window of
        ``wake_window_seconds`` forward by ``step`` each time, so the wake
        phrase is never clipped at a fixed window boundary. This directly
        addresses the Day 1 architecture note about the ``1.5s`` non-overlapping
        window clipping the phrase at its edges.
        """
        window_samples = int(
            self._config.wake_window_seconds * self._config.sample_rate
        )
        overlap = self._config.wake_window_overlap
        if not (0.0 <= overlap < 1.0):
            overlap = 0.5
        step_seconds = self._config.wake_window_seconds * (1.0 - overlap)
        step_samples = max(1, int(step_seconds * self._config.sample_rate))
        buffer = np.zeros(0, dtype=np.float64)
        while not self._stop_event.is_set():
            chunk = self._read_block(step_samples)
            if chunk is None:
                return
            buffer = np.concatenate([buffer, chunk])
            if buffer.size >= window_samples:
                yield buffer[:window_samples].copy()
                buffer = buffer[step_samples:]

    def listen_for_wake(self) -> bool:
        """Continuously listen until the wake phrase is spoken.

        Uses confidence-based fuzzy matching (see
        :func:`match_wake_phrase`); a transcript is only accepted when it
        clears the configured similarity threshold and contains the
        ``ultron`` keyword. Every transcript is logged with its score and
        the accept/reject reason.

        Listeners forever unless :meth:`request_stop` is called or the
        stream fails. Returns True when the wake phrase was detected.

        Raises:
            AudioError: On microphone failure.
        """
        wake_log = logging.getLogger("ultron.wake")
        wake_log.info(
            "Listening for wake phrase '%s' (threshold %.2f).",
            self._config.wake_phrase,
            self._config.wake_match_threshold,
        )
        consecutive_failures = 0
        silent_windows = 0

        # Measure the ambient noise floor so a dead/near-silent microphone
        # (usually missing macOS permission) is reported immediately instead
        # of silently never waking. We do NOT raise the transcription gate
        # above the configured silence_threshold: that is calibration-tuned
        # and raising it would reject quiet-but-real speech.
        wake_gate = self._config.silence_threshold
        floor = self._measure_floor(seconds=0.3)
        if floor <= 0.0 or floor < self._config.silence_threshold * 0.5:
            wake_log.warning(
                "Microphone input is (near) silent (noise floor RMS %.5f). "
                "If Ultron never wakes, grant the terminal microphone access "
                "in macOS Settings > Privacy & Security > Microphone, or "
                "raise the mic input volume.",
                floor,
            )
        wake_log.info(
            "Wake noise floor RMS %.5f; transcription gate RMS %.5f.",
            floor,
            wake_gate,
        )

        for audio in self._iter_wake_windows():
            if self._stop_event.is_set():
                return False
            rms = _rms(audio)
            if rms < wake_gate:
                # Silent window: nothing worth transcribing. Log periodically
                # so a dead-mic / no-permission state is observable instead
                # of looking like a hung process.
                silent_windows += 1
                if silent_windows == _SILENT_LOG_EVERY:
                    wake_log.warning(
                        "Heard only silence after ~%.0fs (RMS %.5f < gate %.5f). "
                        "Check mic permission and input volume.",
                        silent_windows * self._config.wake_window_seconds,
                        rms,
                        wake_gate,
                    )
                elif silent_windows > _SILENT_LOG_EVERY and (
                    silent_windows % _SILENT_LOG_EVERY == 0
                ):
                    wake_log.info(
                        "Still silent (RMS %.5f < gate %.5f; %.0fs elapsed).",
                        rms,
                        wake_gate,
                        silent_windows * self._config.wake_window_seconds,
                    )
                continue
            silent_windows = 0
            path = self._save_wav(audio, _wake_filename())
            try:
                text = self._recognizer.transcribe_wake_window(path)
            except Exception as exc:
                wake_log.warning("Wake transcription failed: %s", exc)
                backoff = min(
                    _WAKE_BACKOFF_BASE * (2**consecutive_failures),
                    _WAKE_BACKOFF_MAX,
                )
                consecutive_failures += 1
                wake_log.debug("Backing off %.2fs before next wake attempt.", backoff)
                time.sleep(backoff)
                continue
            finally:
                delete_wav(path)
            if not text:
                continue
            consecutive_failures = 0
            self._metrics.increment("wake.windows_transcribed")

            matched, score, reason = match_wake_phrase(text, self._config)
            if matched:
                wake_log.info(
                    "Wake DETECTED transcript=%r score=%.2f reason=%s",
                    text,
                    score,
                    reason,
                )
                self._metrics.increment("wake.detections")
                self._metrics.observe("wake.similarity_score", score)
                return True
            wake_log.info(
                "Wake REJECTED transcript=%r score=%.2f reason=%s",
                text,
                score,
                reason,
            )
            self._metrics.observe("wake.rejected_score", score)
        return False

    # ------------------------------------------------------------------
    # Command recording with silence detection
    # ------------------------------------------------------------------

    def record_command(self) -> Path | None:
        """Record a spoken command until silence or the timeout is reached.

        Samples the ambient noise floor first, then waits for speech to
        start (up to ``speech_start_timeout``). Recording ends after
        ``silence_duration`` of trailing silence or ``command_timeout``.

        Returns:
            Path to the recorded WAV file, or None if no speech was heard.

        Raises:
            AudioError: On microphone failure.
        """
        floor = self._measure_floor(seconds=0.3)
        threshold = max(self._config.silence_threshold, floor * 2.0)

        blocks: list[np.ndarray] = []
        started_at = time.monotonic()
        speech_started = False
        silent_blocks = 0
        silence_limit = int(
            self._config.silence_duration
            * self._config.sample_rate
            / self._config.block_size
        )

        while not self._stop_event.is_set():
            elapsed = time.monotonic() - started_at
            if elapsed > self._config.command_timeout:
                self._log.info("Command timeout reached.")
                break
            if not speech_started and elapsed > self._config.speech_start_timeout:
                self._log.info("No speech detected; timing out.")
                return None
            block = self._read_block(self._config.block_size)
            if block is None:
                return None
            blocks.append(block)
            if _rms(block) >= threshold:
                speech_started = True
                silent_blocks = 0
            elif speech_started:
                silent_blocks += 1
                if silent_blocks >= silence_limit:
                    self._log.info("Silence detected; command complete.")
                    break

        if self._stop_event.is_set():
            return None
        if not speech_started:
            self._log.info("Nothing heard.")
            return None

        audio = np.concatenate(blocks)
        duration = len(audio) / self._config.sample_rate
        self._metrics.increment("wake.commands_recorded")
        self._metrics.observe("wake.record_duration", duration)
        self._log.info(
            "Recorded command (%.2fs, peak RMS %.4f).", duration, _rms(audio)
        )
        return self._save_wav(audio, _command_filename())

    def _measure_floor(self, seconds: float) -> float:
        """Measure the ambient noise floor (RMS) for threshold calibration."""
        audio = self._read_blocks(seconds)
        if audio is None:
            return 0.0
        return _rms(audio)


def delete_wav(path: Path) -> None:
    """Best-effort removal of a temporary audio file."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        _log.debug("Could not delete temporary audio file %s: %s", path, exc)


def _wake_variants(config: Config) -> tuple[str, ...]:
    """Return normalized wake phrases, always including the configured one."""
    variants = list(config.wake_variants or ())
    if config.wake_phrase not in variants:
        variants.insert(0, config.wake_phrase)
    return tuple(normalize(variant) for variant in variants if normalize(variant))


def match_wake_phrase(
    transcript: str, config: Config
) -> tuple[bool, float, str]:
    """Decide whether a wake-window transcript contains the wake phrase.

    Two acceptance paths, both deterministic:

    1. A configured wake variant is present verbatim in the transcript
       (e.g. "hey ultron please" contains "hey ultron"). This keeps the
       classic substring behavior for longer utterances.
    2. Otherwise the transcript is compared against every variant with
       the SequenceMatcher ratio; a score at or above
       :attr:`Config.wake_match_threshold` is accepted. This absorbs
       Whisper homophones such as "hey ultra" and "hey altron".

    A low-confidence transcript is never treated as a wake.

    Args:
        transcript: Raw whisper text from a wake window.
        config: Application configuration.

    Returns:
        ``(matched, score, reason)``. ``reason`` always explains the
        outcome so every reject is observable.
    """
    norm = normalize(transcript)
    if not norm:
        return False, 0.0, "empty transcript"

    variants = _wake_variants(config)
    best_score = 0.0
    best_variant = ""
    for variant in variants:
        if variant in norm:
            return True, 1.0, f"matched exact phrase '{variant}'"
        score = difflib.SequenceMatcher(None, norm, variant).ratio()
        if score > best_score:
            best_score = score
            best_variant = variant

    threshold = config.wake_match_threshold
    if best_score >= threshold:
        return True, best_score, (
            f"matched '{best_variant}' at score {best_score:.2f}"
        )
    return False, best_score, (
        f"closest '{best_variant}' scored {best_score:.2f}; "
        f"below threshold {threshold}"
    )
