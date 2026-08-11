"""Listener tests: RMS math, recording state machine, wake backoff."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from ultron.utils import AudioError
from ultron.voice.listener import (
    Listener,
    _command_filename,
    _rms,
    _wake_filename,
    delete_wav,
    match_wake_phrase,
)
from ultron.voice.recognizer import SpeechRecognizer


class FakeStream:
    """Minimal stand-in for a sounddevice InputStream."""

    def __init__(self, blocks):
        self._blocks = [np.asarray(b, dtype="float32") for b in blocks]
        self.started = False
        self.closed = False

    def read(self, frames):
        if not self._blocks:
            raise RuntimeError("stream exhausted")
        block = self._blocks.pop(0)[: int(frames)]
        return block.reshape(-1, 1), False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True


def _zero_block(frames, value=0.0):
    return np.full((frames,), value, dtype="float32")


def _make_listener(config, recognizer=None):
    if recognizer is None:
        recognizer = SpeechRecognizer(config, _quiet_logger())
    return Listener(config, recognizer, _quiet_logger())


def _quiet_logger():
    import logging

    logger = logging.getLogger("ultron.listener.test")
    logger.disabled = True
    return logger


def _counting_monotonic(start=10.0, step=0.05):
    state = {"value": start}

    def counter():
        value = state["value"]
        state["value"] += step
        return value

    return counter


# ---------------------------------------------------------------------------
# _rms
# ---------------------------------------------------------------------------


def test_rms_zeros():
    assert _rms(np.zeros(10)) == 0.0


def test_rms_ones():
    assert _rms(np.ones(10)) == pytest.approx(1.0)


def test_rms_empty():
    assert _rms(np.array([])) == 0.0


def test_rms_negative_values():
    assert _rms(np.full(4, -0.5)) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# filenames
# ---------------------------------------------------------------------------


def test_filenames_include_pid():
    assert str(os.getpid()) in _wake_filename()
    assert str(os.getpid()) in _command_filename()


def test_delete_wav(tmp_path):
    path = tmp_path / "x.wav"
    path.write_bytes(b"data")
    delete_wav(path)
    assert not path.exists()


def test_delete_wav_missing_ok(tmp_path):
    delete_wav(tmp_path / "nope.wav")


# ---------------------------------------------------------------------------
# stop_requested
# ---------------------------------------------------------------------------


def test_stop_requested(config):
    listener = _make_listener(config)
    assert not listener.stop_requested()
    listener.request_stop()
    assert listener.stop_requested()


# ---------------------------------------------------------------------------
# start() failure path
# ---------------------------------------------------------------------------


def test_start_raises_audio_error_on_failure(config, monkeypatch):
    def broken_stream(**kwargs):
        raise RuntimeError("no device")

    monkeypatch.setattr("ultron.voice.listener.sd.InputStream", broken_stream)
    listener = _make_listener(config)
    with pytest.raises(AudioError):
        listener.start()


def test_start_second_call_noop(config):
    listener = _make_listener(config)
    listener._stream = FakeStream([_zero_block(5)])
    listener.start()
    assert listener._stream.started is False


# ---------------------------------------------------------------------------
# record_command: no speech -> None
# ---------------------------------------------------------------------------


def test_record_command_no_speech_times_out(config, monkeypatch):
    object.__setattr__(config, "sample_rate", 10)
    object.__setattr__(config, "block_size", 5)
    object.__setattr__(config, "silence_threshold", 1.0)
    object.__setattr__(config, "speech_start_timeout", 0.2)
    object.__setattr__(config, "command_timeout", 5.0)
    object.__setattr__(config, "silence_duration", 0.2)
    monkeypatch.setattr(time, "monotonic", _counting_monotonic())

    listener = _make_listener(config)
    listener._stream = FakeStream([_zero_block(5)] * 10)
    assert listener.record_command() is None


# ---------------------------------------------------------------------------
# record_command: silence ends recording
# ---------------------------------------------------------------------------


def test_record_command_silence_detected(config, tmp_path):
    object.__setattr__(config, "sample_rate", 10)
    object.__setattr__(config, "block_size", 5)
    object.__setattr__(config, "silence_threshold", 0.1)
    object.__setattr__(config, "speech_start_timeout", 5.0)
    object.__setattr__(config, "command_timeout", 5.0)
    object.__setattr__(config, "silence_duration", 0.2)

    blocks = [
        _zero_block(5),  # floor measurement
        np.full((5,), 1.0, dtype="float32"),  # speech
        _zero_block(5),  # trailing silence -> end
    ]
    listener = _make_listener(config)
    listener._stream = FakeStream(blocks)
    path = listener.record_command()
    assert path is not None
    assert Path(path).exists()
    assert path.name.startswith("command-")
    assert path.parent == config.cache_dir


# ---------------------------------------------------------------------------
# record_command: stop requested during recording
# ---------------------------------------------------------------------------


def test_record_command_stop_returns_none(config):
    object.__setattr__(config, "sample_rate", 10)
    object.__setattr__(config, "block_size", 5)
    object.__setattr__(config, "silence_threshold", 0.1)
    object.__setattr__(config, "speech_start_timeout", 5.0)
    object.__setattr__(config, "command_timeout", 5.0)

    listener = _make_listener(config)
    listener.request_stop()
    listener._stream = FakeStream([np.full((5,), 1.0, dtype="float32")] * 2)
    assert listener.record_command() is None


# ---------------------------------------------------------------------------
# record_command: command timeout cap
# ---------------------------------------------------------------------------


def test_record_command_hard_timeout(config, monkeypatch):
    object.__setattr__(config, "sample_rate", 10)
    object.__setattr__(config, "block_size", 5)
    object.__setattr__(config, "silence_threshold", 0.1)
    object.__setattr__(config, "speech_start_timeout", 5.0)
    object.__setattr__(config, "command_timeout", 0.15)
    object.__setattr__(config, "silence_duration", 5.0)
    monkeypatch.setattr(time, "monotonic", _counting_monotonic())

    listener = _make_listener(config)
    blocks = [
        _zero_block(5),
        np.full((5,), 1.0, dtype="float32"),
        np.full((5,), 1.0, dtype="float32"),
        np.full((5,), 1.0, dtype="float32"),
    ]
    listener._stream = FakeStream(blocks)
    path = listener.record_command()
    assert path is not None


# ---------------------------------------------------------------------------
# wake backoff
# ---------------------------------------------------------------------------


class FailingWakeRecognizer:
    def __init__(self, listener, failures=3):
        self._listener = listener
        self._failures = failures
        self._count = 0

    def transcribe_wake_window(self, path):
        self._count += 1
        if self._count > self._failures:
            self._listener.request_stop()
        raise RuntimeError("decode boom")


def test_wake_backoff_grows_and_stops(config, monkeypatch):
    object.__setattr__(config, "sample_rate", 10)
    object.__setattr__(config, "block_size", 5)
    object.__setattr__(config, "silence_threshold", 0.1)
    object.__setattr__(config, "wake_window_seconds", 0.2)

    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(time, "monotonic", _counting_monotonic())

    listener = _make_listener(config)
    listener._stream = FakeStream([np.full((5,), 0.5, dtype="float32")] * 20)
    recognizer = FailingWakeRecognizer(listener, failures=3)
    listener._recognizer = recognizer

    assert listener.listen_for_wake() is False
    assert sleeps == pytest.approx([0.5, 1.0, 2.0, 4.0])


def test_wake_detects_phrase(config):
    object.__setattr__(config, "sample_rate", 10)
    object.__setattr__(config, "block_size", 5)
    object.__setattr__(config, "silence_threshold", 0.1)
    object.__setattr__(config, "wake_window_seconds", 0.2)

    class WakeRecognizer:
        def transcribe_wake_window(self, path):
            return "Hey Ultron, sir"

    listener = _make_listener(config, WakeRecognizer())
    listener._stream = FakeStream([np.full((5,), 0.5, dtype="float32")] * 12)
    assert listener.listen_for_wake() is True


def test_wake_silence_skips_transcription(config):
    object.__setattr__(config, "sample_rate", 10)
    object.__setattr__(config, "block_size", 5)
    object.__setattr__(config, "silence_threshold", 0.9)
    object.__setattr__(config, "wake_window_seconds", 0.2)

    class ExplodingRecognizer:
        def transcribe_wake_window(self, path):
            raise AssertionError("must not be called for silence")

    listener = _make_listener(config, ExplodingRecognizer())
    listener._stream = FakeStream([_zero_block(5)] * 12)
    listener.request_stop()
    assert listener.listen_for_wake() is False


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


def test_close_releases_stream(config):
    listener = _make_listener(config)
    stream = FakeStream([_zero_block(5)])
    listener._stream = stream
    listener.close()
    assert stream.closed
    assert listener._stream is None


# ---------------------------------------------------------------------------
# wake fuzzy matching
# ---------------------------------------------------------------------------


def test_wake_exact_substring(config):
    matched, score, reason = match_wake_phrase("Hey Ultron, sir", config)
    assert matched is True
    assert score >= config.wake_match_threshold
    assert "matched" in reason


def test_wake_fuzzy_variants(config):
    for phrase in ("hey ultra", "hey altron", "hi ultron", "okay ultron",
                   "hello ultron", "hey ultion"):
        matched, score, _ = match_wake_phrase(phrase, config)
        assert matched is True, f"{phrase!r} should match (score {score:.2f})"


def test_wake_rejects_foreign_phrase(config):
    matched, score, reason = match_wake_phrase("what time is it", config)
    assert matched is False
    assert "ultron" in reason


def test_wake_rejects_low_similarity(config):
    matched, score, reason = match_wake_phrase("ultron power mode", config)
    assert matched is False
    assert "threshold" in reason


def test_wake_threshold_respects_config(config):
    object.__setattr__(config, "wake_match_threshold", 0.95)
    matched, score, _ = match_wake_phrase("hey ultra, sir", config)
    assert matched is False
    assert score < 0.95


def test_wake_ignores_punctuation_capitalization(config):
    matched, _, _ = match_wake_phrase("HEY!!! ULTRON :)", config)
    assert matched is True
