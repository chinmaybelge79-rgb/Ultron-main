"""Speaker tests: engine behavior and fallback selection."""

from __future__ import annotations

import logging
import subprocess

import pytest
import requests

from ultron.utils import TTSError
from ultron.voice.speaker import (
    ElevenLabsEngine,
    MacOSVoiceEngine,
    Speaker,
)


def _speaker(config):
    logger = logging.getLogger("ultron.speaker.test")
    logger.disabled = True
    return Speaker(config, logger)


def _eleven(config):
    logger = logging.getLogger("ultron.speaker.test")
    logger.disabled = True
    return ElevenLabsEngine(config, logger)


def _no_sleep(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda _: None)


# ---------------------------------------------------------------------------
# MacOSVoiceEngine
# ---------------------------------------------------------------------------


def test_say_success(monkeypatch, config):
    def fake_run(cmd, **kwargs):
        assert cmd[0] == "say"
        assert "hello" in cmd[-1]
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    MacOSVoiceEngine(config, logging.getLogger("t")).speak("hello sir")


def test_say_failure(monkeypatch, config):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(TTSError):
        MacOSVoiceEngine(config, logging.getLogger("t")).speak("hello")


def test_say_missing_binary(monkeypatch, config):
    def fake_run(cmd, **kwargs):
        raise OSError("say not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(TTSError):
        MacOSVoiceEngine(config, logging.getLogger("t")).speak("hello")


def test_say_uses_configured_voice(monkeypatch, config):
    object.__setattr__(config, "macos_say_voice", "Samantha")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    MacOSVoiceEngine(config, logging.getLogger("t")).speak("hi")
    assert "-v" in captured["cmd"]
    assert "Samantha" in captured["cmd"]


# ---------------------------------------------------------------------------
# ElevenLabsEngine
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, content=b"mp3", text=""):
        self.status_code = status_code
        self.content = content
        self.text = text


def test_eleven_success(monkeypatch, config, tmp_path):
    _no_sleep(monkeypatch)
    played = {}

    def fake_post(url, **kwargs):
        return _FakeResponse()

    def fake_run(cmd, **kwargs):
        played["file"] = cmd[1]
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(subprocess, "run", fake_run)
    _eleven(config).speak("hello")
    assert played["file"].endswith(".mp3")
    assert not __import__("os").path.exists(played["file"])


def test_eleven_http_error(monkeypatch, config):
    _no_sleep(monkeypatch)

    def fake_post(url, **kwargs):
        return _FakeResponse(status_code=401, text="bad key")

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(TTSError):
        _eleven(config).speak("hello")


def test_eleven_request_error(monkeypatch, config):
    _no_sleep(monkeypatch)

    def fake_post(url, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(TTSError):
        _eleven(config).speak("hello")


def test_eleven_empty_audio(monkeypatch, config):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(
        requests, "post", lambda url, **kwargs: _FakeResponse(content=b"")
    )
    with pytest.raises(TTSError):
        _eleven(config).speak("hello")


def test_eleven_afplay_failure(monkeypatch, config):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: _FakeResponse())

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "device busy")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(TTSError):
        _eleven(config).speak("hello")


# ---------------------------------------------------------------------------
# Speaker facade
# ---------------------------------------------------------------------------


class RecordingVoice:
    def __init__(self):
        self.calls = []

    def speak(self, text):
        self.calls.append(text)


def test_speaker_empty_text_refused(config):
    speaker = _speaker(config)
    speaker._cloud = RecordingVoice()
    speaker._system = RecordingVoice()
    speaker.speak("   ")
    assert speaker._cloud.calls == []
    assert speaker._system.calls == []


def test_speaker_uses_system_when_not_configured(monkeypatch, config):
    monkeypatch.setattr("ultron.voice.speaker.is_online", lambda timeout=2.0: True)
    object.__setattr__(config, "elevenlabs_api_key", "")
    speaker = _speaker(config)
    speaker._cloud = RecordingVoice()
    speaker._system = RecordingVoice()
    speaker.speak("hello")
    assert speaker._system.calls == ["hello"]
    assert speaker._cloud.calls == []


def test_speaker_uses_system_when_offline(monkeypatch, config):
    monkeypatch.setattr("ultron.voice.speaker.is_online", lambda timeout=2.0: False)
    object.__setattr__(config, "elevenlabs_api_key", "el-key")
    speaker = _speaker(config)
    speaker._cloud = RecordingVoice()
    speaker._system = RecordingVoice()
    speaker.speak("hello")
    assert speaker._system.calls == ["hello"]
    assert speaker._cloud.calls == []


def test_speaker_uses_cloud_when_configured_and_online(monkeypatch, config):
    monkeypatch.setattr("ultron.voice.speaker.is_online", lambda timeout=2.0: True)
    object.__setattr__(config, "elevenlabs_api_key", "el-key")
    speaker = _speaker(config)
    speaker._cloud = RecordingVoice()
    speaker._system = RecordingVoice()
    speaker.speak("hello")
    assert speaker._cloud.calls == ["hello"]
    assert speaker._system.calls == []


def test_speaker_falls_back_when_cloud_fails(monkeypatch, config):
    monkeypatch.setattr("ultron.voice.speaker.is_online", lambda timeout=2.0: True)
    object.__setattr__(config, "elevenlabs_api_key", "el-key")

    class FailingCloud:
        def speak(self, text):
            raise TTSError("cloud down")

    speaker = _speaker(config)
    speaker._cloud = FailingCloud()
    speaker._system = RecordingVoice()
    speaker.speak("hello")
    assert speaker._system.calls == ["hello"]


def test_speaker_cleans_markdown_before_speaking(monkeypatch, config):
    monkeypatch.setattr("ultron.voice.speaker.is_online", lambda timeout=2.0: False)
    speaker = _speaker(config)
    speaker._system = RecordingVoice()
    speaker.speak("**bold** text")
    assert speaker._system.calls == ["bold text"]
