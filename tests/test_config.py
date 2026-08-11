"""Configuration tests: parsing, defaults, paths, and validation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ultron.config import Config
from ultron.utils import ConfigError


def _write_env(tmp_path, content: str) -> Path:
    env_file = tmp_path / ".env.test"
    env_file.write_text(content, encoding="utf-8")
    return env_file


def test_defaults_apply(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    cfg = Config.from_env(dotenv_path=_write_env(tmp_path, ""))
    assert cfg.wake_phrase == "hey ultron"
    assert cfg.wake_acknowledgements == ("Yes sir?",)
    assert cfg.sample_rate == 16000
    assert cfg.channels == 1
    assert cfg.block_size == 512
    assert cfg.silence_threshold == 0.006
    assert cfg.silence_duration == 0.9
    assert cfg.speech_start_timeout == 6.0
    assert cfg.command_timeout == 12.0
    assert cfg.wake_window_seconds == 2.0
    assert cfg.whisper_model == "base"
    assert cfg.whisper_device == "cpu"
    assert cfg.whisper_compute_type == "int8"
    assert cfg.openrouter_model == "openai/gpt-4o-mini"
    assert cfg.openrouter_url == "https://openrouter.ai/api/v1/chat/completions"
    assert cfg.llm_temperature == 0.3
    assert cfg.llm_max_tokens == 400
    assert cfg.elevenlabs_voice_id == "kx5PgdDVv8ns0ma9VLxo"
    assert cfg.elevenlabs_model_id == "eleven_turbo_v2_5"
    assert cfg.tools_command_timeout == 30.0
    assert cfg.offline_timeout == 2.0
    assert cfg.mic_device is None
    assert cfg.output_device is None
    assert not cfg.llm_configured
    assert not cfg.tts_configured


def test_env_strings_parsed(tmp_path, monkeypatch):
    monkeypatch.setenv("ULTRON_WAKE_PHRASE", "Hey  Doctor ")
    monkeypatch.setenv("ULTRON_WAKE_ACK", "What is it?,  Yes? ")
    monkeypatch.setenv("ULTRON_WHISPER_MODEL", "small")
    monkeypatch.setenv("ULTRON_SAMPLE_RATE", "8000")
    monkeypatch.setenv("ULTRON_CHANNELS", "2")
    monkeypatch.setenv("ULTRON_BLOCK_SIZE", "256")
    cfg = Config.from_env(dotenv_path=_write_env(tmp_path, ""))
    assert cfg.wake_phrase == "hey  doctor"
    assert cfg.wake_acknowledgements == ("What is it?", "Yes?")
    assert cfg.whisper_model == "small"
    assert cfg.sample_rate == 8000
    assert cfg.channels == 2
    assert cfg.block_size == 256


def test_env_api_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
    cfg = Config.from_env(dotenv_path=_write_env(tmp_path, ""))
    assert cfg.llm_configured
    assert cfg.tts_configured
    assert cfg.api_keys_configured


def test_mic_device_optional(tmp_path, monkeypatch):
    monkeypatch.delenv("ULTRON_MIC_DEVICE", raising=False)
    cfg_no = Config.from_env(dotenv_path=_write_env(tmp_path, ""))
    assert cfg_no.mic_device is None
    monkeypatch.setenv("ULTRON_MIC_DEVICE", "2")
    cfg_yes = Config.from_env(dotenv_path=_write_env(tmp_path, ""))
    assert cfg_yes.mic_device == 2


def test_paths_resolved(tmp_path):
    cfg = Config()
    assert Path(cfg.project_dir).is_absolute()
    assert cfg.db_path.name == "ultron_memory.db"
    assert cfg.log_dir.name == "logs"
    assert cfg.cache_dir.name == "cache"
    assert cfg.screenshot_dir.name == "screenshots"


def test_project_dir_static():
    expected = Path(__file__).resolve().parent.parent
    assert Config.project_dir_default() == expected


def test_missing_services_both(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    cfg = Config.from_env(dotenv_path=_write_env(tmp_path, ""))
    missing = cfg.missing_services()
    assert "OpenRouter (brain)" in missing
    assert "ElevenLabs (voice)" in missing


def test_missing_services_none_when_full(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
    cfg = Config.from_env(dotenv_path=_write_env(tmp_path, ""))
    assert cfg.missing_services() == []
    assert cfg.api_keys_configured


def test_api_keys_configured_partial(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    cfg = Config.from_env(dotenv_path=_write_env(tmp_path, ""))
    assert cfg.llm_configured
    assert not cfg.tts_configured
    assert not cfg.api_keys_configured


def test_invalid_float_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ULTRON_SILENCE_THRESHOLD", "not-a-number")
    with pytest.raises(ConfigError):
        Config.from_env(dotenv_path=_write_env(tmp_path, ""))


def test_invalid_int_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ULTRON_BLOCK_SIZE", "abc")
    with pytest.raises(ConfigError):
        Config.from_env(dotenv_path=_write_env(tmp_path, ""))


def test_empty_wake_acknowledgements_raises():
    with pytest.raises(ConfigError):
        Config(wake_acknowledgements=())


def test_wake_ack_env_blank_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ULTRON_WAKE_ACK", "")
    cfg = Config.from_env(dotenv_path=_write_env(tmp_path, ""))
    assert cfg.wake_acknowledgements == ("Yes sir?",)


def test_wake_ack_explicit_single(tmp_path, monkeypatch):
    monkeypatch.setenv("ULTRON_WAKE_ACK", "At your service")
    cfg = Config.from_env(dotenv_path=_write_env(tmp_path, ""))
    assert cfg.wake_acknowledgements == ("At your service",)


@pytest.mark.parametrize(
    ("field", "value", "error_text"),
    [
        ("silence_duration", 0.0, "ULTRON_SILENCE_DURATION must be > 0"),
        ("command_timeout", -1.0, "ULTRON_COMMAND_TIMEOUT must be > 0"),
        (
            "speech_start_timeout",
            0.0,
            "ULTRON_SPEECH_START_TIMEOUT must be > 0",
        ),
        ("llm_max_tokens", 0, "ULTRON_LLM_MAX_TOKENS must be > 0"),
        ("tools_command_timeout", -5.0, "ULTRON_TOOLS_TIMEOUT must be > 0"),
    ],
)
def test_validation_bounds(field, value, error_text):
    with pytest.raises(ConfigError, match=error_text):
        Config(**{field: value})


@pytest.mark.parametrize(
    "temperature",
    [-0.1, 2.5],
)
def test_invalid_temperature_raises(temperature):
    with pytest.raises(ConfigError, match="ULTRON_LLM_TEMPERATURE"):
        Config(llm_temperature=temperature)


def test_boundary_temperature_valid():
    assert Config(llm_temperature=0.0).llm_temperature == 0.0
    assert Config(llm_temperature=2.0).llm_temperature == 2.0


def test_routing_policy_defaults_and_parse(tmp_path, monkeypatch):
    monkeypatch.delenv("ULTRON_ROUTING_POLICY", raising=False)
    cfg = Config.from_env(dotenv_path=_write_env(tmp_path, ""))
    assert cfg.routing_policy.value == "auto"


def test_routing_policy_parse_from_env(tmp_path, monkeypatch):
    monkeypatch.delenv("ULTRON_ROUTING_POLICY", raising=False)
    try:
        cfg = Config.from_env(
            dotenv_path=_write_env(tmp_path, "ULTRON_ROUTING_POLICY=local_only")
        )
    finally:
        os.environ.pop("ULTRON_ROUTING_POLICY", None)
    assert cfg.routing_policy.value == "local_only"


def test_routing_policy_invalid_raises(tmp_path, monkeypatch):
    from ultron.utils import ConfigError

    monkeypatch.delenv("ULTRON_ROUTING_POLICY", raising=False)
    with pytest.raises(ConfigError, match="ULTRON_ROUTING_POLICY"):
        try:
            Config.from_env(
                dotenv_path=_write_env(tmp_path, "ULTRON_ROUTING_POLICY=banana")
            )
        finally:
            os.environ.pop("ULTRON_ROUTING_POLICY", None)


def test_wake_threshold_default_and_validation(tmp_path, monkeypatch):
    from ultron.utils import ConfigError

    monkeypatch.delenv("ULTRON_WAKE_MATCH_THRESHOLD", raising=False)
    cfg = Config.from_env(dotenv_path=_write_env(tmp_path, ""))
    assert cfg.wake_match_threshold == 0.75
    with pytest.raises(ConfigError):
        try:
            Config.from_env(
                dotenv_path=_write_env(tmp_path, "ULTRON_WAKE_MATCH_THRESHOLD=1.5")
            )
        finally:
            os.environ.pop("ULTRON_WAKE_MATCH_THRESHOLD", None)


def test_wake_variants_from_env(tmp_path, monkeypatch):
    monkeypatch.delenv("ULTRON_WAKE_VARIANTS", raising=False)
    content = "ULTRON_WAKE_VARIANTS=yo ultron,sup ultron"
    try:
        cfg = Config.from_env(dotenv_path=_write_env(tmp_path, content))
    finally:
        os.environ.pop("ULTRON_WAKE_VARIANTS", None)
    assert "yo ultron" in cfg.wake_variants
    assert "sup ultron" in cfg.wake_variants


def test_elevenlabs_voice_is_ultron(tmp_path, monkeypatch):
    cfg = Config.from_env(dotenv_path=_write_env(tmp_path, ""))
    assert cfg.elevenlabs_voice_id == "kx5PgdDVv8ns0ma9VLxo"
