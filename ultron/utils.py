"""Shared utilities for Ultron.

Contains the structured exception hierarchy, the retry decorator,
network connectivity probing, and text helpers used across modules.
"""

from __future__ import annotations

import functools
import logging
import random
import re
import socket
import time
import unicodedata
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Structured exceptions
# ---------------------------------------------------------------------------


class UltronError(Exception):
    """Base class for all errors raised by Ultron."""


class ConfigError(UltronError):
    """Raised when the configuration is missing or invalid."""


class AudioError(UltronError):
    """Raised when the microphone cannot be opened or read."""


class TranscriptionError(UltronError):
    """Raised when speech-to-text fails."""


class LLMError(UltronError):
    """Raised when the language model backend fails."""


class LLMRetryableError(LLMError):
    """Raised for transient LLM failures (rate limits, 5xx, timeouts)."""


class TTSError(UltronError):
    """Raised when text-to-speech synthesis or playback fails."""


class ToolError(UltronError):
    """Raised when a tool cannot complete its work."""


class MemoryStoreError(UltronError):
    """Raised when the SQLite memory store fails."""


class AgentError(UltronError):
    """Raised when an agent encounters an unrecoverable failure."""


class ReasoningError(UltronError):
    """Raised when the reasoning engine cannot proceed."""


class EmbeddingError(UltronError):
    """Raised when embedding generation fails."""


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------


def retry(
    attempts: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    logger: logging.Logger | None = None,
    jitter: float = 0.0,
) -> Callable[[F], F]:
    """Decorator that retries a callable with exponential backoff.

    Args:
        attempts: Maximum number of attempts (must be >= 1).
        base_delay: Delay before the first retry, in seconds.
        backoff: Multiplier applied to the delay after each attempt.
        exceptions: Exception types that trigger a retry.
        logger: Logger for retry messages; defaults to the module logger.
        jitter: Maximum extra random delay (seconds) added to each wait.

    Returns:
        A decorator wrapping the callable with retry logic.
    """

    def decorator(func: F) -> F:
        module_logger = logging.getLogger(func.__module__)
        log = logger or module_logger

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = base_delay
            last_error: BaseException | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # type: ignore[misc]
                    last_error = exc
                    if attempt >= attempts:
                        break
                    wait = delay
                    if jitter > 0.0:
                        wait += random.uniform(0.0, jitter)
                    log.warning(
                        "%s failed on attempt %d/%d: %s. Retrying in %.1fs...",
                        getattr(func, "__qualname__", func.__name__),
                        attempt,
                        attempts,
                        exc,
                        wait,
                    )
                    time.sleep(wait)
                    delay *= backoff
            assert last_error is not None
            raise last_error

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def is_online(host: str = "8.8.8.8", port: int = 53, timeout: float = 2.0) -> bool:
    """Probe connectivity by opening a TCP connection.

    Args:
        host: Host to probe (default: a public DNS server).
        port: Port to connect to.
        timeout: Connection timeout in seconds.

    Returns:
        True if the connection succeeded, False otherwise.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[^\w\s]")
_MARKDOWN_RE = re.compile(r"[*_#`>\[\]()]")
_LINK_RE = re.compile(r"https?://\S+")


def normalize(text: str) -> str:
    """Normalize text for phrase matching.

    Lowercases, strips accents and punctuation, and collapses whitespace.

    Args:
        text: Raw text.

    Returns:
        Normalized text safe for substring comparison.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    cleaned = _PUNCTUATION_RE.sub(" ", ascii_only.lower())
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def clean_for_speech(text: str) -> str:
    """Strip markdown formatting so text is spoken cleanly.

    Args:
        text: Assistant reply text.

    Returns:
        Plain text suitable for speech synthesis.
    """
    if not text:
        return ""
    cleaned = _MARKDOWN_RE.sub(" ", text)
    cleaned = _LINK_RE.sub("link", cleaned)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def truncate(text: str, limit: int = 4000) -> str:
    """Truncate text to a maximum length with an ellipsis marker.

    Args:
        text: Text to truncate.
        limit: Maximum number of characters to keep.

    Returns:
        The truncated text.
    """
    if len(text) <= limit:
        return text
    return text[: limit - 4].rstrip() + " ..."
