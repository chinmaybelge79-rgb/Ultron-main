"""Speech-to-text for Ultron using Faster-Whisper.

The model is loaded eagerly at startup (so health can be verified before
entering the listening loop), warm-up-inferred once, and transcription
calls are wrapped with retry logic for transient failures.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from ultron.config import Config
from ultron.monitoring import Metrics, get_metrics
from ultron.utils import TranscriptionError, retry

_WAKE_BEAM_SIZE = 1
_COMMAND_BEAM_SIZE = 5
_WARMUP_SECONDS = 0.5


class SpeechRecognizer:
    """Transcribes audio with a local Faster-Whisper model.

    Args:
        config: Application configuration.
        logger: Logger instance for the recognizer.
    """

    def __init__(
        self, config: Config, logger: logging.Logger, metrics: Metrics | None = None
    ) -> None:
        self._config = config
        self._log = logger
        self._metrics = metrics or get_metrics()
        self._model = None

    def load(self) -> None:
        """Load (and download on first run) the Whisper model.

        Verifies the model cache ahead of loading, measures the load
        wall-clock time, and reports whether the model was cached or had
        to be downloaded on demand.

        Raises:
            TranscriptionError: If the model cannot be loaded.
        """
        if self._model is not None:
            return
        cached = whisper_model_available(self._config)
        self._log.info(
            "Loading Whisper model '%s' (%s, %s)... cache=%s",
            self._config.whisper_model,
            self._config.whisper_device,
            self._config.whisper_compute_type,
            "found" if cached else "missing (will download on demand)",
        )
        started = time.monotonic()
        try:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self._config.whisper_model,
                device=self._config.whisper_device,
                compute_type=self._config.whisper_compute_type,
            )
        except ImportError as exc:
            raise TranscriptionError(
                "faster-whisper is not installed. Run: pip install -r requirements.txt"
            ) from exc
        except Exception as exc:
            raise TranscriptionError(f"Failed to load Whisper model: {exc}") from exc
        load_seconds = time.monotonic() - started
        self._log.info("Whisper model loaded in %.1fs.", load_seconds)
        self._metrics.observe("speech.model_load_s", load_seconds)

    def warmup(self) -> None:
        """Run one cheap inference to validate the loaded model end to end.

        A 0.5s silent buffer is pushed through a beam-1 decode. A failure
        here means calls would fail later mid-session, so it is surfaced
        immediately with recovery instructions.

        Raises:
            TranscriptionError: If warm-up inference fails.
        """
        if self._model is None:
            self.load()
        import numpy as np

        started = time.monotonic()
        try:
            silent = np.zeros(
                int(self._config.sample_rate * _WARMUP_SECONDS), dtype="float32"
            )
            segments, _info = self._model.transcribe(
                silent,
                language="en",
                beam_size=_WAKE_BEAM_SIZE,
                temperature=0.0,
                condition_on_previous_text=False,
            )
            list(segments)
        except Exception as exc:
            raise TranscriptionError(
                f"Whisper warm-up inference failed: {exc}. "
                "Verify ULTRON_WHISPER_MODEL/DEVICE/COMPUTE_TYPE and reinstall "
                "faster-whisper."
            ) from exc
        duration = time.monotonic() - started
        self._log.info("Whisper warm-up inference OK in %.1fs.", duration)

    @property
    def loaded(self) -> bool:
        """True once the model has been loaded."""
        return self._model is not None

    @retry(
        attempts=3,
        base_delay=0.5,
        backoff=2.0,
        exceptions=(TranscriptionError,),
        jitter=0.1,
    )
    def transcribe(self, wav_path: Path | str) -> str:
        """Transcribe a mono 16 kHz WAV file to text.

        Args:
            wav_path: Path to a PCM WAV file.

        Returns:
            Transcribed text (possibly empty).

        Raises:
            TranscriptionError: If the model is unavailable or the call fails.
        """
        wav_path = Path(wav_path)
        if not wav_path.exists():
            raise TranscriptionError(f"Audio file not found: {wav_path}")
        if self._model is None:
            self.load()
        self._metrics.increment("speech.commands")
        with self._metrics.timer("speech.transcribe"):
            try:
                segments, _info = self._model.transcribe(
                    str(wav_path),
                    language="en",
                    beam_size=_COMMAND_BEAM_SIZE,
                    vad_filter=True,
                    condition_on_previous_text=False,
                )
                return " ".join(segment.text.strip() for segment in segments).strip()
            except TranscriptionError:
                raise
            except Exception as exc:
                raise TranscriptionError(
                    f"Whisper transcription failed: {exc}"
                ) from exc

    def transcribe_wake_window(self, wav_path: Path | str) -> str:
        """Transcribe a short window for wake-phrase detection.

        Uses a faster, lower-beam decode suitable for short utterances.

        Args:
            wav_path: Path to a short PCM WAV file.

        Returns:
            Transcribed text (possibly empty).

        Raises:
            TranscriptionError: On failure.
        """
        if not wav_path.exists():
            raise TranscriptionError(f"Audio file not found: {wav_path}")
        if self._model is None:
            self.load()
        self._metrics.increment("speech.wake_windows")
        with self._metrics.timer("speech.wake_latency"):
            try:
                segments, _info = self._model.transcribe(
                    str(wav_path),
                    language="en",
                    beam_size=_WAKE_BEAM_SIZE,
                    vad_filter=False,
                    condition_on_previous_text=False,
                    temperature=0.0,
                )
                return " ".join(segment.text.strip() for segment in segments).strip()
            except Exception as exc:
                raise TranscriptionError(f"Whisper wake decode failed: {exc}") from exc


def whisper_model_available(config: Config) -> bool:
    """Check whether the configured Whisper model is already cached.

    Args:
        config: Application configuration.

    Returns:
        True if a local cache directory exists for the model.
    """
    cache_root = Path(
        os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface" / "hub")
    )
    model_name = config.whisper_model.replace("/", "--")
    return (cache_root / f"models--Systran--faster-whisper-{model_name}").is_dir() or (
        cache_root / f"models--{model_name}"
    ).is_dir()
