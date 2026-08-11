"""Shared fixtures for the Ultron test suite.

All tests run against temporary paths and in-memory-ish resources so no
real microphone, network, or API key is ever used.
"""

from __future__ import annotations

import logging

import pytest

from ultron.config import Config
from ultron.memory import MemoryStore


def make_config(tmp_path, **overrides) -> Config:
    """Build a Config pointed at temporary directories.

    The frozen dataclass is constructed with defaults, then the derived
    paths and any overrides are forced via object.__setattr__.
    """
    cfg = Config()
    object.__setattr__(cfg, "db_path", tmp_path / "ultron_memory.db")
    object.__setattr__(cfg, "log_dir", tmp_path / "logs")
    object.__setattr__(cfg, "cache_dir", tmp_path / "assets" / "cache")
    object.__setattr__(cfg, "screenshot_dir", tmp_path / "logs" / "screenshots")
    for key, value in overrides.items():
        object.__setattr__(cfg, key, value)
    for directory in (cfg.log_dir, cfg.cache_dir, cfg.screenshot_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return cfg


@pytest.fixture
def config(tmp_path):
    """A Config with all paths redirected under tmp_path."""
    return make_config(tmp_path)


@pytest.fixture
def memory(config):
    """A MemoryStore backed by a temporary database."""
    store = MemoryStore(config.db_path, logging.getLogger("ultron.memory"))
    yield store
    store.close()


@pytest.fixture
def silent_logging():
    """Route ultron loggers to a quiet handler for the duration."""
    root = logging.getLogger("ultron")
    original_level = root.level
    handler = logging.NullHandler()
    root.addHandler(handler)
    root.setLevel(logging.CRITICAL)
    yield root
    root.removeHandler(handler)
    root.setLevel(original_level)
