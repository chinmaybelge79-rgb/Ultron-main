"""Tests for the Day 1 headless daemon and its single-instance lock."""

from __future__ import annotations

import logging
import threading
import time

import pytest

from tests.conftest import make_config
from ultron.daemon import (
    AutonomyLoop,
    ProbeLoop,
    SingleInstanceLock,
    UltronDaemon,
    VoiceLoop,
)


class _Log(logging.Logger):
    def __init__(self, name):
        super().__init__(name)


@pytest.fixture
def daemon_config(tmp_path):
    """A config whose project_dir points at tmp_path for the sentinel file."""
    return make_config(tmp_path, project_dir=tmp_path)


def test_single_instance_lock_second_acquire_fails(tmp_path):
    lock = SingleInstanceLock(tmp_path / "ultron.lock")
    assert lock.acquire() is True
    other = SingleInstanceLock(tmp_path / "ultron.lock")
    assert other.acquire() is False
    other.release()
    lock.release()
    # After release a new acquisition succeeds.
    again = SingleInstanceLock(tmp_path / "ultron.lock")
    assert again.acquire() is True
    again.release()


def test_disabled_sentinel_prevents_start(daemon_config, tmp_path):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "DISABLED").touch()
    logger = logging.getLogger("ultron.test")
    daemon = UltronDaemon(daemon_config, logger)
    assert daemon.start() == 0
    assert daemon._loops == []
    daemon.shutdown()


def test_daemon_starts_three_loops_and_stops(daemon_config):
    logger = logging.getLogger("ultron.test")
    daemon = UltronDaemon(daemon_config, logger)
    assert daemon.start() == 0
    names = {loop.name for loop in daemon._loops}
    assert names == {"voice", "probe", "autonomy"}
    assert len(daemon._loops) == 3
    daemon.request_stop()
    daemon.shutdown()


def test_loop_exception_is_isolated(daemon_config):
    """A raising run_once in one loop must not take down sibling loops."""
    logger = logging.getLogger("ultron.test")
    stop = threading.Event()

    class BoomLoop(VoiceLoop):
        name = "boom"

        def run_once(self):
            raise RuntimeError("boom")

    loop = BoomLoop(daemon_config, logger, stop, interval=0.01)
    loop.start()
    time.sleep(0.05)
    # Thread still alive despite the repeated exceptions.
    assert loop._thread is not None and loop._thread.is_alive()
    stop.set()
    loop._thread.join(timeout=1.0)
    assert not loop._thread.is_alive()


def test_stub_loops_are_callable(daemon_config):
    logger = logging.getLogger("ultron.test")
    stop = threading.Event()
    for loop_cls in (VoiceLoop, ProbeLoop, AutonomyLoop):
        loop = loop_cls(daemon_config, logger, stop)
        loop.run_once()  # empty-but-callable per Day 1
