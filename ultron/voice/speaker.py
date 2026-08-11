"""Text-to-speech output for Ultron.

Primary engine: ElevenLabs (streamed MP3 played with ``afplay``).
Fallback engine: macOS ``say``. The :class:`Speaker` chooses an engine
per call based on configuration and connectivity (offline detection),
and cleans text for natural spoken output.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Protocol

import requests

from ultron.config import Config
from ultron.monitoring import Metrics, get_metrics
from ultron.utils import TTSError, clean_for_speech, is_online, retry


class VoiceEngine(Protocol):
    """Contract implemented by every speech engine."""

    def speak(self, text: str) -> None: ...


class ElevenLabsEngine:
    """ElevenLabs cloud text-to-speech with retry and file playback.

    Args:
        config: Application configuration.
        logger: Logger instance for the engine.
    """

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self._config = config
        self._log = logger

    @retry(
        attempts=3,
        base_delay=1.0,
        backoff=2.0,
        exceptions=(TTSError,),
        jitter=0.25,
    )
    def speak(self, text: str) -> None:
        """Synthesize and play text via the ElevenLabs API.

        Raises:
            TTSError: If synthesis or playback fails.
        """
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._config.elevenlabs_voice_id}/stream"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self._config.elevenlabs_api_key,
        }
        payload = {
            "text": text,
            "model_id": self._config.elevenlabs_model_id,
            "voice_settings": {
                "stability": self._config.elevenlabs_stability,
                "similarity_boost": self._config.elevenlabs_similarity,
            },
        }
        self._log.debug("Requesting ElevenLabs synthesis (%d chars).", len(text))
        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self._config.llm_timeout,
            )
        except requests.RequestException as exc:
            raise TTSError(f"ElevenLabs request failed: {exc}") from exc
        if response.status_code != 200:
            raise TTSError(
                f"ElevenLabs returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        self._play_audio(response.content)

    def _play_audio(self, audio: bytes) -> None:
        """Play raw MP3 bytes using the macOS ``afplay`` utility."""
        if not audio:
            raise TTSError("ElevenLabs returned empty audio.")
        tmp_path: str = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(audio)
                tmp_path = tmp.name
            result = subprocess.run(
                ["afplay", tmp_path],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                raise TTSError(
                    f"afplay failed with code {result.returncode}: "
                    f"{result.stderr.strip()}"
                )
        except subprocess.TimeoutExpired as exc:
            raise TTSError("afplay timed out.") from exc
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError as exc:
                    self._log.debug(
                        "Could not delete temporary audio %s: %s", tmp_path, exc
                    )


class MacOSVoiceEngine:
    """macOS ``say`` engine used as an offline/fallback voice.

    Args:
        config: Application configuration.
        logger: Logger instance for the engine.
    """

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self._config = config
        self._log = logger

    def speak(self, text: str) -> None:
        """Speak text using the macOS ``say`` command.

        Raises:
            TTSError: If ``say`` fails.
        """
        command = ["say"]
        if self._config.macos_say_voice:
            command += ["-v", self._config.macos_say_voice]
        command.append(text)
        self._log.debug("Speaking with macOS 'say'.")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if result.returncode != 0:
                raise TTSError(
                    f"say failed with code {result.returncode}: {result.stderr.strip()}"
                )
        except subprocess.TimeoutExpired as exc:
            raise TTSError("say timed out.") from exc
        except OSError as exc:
            raise TTSError(f"say is unavailable: {exc}") from exc


class Speaker:
    """Facade that picks the best available voice engine per call.

    Uses ElevenLabs when configured and online; otherwise falls back to
    the macOS ``say`` voice.

    Args:
        config: Application configuration.
        logger: Logger instance for the speaker.
    """

    def __init__(
        self, config: Config, logger: logging.Logger, metrics: Metrics | None = None
    ) -> None:
        self._config = config
        self._log = logger
        self._metrics = metrics or get_metrics()
        self._cloud = ElevenLabsEngine(config, logger)
        self._system = MacOSVoiceEngine(config, logger)

    def speak(self, text: str) -> None:
        """Speak cleaned text through the best available engine.

        Args:
            text: Raw assistant text (markdown will be stripped).
        """
        cleaned = clean_for_speech(text)
        if not cleaned:
            self._log.warning("Refusing to speak empty text.")
            return
        self._metrics.increment("tts.total")
        with self._metrics.timer("tts.latency"):
            if self._config.tts_configured and is_online(
                timeout=self._config.offline_timeout
            ):
                try:
                    self._cloud.speak(cleaned)
                    return
                except TTSError as exc:
                    self._metrics.increment("tts.cloud_errors")
                    self._log.warning(
                        "ElevenLabs failed (%s); falling back to system voice.", exc
                    )
            self._metrics.increment("tts.fallback")
            self._system.speak(cleaned)
