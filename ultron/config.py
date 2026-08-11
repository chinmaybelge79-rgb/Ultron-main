"""Configuration for Ultron.

All settings are loaded once from the environment (plus an optional
``.env`` file) into an immutable :class:`Config` object, which is then
injected into every component. There is no global mutable state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

from ultron.utils import ConfigError

_DEFAULT_WAKE_PHRASE = "hey ultron"
_DEFAULT_WHISPER_MODEL = "base"
_DEFAULT_OPENROUTER_MODEL = "openai/gpt-4o-mini"
_DEFAULT_ELEVENLABS_VOICE = "kx5PgdDVv8ns0ma9VLxo"
_DEFAULT_ELEVENLABS_MODEL = "eleven_turbo_v2_5"
_DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
_DEFAULT_OLLAMA_CODE_MODEL = "qwen2.5-coder:7b"
_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


class RoutingPolicy(Enum):
    """Deterministic LLM provider selection policy.

    ``AUTO`` and ``PREFER_LOCAL`` both try the local Ollama server first
    and fall back to OpenRouter; ``PREFER_REMOTE`` is the mirror image.
    The ``*_ONLY`` policies never cross between local and remote, so a
    production box can be pinned to a single backend.
    """

    AUTO = "auto"
    LOCAL_ONLY = "local_only"
    REMOTE_ONLY = "remote_only"
    PREFER_LOCAL = "prefer_local"
    PREFER_REMOTE = "prefer_remote"

    @classmethod
    def parse(cls, value: str) -> RoutingPolicy:
        """Parse a routing policy name, raising ConfigError for unknown values."""
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            valid = ", ".join(policy.value for policy in cls)
            raise ConfigError(
                f"ULTRON_ROUTING_POLICY must be one of: {valid} (got {value!r})"
            ) from exc


def _env_str(name: str, default: str) -> str:
    """Read a string from the environment, falling back to ``default``."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _env_float(name: str, default: float) -> float:
    """Read a float from the environment, falling back to ``default``."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {value!r}") from exc


def _env_int(name: str, default: int) -> int:
    """Read an integer from the environment, falling back to ``default``."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean from the environment."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Read a comma-separated list from the environment."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Config:
    """Immutable application configuration.

    Attributes:
        project_dir: Root directory of the Ultron project.
        wake_phrase: Phrase that activates the assistant.
        wake_acknowledgements: Spoken replies after the wake phrase.
        shutdown_phrases: Exact phrases (normalized) that request shutdown.
        sample_rate: Microphone sample rate in Hz (16 kHz for Whisper).
        channels: Number of microphone channels to capture.
        block_size: Samples per audio block read from the mic.
        silence_threshold: RMS level below which audio counts as silence.
        silence_duration: Seconds of trailing silence that ends a command.
        speech_start_timeout: Seconds to wait for speech before giving up.
        command_timeout: Hard cap on command recording, in seconds.
        wake_window_seconds: Audio window transcribed while waiting to wake.
        wake_window_overlap: Fraction of the wake window carried forward
            between successive transcription windows so the wake phrase is
            never clipped at a fixed window boundary (0.0 = no overlap).
        whisper_model: Faster-Whisper model size/name.
        whisper_device: Device used by Faster-Whisper (cpu / cuda).
        whisper_compute_type: Faster-Whisper compute type (int8 / float32).
        openrouter_api_key: OpenRouter API key (may be empty).
        openrouter_model: OpenRouter model identifier.
        openrouter_url: OpenRouter chat completions endpoint.
        openrouter_headers: Extra HTTP headers for OpenRouter.
        llm_temperature: Sampling temperature for the LLM.
        llm_max_tokens: Maximum tokens for the LLM response.
        llm_timeout: (connect, read) timeout in seconds for HTTP calls.
        elevenlabs_api_key: ElevenLabs API key (may be empty).
        elevenlabs_voice_id: ElevenLabs voice identifier.
        elevenlabs_model_id: ElevenLabs synthesis model.
        elevenlabs_stability: Voice stability parameter.
        elevenlabs_similarity: Voice similarity boost parameter.
        macos_say_voice: macOS ``say`` voice used as fallback.
        ollama_url: Ollama API endpoint.
        ollama_model: Default Ollama model for general tasks.
        ollama_code_model: Ollama model for coding tasks.
        ollama_enabled: Whether Ollama local inference is enabled.
        embedding_model: Sentence-transformer model for embeddings.
        embedding_dim: Embedding vector dimensionality.
        db_path: Path to the SQLite memory database.
        log_dir: Directory for log files.
        cache_dir: Directory for temporary audio files.
        screenshot_dir: Directory where screenshots are saved.
        tools_command_timeout: Timeout for shell tool executions.
        offline_timeout: Timeout used for connectivity probes.
        mic_device: Optional numeric microphone device index.
        output_device: Optional numeric audio output device index.
    """

    project_dir: Path = Path(__file__).resolve().parent.parent
    wake_phrase: str = _DEFAULT_WAKE_PHRASE
    wake_variants: tuple[str, ...] = (
        "hey ultron",
        "hi ultron",
        "okay ultron",
        "ok ultron",
        "hello ultron",
    )
    wake_match_threshold: float = 0.75
    wake_acknowledgements: tuple[str, ...] = ("Yes sir?",)
    shutdown_phrases: tuple[str, ...] = (
        "goodbye",
        "shut down",
        "shutdown",
        "go to sleep",
        "stop ultron",
        "exit ultron",
        "quit ultron",
        "ultron stop",
        "ultron quit",
        "that's all",
    )
    sample_rate: int = 16000
    channels: int = 1
    block_size: int = 512
    silence_threshold: float = 0.006
    silence_duration: float = 0.9
    speech_start_timeout: float = 6.0
    command_timeout: float = 12.0
    wake_window_seconds: float = 2.0
    wake_window_overlap: float = 0.5
    whisper_model: str = _DEFAULT_WHISPER_MODEL
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    openrouter_api_key: str = ""
    openrouter_model: str = _DEFAULT_OPENROUTER_MODEL
    openrouter_url: str = "https://openrouter.ai/api/v1/chat/completions"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 400
    llm_timeout: tuple[float, float] = (5.0, 60.0)
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = _DEFAULT_ELEVENLABS_VOICE
    elevenlabs_model_id: str = _DEFAULT_ELEVENLABS_MODEL
    elevenlabs_stability: float = 0.5
    elevenlabs_similarity: float = 0.75
    macos_say_voice: str = ""
    # --- Ollama (local LLM) ---
    ollama_url: str = _DEFAULT_OLLAMA_URL
    ollama_model: str = _DEFAULT_OLLAMA_MODEL
    ollama_code_model: str = _DEFAULT_OLLAMA_CODE_MODEL
    ollama_enabled: bool = True
    ollama_thinking: bool = False
    # --- Provider routing ---
    routing_policy: RoutingPolicy = RoutingPolicy.AUTO
    run_startup_checks: bool = True
    # --- Embeddings ---
    embedding_model: str = _DEFAULT_EMBEDDING_MODEL
    embedding_dim: int = 384
    # --- Derived paths ---
    db_path: Path = field(init=False)
    log_dir: Path = field(init=False)
    cache_dir: Path = field(init=False)
    screenshot_dir: Path = field(init=False)
    tools_command_timeout: float = 30.0
    offline_timeout: float = 2.0
    mic_device: int | None = None
    output_device: int | None = None

    def __post_init__(self) -> None:
        """Resolve derived paths and validate the configuration."""
        project_dir = Path(self.project_dir).resolve()
        object.__setattr__(self, "project_dir", project_dir)
        object.__setattr__(self, "db_path", project_dir / "ultron_memory.db")
        object.__setattr__(self, "log_dir", project_dir / "logs")
        object.__setattr__(self, "cache_dir", project_dir / "assets" / "cache")
        object.__setattr__(self, "screenshot_dir", project_dir / "logs" / "screenshots")

        if not self.wake_phrase.strip():
            raise ConfigError("Wake phrase cannot be empty (ULTRON_WAKE_PHRASE).")
        if not self.wake_acknowledgements:
            raise ConfigError(
                "Wake acknowledgements cannot be empty (ULTRON_WAKE_ACK)."
            )
        if self.sample_rate <= 0:
            raise ConfigError(f"Invalid sample rate: {self.sample_rate}")
        if self.block_size <= 0:
            raise ConfigError(f"Invalid block size: {self.block_size}")
        if self.silence_threshold < 0.0:
            raise ConfigError(f"Invalid silence threshold: {self.silence_threshold}")
        if self.silence_duration <= 0.0:
            raise ConfigError("ULTRON_SILENCE_DURATION must be > 0")
        if self.command_timeout <= 0.0:
            raise ConfigError("ULTRON_COMMAND_TIMEOUT must be > 0")
        if self.speech_start_timeout <= 0.0:
            raise ConfigError("ULTRON_SPEECH_START_TIMEOUT must be > 0")
        if self.llm_max_tokens <= 0:
            raise ConfigError("ULTRON_LLM_MAX_TOKENS must be > 0")
        if not 0.0 <= self.llm_temperature <= 2.0:
            raise ConfigError("ULTRON_LLM_TEMPERATURE must be within [0.0, 2.0]")
        if self.tools_command_timeout <= 0.0:
            raise ConfigError("ULTRON_TOOLS_TIMEOUT must be > 0")
        if not 0.0 <= self.wake_match_threshold <= 1.0:
            raise ConfigError(
                "ULTRON_WAKE_MATCH_THRESHOLD must be within [0.0, 1.0]"
            )

        for directory in (self.log_dir, self.cache_dir, self.screenshot_dir):
            directory.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls, dotenv_path: Path | None = None) -> Config:
        """Build a :class:`Config` from environment variables.

        Args:
            dotenv_path: Optional path to a ``.env`` file to load first.

        Returns:
            A fully resolved, validated configuration.

        Raises:
            ConfigError: If the configuration is invalid.
        """
        env_file = dotenv_path or (cls.project_dir_default() / ".env")
        if env_file.exists():
            load_dotenv(env_file, override=True)

        mic_device = os.environ.get("ULTRON_MIC_DEVICE")
        output_device = os.environ.get("ULTRON_OUTPUT_DEVICE")

        return cls(
            wake_phrase=_env_str("ULTRON_WAKE_PHRASE", _DEFAULT_WAKE_PHRASE).lower(),
            wake_variants=_env_list(
                "ULTRON_WAKE_VARIANTS",
                (
                    "hey ultron",
                    "hi ultron",
                    "okay ultron",
                    "ok ultron",
                    "hello ultron",
                ),
            ),
            wake_match_threshold=_env_float("ULTRON_WAKE_MATCH_THRESHOLD", 0.75),
            wake_acknowledgements=_env_list("ULTRON_WAKE_ACK", ("Yes sir?",)),
            shutdown_phrases=_env_list(
                "ULTRON_SHUTDOWN_PHRASES",
                (
                    "goodbye",
                    "shut down",
                    "shutdown",
                    "go to sleep",
                    "stop ultron",
                    "exit ultron",
                    "quit ultron",
                    "ultron stop",
                    "ultron quit",
                    "that's all",
                ),
            ),
            sample_rate=_env_int("ULTRON_SAMPLE_RATE", 16000),
            channels=_env_int("ULTRON_CHANNELS", 1),
            block_size=_env_int("ULTRON_BLOCK_SIZE", 512),
            silence_threshold=_env_float("ULTRON_SILENCE_THRESHOLD", 0.006),
            silence_duration=_env_float("ULTRON_SILENCE_DURATION", 0.9),
            speech_start_timeout=_env_float("ULTRON_SPEECH_START_TIMEOUT", 6.0),
            command_timeout=_env_float("ULTRON_COMMAND_TIMEOUT", 12.0),
            wake_window_seconds=_env_float("ULTRON_WAKE_WINDOW", 2.0),
            wake_window_overlap=_env_float("ULTRON_WAKE_WINDOW_OVERLAP", 0.5),
            whisper_model=_env_str("ULTRON_WHISPER_MODEL", _DEFAULT_WHISPER_MODEL),
            whisper_device=_env_str("ULTRON_WHISPER_DEVICE", "cpu"),
            whisper_compute_type=_env_str("ULTRON_WHISPER_COMPUTE_TYPE", "int8"),
            openrouter_api_key=_env_str("OPENROUTER_API_KEY", ""),
            openrouter_model=_env_str(
                "ULTRON_OPENROUTER_MODEL", _DEFAULT_OPENROUTER_MODEL
            ),
            openrouter_url=_env_str(
                "ULTRON_OPENROUTER_URL",
                "https://openrouter.ai/api/v1/chat/completions",
            ),
            llm_temperature=_env_float("ULTRON_LLM_TEMPERATURE", 0.3),
            llm_max_tokens=_env_int("ULTRON_LLM_MAX_TOKENS", 400),
            elevenlabs_api_key=_env_str("ELEVENLABS_API_KEY", ""),
            elevenlabs_voice_id=_env_str(
                "ULTRON_ELEVENLABS_VOICE_ID", _DEFAULT_ELEVENLABS_VOICE
            ),
            elevenlabs_model_id=_env_str(
                "ULTRON_ELEVENLABS_MODEL_ID", _DEFAULT_ELEVENLABS_MODEL
            ),
            elevenlabs_stability=_env_float("ULTRON_ELEVENLABS_STABILITY", 0.5),
            elevenlabs_similarity=_env_float("ULTRON_ELEVENLABS_SIMILARITY", 0.75),
            macos_say_voice=_env_str("ULTRON_MACOS_SAY_VOICE", ""),
            ollama_url=_env_str("ULTRON_OLLAMA_URL", _DEFAULT_OLLAMA_URL),
            ollama_model=_env_str("ULTRON_OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL),
            ollama_code_model=_env_str(
                "ULTRON_OLLAMA_CODE_MODEL", _DEFAULT_OLLAMA_CODE_MODEL
            ),
            ollama_enabled=_env_bool("ULTRON_OLLAMA_ENABLED", True),
            ollama_thinking=_env_bool("ULTRON_OLLAMA_THINKING", False),
            routing_policy=RoutingPolicy.parse(
                _env_str("ULTRON_ROUTING_POLICY", RoutingPolicy.AUTO.value)
            ),
            run_startup_checks=_env_bool("ULTRON_RUN_STARTUP_CHECKS", True),
            embedding_model=_env_str(
                "ULTRON_EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL
            ),
            embedding_dim=_env_int("ULTRON_EMBEDDING_DIM", 384),
            tools_command_timeout=_env_float("ULTRON_TOOLS_TIMEOUT", 30.0),
            offline_timeout=_env_float("ULTRON_OFFLINE_TIMEOUT", 2.0),
            mic_device=(
                _env_int("ULTRON_MIC_DEVICE", -1) if mic_device is not None else None
            ),
            output_device=(
                _env_int("ULTRON_OUTPUT_DEVICE", -1)
                if output_device is not None
                else None
            ),
        )

    @staticmethod
    def project_dir_default() -> Path:
        """Return the project directory for the ``from_env`` default dotenv path."""
        return Path(__file__).resolve().parent.parent

    @property
    def api_keys_configured(self) -> bool:
        """True when both remote API keys are present."""
        return bool(self.openrouter_api_key) and bool(self.elevenlabs_api_key)

    @property
    def llm_configured(self) -> bool:
        """True when an OpenRouter key is available."""
        return bool(self.openrouter_api_key)

    @property
    def tts_configured(self) -> bool:
        """True when an ElevenLabs key is available."""
        return bool(self.elevenlabs_api_key)

    @property
    def local_llm_configured(self) -> bool:
        """True when Ollama is enabled."""
        return self.ollama_enabled

    @property
    def any_llm_configured(self) -> bool:
        """True when any LLM backend is available."""
        return self.llm_configured or self.local_llm_configured

    def missing_services(self) -> list[str]:
        """Return names of optional services that are not configured."""
        if self.api_keys_configured:
            return []
        missing: list[str] = []
        if not self.llm_configured:
            missing.append("OpenRouter (brain)")
        if not self.tts_configured:
            missing.append("ElevenLabs (voice)")
        return missing
