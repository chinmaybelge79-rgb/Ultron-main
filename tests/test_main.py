"""Main loop tests: scripted sessions, error limits, logging lifecycle."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ultron.app import UltronApp, _signal_handler
from ultron.config import Config
from ultron.logger import close_logging, configure_logging
from ultron.utils import ConfigError, UltronError


@pytest.fixture(autouse=True)
def _clean_ultron_logger():
    """Reset the global ultron logger before and after every test."""
    close_logging()
    yield
    close_logging()


class FakeSpeaker:
    def __init__(self):
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)


class FakeListener:
    def __init__(self, wake_results=None, commands=None):
        self._wake = list(wake_results or [])
        self._commands = list(commands or [])
        self.stop_called = False
        self.close_called = False

    def listen_for_wake(self):
        if self._wake:
            return self._wake.pop(0)
        return False

    def record_command(self):
        if self._commands:
            return self._commands.pop(0)
        return None

    def request_stop(self):
        self.stop_called = True

    def stop_requested(self):
        return self.stop_called

    def close(self):
        self.close_called = True


class FakeRecognizer:
    def __init__(self, texts=None):
        self._texts = list(texts or [])
        self._paths = []

    def transcribe(self, path):
        self._paths.append(path)
        if self._texts:
            return self._texts.pop(0)
        return ""


class FakeAssistant:
    def __init__(self, replies=None):
        self._replies = list(replies or [])
        self.commands = []

    def handle_command(self, text):
        self.commands.append(text)
        if self._replies:
            return self._replies.pop(0)
        return "I'm here, sir."


class ErrorListener(FakeListener):
    def __init__(self, errors=5):
        super().__init__(wake_results=[])
        self._errors = errors

    def listen_for_wake(self):
        if self._errors > 0:
            self._errors -= 1
            raise UltronError("mic failed")
        return False


def _app(config, listener=None, speaker=None, recognizer=None, assistant=None):
    app = UltronApp(config, logging.getLogger("ultron.main.test"))
    app._listener = listener or FakeListener()
    app._speaker = speaker or FakeSpeaker()
    app._recognizer = recognizer or FakeRecognizer()
    app._assistant = assistant or FakeAssistant()
    return app


def test_run_returns_zero_when_no_wake(config):
    assert _app(config).run() == 0


def test_run_shutdown_phrase(config):
    listener = FakeListener(wake_results=[True], commands=[Path("/tmp/x.wav")])
    recognizer = FakeRecognizer(texts=["goodbye"])
    speaker = FakeSpeaker()
    app = _app(config, listener, speaker, recognizer)
    assert app.run() == 0
    assert "Very well, sir." in speaker.spoken[-1]


def test_run_full_session(config):
    listener = FakeListener(
        wake_results=[True, False],
        commands=[Path("/tmp/a.wav")],
    )
    recognizer = FakeRecognizer(texts=["open safari"])
    assistant = FakeAssistant(replies=["Done, sir."])
    speaker = FakeSpeaker()
    app = _app(config, listener, speaker, recognizer, assistant)
    assert app.run() == 0
    assert assistant.commands == ["open safari"]
    assert speaker.spoken == ["Yes sir?", "Done, sir."]


def test_run_empty_transcription_retries(config):
    listener = FakeListener(wake_results=[True, False], commands=[Path("/tmp/a.wav")])
    recognizer = FakeRecognizer(texts=["   "])
    speaker = FakeSpeaker()
    app = _app(config, listener, speaker, recognizer)
    assert app.run() == 0
    assert "didn't catch that" in speaker.spoken[-1]


def test_run_command_none_retries(config):
    listener = FakeListener(wake_results=[True, False], commands=[None])
    speaker = FakeSpeaker()
    app = _app(config, listener, speaker)
    assert app.run() == 0
    assert "didn't catch that" in speaker.spoken[-1]


def test_run_stops_on_request(config):
    listener = FakeListener(wake_results=[True], commands=[None])
    app = _app(config, listener)
    assert app.run() == 0


def test_run_five_consecutive_errors_exits_one(config):
    listener = ErrorListener(errors=5)
    app = _app(config, listener)
    assert app.run() == 1


def test_run_recovers_after_errors(config):
    class RecoveringListener(FakeListener):
        def __init__(self):
            super().__init__()
            self._remaining = 3

        def listen_for_wake(self):
            if self._remaining > 0:
                self._remaining -= 1
                raise UltronError("transient")
            return False

    app = _app(config, RecoveringListener())
    assert app.run() == 0


def test_is_shutdown_request(config):
    app = _app(config)
    assert app._is_shutdown_request("Goodbye")
    assert app._is_shutdown_request("shut down")
    assert app._is_shutdown_request("go to sleep")
    assert not app._is_shutdown_request("good day sir")


def test_request_stop_propagates(config):
    listener = FakeListener()
    app = _app(config, listener)
    app.request_stop()
    assert listener.stop_called


def test_shutdown_closes_resources(config):
    listener = FakeListener()
    app = _app(config, listener)
    app.shutdown()
    assert listener.close_called


# ---------------------------------------------------------------------------
# main() entry points without hardware
# ---------------------------------------------------------------------------


def test_main_runs_twice_without_handler_leak(config, monkeypatch):
    monkeypatch.setattr(Config, "from_env", staticmethod(lambda: config))
    monkeypatch.setattr("ultron.app.UltronApp.build", lambda self: None)
    monkeypatch.setattr("ultron.app.UltronApp.run", lambda self: 0)
    from ultron.app import main

    assert main([]) == 0
    first_handlers = list(logging.getLogger("ultron").handlers)
    assert main([]) == 0
    second_handlers = list(logging.getLogger("ultron").handlers)
    assert len(second_handlers) == len(first_handlers)


def test_main_returns_two_on_config_error(monkeypatch):
    def broken_from_env():
        raise ConfigError("bad config")

    monkeypatch.setattr(Config, "from_env", staticmethod(broken_from_env))
    from ultron.app import main

    assert main([]) == 2


def test_main_returns_one_on_build_error(config, monkeypatch):
    from ultron.app import main

    monkeypatch.setattr(Config, "from_env", staticmethod(lambda: config))

    def broken_build(self):
        raise UltronError("startup exploded")

    monkeypatch.setattr("ultron.app.UltronApp.build", broken_build)
    assert main([]) == 1


def test_main_signal_handler_requests_stop(config):
    app = _app(config)
    handler = _signal_handler(app)
    with pytest.raises(KeyboardInterrupt):
        handler(2, None)
    assert app._listener.stop_called


def test_configure_logging_idempotent(tmp_path):
    from logging.handlers import RotatingFileHandler

    logger = configure_logging(tmp_path)
    configure_logging(tmp_path)
    configure_logging(tmp_path)
    handlers = list(logger.handlers)
    assert len(handlers) == 2
    assert len([h for h in handlers if isinstance(h, RotatingFileHandler)]) == 1


def test_configure_logging_creates_file(tmp_path):
    logger = configure_logging(tmp_path)
    assert (tmp_path / "ultron.log").exists()
    assert any(handler.level == logging.DEBUG for handler in logger.handlers)


def test_logger_usable_after_close_and_reconfigure(tmp_path):
    logger = configure_logging(tmp_path)
    close_logging(logger)
    assert logger.handlers == []
    logger2 = configure_logging(tmp_path)
    assert len(logger2.handlers) == 2


def test_rotating_handler_configured(tmp_path):
    from logging.handlers import RotatingFileHandler

    logger = configure_logging(tmp_path)
    rotating = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(rotating) == 1
    assert rotating[0].backupCount == 3
