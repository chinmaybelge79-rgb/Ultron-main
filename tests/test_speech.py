"""Speech tests: model availability check and transcription errors."""

from __future__ import annotations

import logging

import pytest

from ultron.utils import TranscriptionError
from ultron.voice.recognizer import SpeechRecognizer, whisper_model_available


def _recognizer(config):
    return SpeechRecognizer(config, logging.getLogger("ultron.speech.test"))


def test_whisper_available_found(tmp_path, monkeypatch, config):
    cache = tmp_path / "hf"
    (cache / "models--Systran--faster-whisper-base").mkdir(parents=True)
    monkeypatch.setenv("HF_HOME", str(cache))
    assert whisper_model_available(config) is True


def test_whisper_available_missing(tmp_path, monkeypatch, config):
    cache = tmp_path / "hf"
    cache.mkdir()
    monkeypatch.setenv("HF_HOME", str(cache))
    assert whisper_model_available(config) is False


def test_whisper_available_alt_name(tmp_path, monkeypatch, config):
    cache = tmp_path / "hf"
    (cache / "models--Systran--faster-whisper-small").mkdir(parents=True)
    monkeypatch.setenv("HF_HOME", str(cache))
    object.__setattr__(config, "whisper_model", "small")
    assert whisper_model_available(config) is True


def test_whisper_available_slashed_model(tmp_path, monkeypatch, config):
    cache = tmp_path / "hf"
    (cache / "models--user--my-model").mkdir(parents=True)
    monkeypatch.setenv("HF_HOME", str(cache))
    object.__setattr__(config, "whisper_model", "user/my-model")
    assert whisper_model_available(config) is True


def test_whisper_available_default_home(tmp_path, monkeypatch, config):
    monkeypatch.delenv("HF_HOME", raising=False)
    assert isinstance(whisper_model_available(config), bool)


def test_transcribe_missing_file_raises(tmp_path, config):
    recognizer = _recognizer(config)
    with pytest.raises(TranscriptionError):
        recognizer.transcribe(tmp_path / "missing.wav")


def test_transcribe_wake_missing_file_raises(tmp_path, config):
    recognizer = _recognizer(config)
    with pytest.raises(TranscriptionError):
        recognizer.transcribe_wake_window(tmp_path / "missing.wav")


def test_load_raises_when_import_missing(config, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("no faster_whisper")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    recognizer = _recognizer(config)
    with pytest.raises(TranscriptionError, match="faster-whisper"):
        recognizer.load()


def test_load_error_message_mentions_pip(config, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(TranscriptionError, match="pip install"):
        _recognizer(config).load()
