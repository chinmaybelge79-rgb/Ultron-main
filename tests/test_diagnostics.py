"""Diagnostics tests: pre-flight checks, rendering, and failure detection."""

from __future__ import annotations

from dataclasses import replace

from ultron.config import Config
from ultron.diagnostics import (
    Status,
    check_api_keys,
    check_config,
    check_database,
    check_internet,
    check_mic_level,
    check_microphone,
    check_ollama,
    check_speaker,
    check_tools,
    check_whisper_model,
    has_failures,
    render_report,
    run_checks,
)


def _config(**overrides) -> Config:
    cfg = Config()
    init_fields = {f.name for f in cfg.__dataclass_fields__.values() if f.init}
    for key, value in overrides.items():
        if key in init_fields:
            cfg = replace(cfg, **{key: value})
        else:
            object.__setattr__(cfg, key, value)
    return cfg


def test_run_checks_returns_results():
    results = run_checks(_config())
    assert len(results) >= 8
    for result in results:
        assert isinstance(result.name, str)
        assert result.status in (Status.PASS, Status.WARN, Status.FAIL)
        assert isinstance(result.detail, str)


def test_has_failures(monkeypatch):
    import ultron.diagnostics as diag

    monkeypatch.setattr(
        diag, "_CHECK_FUNCTIONS", (lambda cfg: _result("forced", Status.FAIL),)
    )
    assert has_failures(run_checks(_config()))
    monkeypatch.setattr(
        diag, "_CHECK_FUNCTIONS", (lambda cfg: _result("forced", Status.PASS),)
    )
    assert not has_failures(run_checks(_config()))


def _result(name: str, status: Status, detail: str = "") -> object:
    return type("CheckResult", (), {"name": name, "status": status, "detail": detail})()


def test_render_report_summary():
    results = [
        _result("a", Status.PASS),
        _result("b", Status.WARN),
        _result("c", Status.FAIL),
    ]
    report = render_report(results)
    assert "PASS=1 FAIL=1 WARN=1" in report
    assert "[PASS]" in report
    assert "[FAIL]" in report
    assert "[WARN]" in report


def test_check_config_pass():
    assert check_config(_config()).status is Status.PASS


def test_check_api_keys_pass_warn():
    assert check_api_keys(_config()).status is Status.PASS
    cfg = _config(ollama_enabled=False, openrouter_api_key="")
    assert check_api_keys(cfg).status is Status.WARN


def test_check_ollama_disabled():
    assert check_ollama(_config(ollama_enabled=False)).status is Status.PASS


def test_check_ollama_reachable(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"models": [{"name": "llama3.1:8b"}]}

    monkeypatch.setattr(
        "ultron.diagnostics.requests.get", lambda *a, **k: FakeResponse()
    )
    assert check_ollama(_config()).status is Status.PASS


def test_check_ollama_model_missing(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"models": [{"name": "other-model:latest"}]}

    monkeypatch.setattr(
        "ultron.diagnostics.requests.get", lambda *a, **k: FakeResponse()
    )
    result = check_ollama(_config())
    assert result.status is Status.WARN
    assert "ollama pull" in result.detail


def test_check_ollama_unreachable(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr("ultron.diagnostics.requests.get", boom)
    assert check_ollama(_config()).status is Status.WARN


def test_check_internet_online(monkeypatch):
    monkeypatch.setattr(
        "ultron.diagnostics.is_online", lambda *a, **k: True
    )
    assert check_internet(_config()).status is Status.PASS


def test_check_internet_offline(monkeypatch):
    monkeypatch.setattr(
        "ultron.diagnostics.is_online", lambda *a, **k: False
    )
    assert check_internet(_config()).status is Status.WARN


def test_check_whisper_model(monkeypatch):
    monkeypatch.setattr(
        "ultron.diagnostics.whisper_model_available", lambda cfg: True
    )
    assert check_whisper_model(_config()).status is Status.PASS


def test_check_speaker(monkeypatch):
    monkeypatch.setattr("ultron.diagnostics.shutil.which", lambda name: "/usr/bin/say")
    assert check_speaker(_config()).status is Status.PASS
    monkeypatch.setattr("ultron.diagnostics.shutil.which", lambda name: None)
    assert check_speaker(_config()).status is Status.FAIL


def test_check_microphone_no_device(monkeypatch):
    class FakeSD:
        @staticmethod
        def query_devices():
            return []

    monkeypatch.setattr("ultron.diagnostics.sd", FakeSD)
    assert check_microphone(_config()).status is Status.FAIL


def test_check_microphone_with_device(monkeypatch):
    class FakeDev:
        def get(self, key, default=0):
            return 2 if key == "max_input_channels" else default

    class FakeSD:
        @staticmethod
        def query_devices():
            return [FakeDev()]

    monkeypatch.setattr("ultron.diagnostics.sd", FakeSD)
    assert check_microphone(_config()).status is Status.PASS


def _mic_stream(amplitude: float):
    """Build a fake InputStream whose read() returns a constant signal."""

    class FakeInput:
        def __init__(self, **kwargs):
            self._amp = amplitude
            self.stopped = False
            self.closed = False

        def start(self):
            pass

        def read(self, frames):
            import numpy as np

            data = (np.ones((int(frames), 1), dtype="float32") * self._amp, False)
            return data

        def stop(self):
            self.stopped = True

        def close(self):
            self.closed = True

    return FakeInput


class _ExplodingStream:
    def start(self):
        raise RuntimeError("boom")


def test_check_mic_level_silence_warns(monkeypatch):
    monkeypatch.setattr(
        "ultron.diagnostics.sd.InputStream", _mic_stream(amplitude=0.0)
    )
    result = check_mic_level(_config())
    assert result.name == "mic_level"
    assert result.status is Status.WARN
    assert "silent" in result.detail.lower()


def test_check_mic_level_audio_passes(monkeypatch):
    monkeypatch.setattr(
        "ultron.diagnostics.sd.InputStream", _mic_stream(amplitude=0.5)
    )
    result = check_mic_level(_config())
    assert result.status is Status.PASS
    assert "delivering audio" in result.detail


def test_check_mic_level_open_failure_warns(monkeypatch):
    monkeypatch.setattr("ultron.diagnostics.sd.InputStream", _ExplodingStream)
    result = check_mic_level(_config())
    assert result.status is Status.WARN


def test_check_tools_pass():
    assert check_tools(_config()).status is Status.PASS


def test_check_database_pass(tmp_path):
    cfg = _config(log_dir=tmp_path, cache_dir=tmp_path, screenshot_dir=tmp_path)
    assert check_database(cfg).status is Status.PASS


def test_diagnostics_cli_flag():
    from ultron.app import main

    assert main(["--diagnostics"]) in (0, 1)
