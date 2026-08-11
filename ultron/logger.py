"""Logging setup for Ultron.

Provides a single point of configuration: a console handler plus a
rotating file handler writing into ``logs/ultron.log``. Loggers are
obtained with ``logging.getLogger("ultron.<component>")`` and carry no
global application state.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONSOLE_FORMAT = "%(asctime)s | %(levelname)-7s | [%(ultron_tag)s] | %(message)s"
_FILE_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%H:%M:%S"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3

_ROOT_LOGGER = "ultron"

# Maps a logger name (or its first component) to a console tag.
_TAG_BY_COMPONENT = {
    "": "INFO",
    "app": "BOOT",
    "assistant": "BRAIN",
    "config": "CFG",
    "diagnostics": "DIAG",
    "events": "EVENT",
    "listener": "MIC",
    "llm": "LLM",
    "memory": "MEMORY",
    "monitoring": "METRICS",
    "ollama": "OLLAMA",
    "openrouter": "OPENROUTER",
    "reasoning": "REASON",
    "router": "ROUTER",
    "self_improve": "AI",
    "speaker": "SPEAKER",
    "speech": "STT",
    "tools": "TOOLS",
    "tts": "TTS",
    "ui": "UI",
    "voice": "VOICE",
    "wake": "WAKE",
}


class _TaggedFormatter(logging.Formatter):
    """Formatter that injects a ``[ultron_tag]`` attribute per record."""

    def format(self, record: logging.LogRecord) -> str:
        name = record.name or ""
        component = name.split(".")[1] if name.startswith("ultron.") else ""
        record.ultron_tag = _TAG_BY_COMPONENT.get(component, "INFO")
        return super().format(record)


def _as_level(level: str) -> int:
    """Convert a level name to its numeric value, defaulting to INFO."""
    return getattr(logging, level.upper(), logging.INFO)


def configure_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    """Configure Ultron logging and return the root logger.

    Deterministic: any pre-existing handlers (stale or foreign, e.g.
    pytest capture handlers) are closed and removed first, then exactly
    a console and a rotating file handler are attached. Repeated calls
    never stack handlers.

    Args:
        log_dir: Directory that will receive ``ultron.log``.
        level: Logging level name (``DEBUG``, ``INFO``, ...).

    Returns:
        The configured ``ultron`` root logger.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_ROOT_LOGGER)
    logger.setLevel(_as_level(level))
    logger.propagate = False

    for handler in list(logger.handlers):
        try:
            handler.close()
        except Exception as exc:
            logging.getLogger("ultron.config").debug(
                "Failed to close stale handler %r: %s", handler, exc
            )
        logger.removeHandler(handler)

    console = logging.StreamHandler()
    console.setLevel(_as_level(level))
    console.setFormatter(
        _TaggedFormatter(_CONSOLE_FORMAT, datefmt=_DATE_FORMAT)
    )

    file_handler = RotatingFileHandler(
        log_dir / "ultron.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT))

    logger.addHandler(console)
    logger.addHandler(file_handler)

    return logger


def close_logging(logger: logging.Logger | None = None) -> None:
    """Close all handlers of the Ultron root logger.

    Args:
        logger: The root logger to close; defaults to ``ultron``.
    """
    target = logger or logging.getLogger(_ROOT_LOGGER)
    for handler in list(target.handlers):
        handler.close()
        target.removeHandler(handler)
