"""Utilities tests: text helpers, connectivity probing, and retry."""

from __future__ import annotations

import socket
import time

import pytest

from ultron.utils import (
    LLMRetryableError,
    clean_for_speech,
    is_online,
    normalize,
    retry,
    truncate,
)

# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


def test_normalize_lowercases_and_collapses():
    assert normalize("  Hey   ULTRON  ") == "hey ultron"


def test_normalize_strips_punctuation():
    assert normalize("What's on my clipboard?") == "what s on my clipboard"


def test_normalize_removes_accents():
    assert normalize("café naïve") == "cafe naive"


def test_normalize_empty():
    assert normalize("") == ""
    assert normalize(None) == ""


def test_normalize_drops_emojis():
    assert normalize("hey ultron 🔥") == "hey ultron"


# ---------------------------------------------------------------------------
# clean_for_speech
# ---------------------------------------------------------------------------


def test_clean_for_speech_strips_markdown():
    assert clean_for_speech("**bold** and `code`") == "bold and code"


def test_clean_for_speech_replaces_links():
    assert clean_for_speech("see https://example.com/page now") == "see link now"


def test_clean_for_speech_collapses_whitespace():
    assert clean_for_speech("a   b\n\tc") == "a b c"


def test_clean_for_speech_empty():
    assert clean_for_speech("") == ""
    assert clean_for_speech(None) == ""


# ---------------------------------------------------------------------------
# truncate
# ---------------------------------------------------------------------------


def test_truncate_short_text_untouched():
    assert truncate("hello", 10) == "hello"


def test_truncate_long_text_ellipsis():
    out = truncate("x" * 100, 10)
    assert out.endswith("...")
    assert len(out) <= 10


def test_truncate_default_limit():
    assert len(truncate("y" * 5000)) <= 4000


# ---------------------------------------------------------------------------
# is_online
# ---------------------------------------------------------------------------


def test_is_online_success(monkeypatch):
    class FakeContext:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_connect(*args, **kwargs):
        return FakeContext()

    monkeypatch.setattr(socket, "create_connection", fake_connect)
    assert is_online() is True


def test_is_online_failure(monkeypatch):
    def fake_connect(*args, **kwargs):
        raise OSError("network unreachable")

    monkeypatch.setattr(socket, "create_connection", fake_connect)
    assert is_online() is False


# ---------------------------------------------------------------------------
# retry
# ---------------------------------------------------------------------------


def test_retry_succeeds_after_failures(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    calls = {"n": 0}

    @retry(attempts=3, base_delay=0.01)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_retry_exhausts_and_raises(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    calls = {"n": 0}

    @retry(attempts=3, base_delay=0.01)
    def always_fails():
        calls["n"] += 1
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        always_fails()
    assert calls["n"] == 3


def test_retry_respects_exception_tuple(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    calls = {"n": 0}

    @retry(attempts=3, exceptions=(LLMRetryableError,))
    def raises_plain():
        calls["n"] += 1
        raise ValueError("not retryable")

    with pytest.raises(ValueError):
        raises_plain()
    assert calls["n"] == 1


def test_retry_jitter_bounds(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    @retry(attempts=3, base_delay=1.0, backoff=2.0, jitter=0.5)
    def always_fails():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        always_fails()

    assert len(sleeps) == 2
    assert 1.0 <= sleeps[0] <= 1.5
    assert 2.0 <= sleeps[1] <= 2.5


def test_retry_single_attempt_no_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: pytest.fail("must not sleep"))
    calls = {"n": 0}

    @retry(attempts=1)
    def fails_once():
        calls["n"] += 1
        raise KeyError("boom")

    with pytest.raises(KeyError):
        fails_once()
    assert calls["n"] == 1
