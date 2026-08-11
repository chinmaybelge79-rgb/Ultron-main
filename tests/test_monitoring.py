"""Tests for the monitoring/telemetry module."""

from __future__ import annotations

import json
import threading
import time

from ultron.monitoring import Metrics, get_metrics, reset_default_metrics


def _fresh() -> Metrics:
    return Metrics()


def test_increment_and_snapshot():
    m = _fresh()
    m.increment("commands")
    m.increment("commands")
    m.increment("errors", 3)
    snapshot = m.snapshot()
    assert snapshot["counters"]["commands"] == 2
    assert snapshot["counters"]["errors"] == 3
    assert snapshot["uptime_s"] >= 0.0
    assert snapshot["started_at"]


def test_timer_records_latency():
    m = _fresh()
    with m.timer("llm.chat"):
        time.sleep(0.01)
    stats = m.snapshot()["histograms"]["llm.chat"]
    assert stats["count"] == 1
    assert stats["min"] >= 0.01
    assert stats["max"] == stats["min"]
    assert stats["mean"] >= 0.01


def test_histogram_percentiles():
    m = _fresh()
    for i in range(100):
        m.observe("lat", (i + 1) / 100.0)
    stats = m.snapshot()["histograms"]["lat"]
    assert stats["count"] == 100.0
    assert abs(stats["p50"] - 0.50) < 0.02
    assert abs(stats["p95"] - 0.96) < 0.02
    assert abs(stats["p99"] - 1.0) < 0.02
    assert abs(stats["min"] - 0.01) < 0.001
    assert abs(stats["max"] - 1.0) < 0.001


def test_observe_ignores_invalid_values():
    m = _fresh()
    m.observe("lat", -1.0)
    m.observe("lat", 0.0)
    m.observe("lat", float("nan"))
    assert m.snapshot()["histograms"] == {}


def test_set_gauge():
    m = _fresh()
    m.set_gauge("rss_mb", 123.45)
    m.set_gauge("rss_mb", 200.0)
    assert m.snapshot()["gauges"]["rss_mb"] == 200.0


def test_ring_buffer_is_bounded():
    m = _fresh()
    for _ in range(600):
        m.observe("lat", 1.0)
    stats = m.snapshot()["histograms"]["lat"]
    assert stats["count"] == 512.0  # _RING_MAXLEN


def test_snapshot_json_serializable():
    m = _fresh()
    m.increment("commands")
    with m.timer("llm.chat"):
        pass
    m.set_gauge("cpu_pct", 4.5)
    json.dumps(m.snapshot())  # must not raise


def test_summary_text_contains_counters():
    m = _fresh()
    m.increment("commands", 3)
    text = m.summary_text()
    assert "commands=3" in text
    assert "uptime" in text


def test_thread_safety():
    m = _fresh()
    threads = [
        threading.Thread(target=lambda: [m.increment("x") for _ in range(200)])
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert m.snapshot()["counters"]["x"] == 1600


def test_shared_default_collector():
    reset_default_metrics()
    a = get_metrics()
    b = get_metrics()
    a.increment("shared")
    assert b.snapshot()["counters"]["shared"] == 1
    reset_default_metrics()
