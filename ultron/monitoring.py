"""Lightweight, thread-safe telemetry for Ultron.

This is the Monitoring module of the architecture. It provides a single
:class:`Metrics` object that components use to record event counts,
latency samples, and resource gauges, plus structured snapshots for log
emission and diagnostics. All data structures are bounded so a
long-running process never leaks memory.

Design notes:
    - Counter values increase monotonically within a run.
    - Latency samples are kept in a bounded ring buffer per metric and
      summarized as count/min/max/mean and p50/p95/p99 percentiles.
    - Gauges hold the last observed value (e.g. RSS in MB).
    - Everything is guarded by a single lock; overhead is negligible at
      Ultron's per-command cadence (a handful of events per second).
"""

from __future__ import annotations

import collections
import threading
import time
from datetime import datetime, timezone
from typing import Any

_RING_MAXLEN = 512


class _Histogram:
    """Bounded ring buffer of latency samples with percentile reduction."""

    __slots__ = ("_samples", "_sum", "_sum_sq", "_min", "_max")

    def __init__(self) -> None:
        self._samples: collections.deque[float] = collections.deque(
            maxlen=_RING_MAXLEN
        )
        self._sum = 0.0
        self._sum_sq = 0.0
        self._min = float("inf")
        self._max = 0.0

    def observe(self, value: float) -> None:
        self._samples.append(value)
        self._sum += value
        self._sum_sq += value * value
        if value < self._min:
            self._min = value
        if value > self._max:
            self._max = value

    def stats(self) -> dict[str, float]:
        count = len(self._samples)
        if count == 0:
            return {"count": 0.0}
        ordered = sorted(self._samples)
        mean = self._sum / count
        mean_sq = self._sum_sq / count
        std_dev = (mean_sq - mean * mean) ** 0.5 if mean_sq >= mean * mean else 0.0

        def percentile(pct: float) -> float:
            return ordered[min(count - 1, int(count * pct))]

        return {
            "count": float(count),
            "min": round(self._min, 4),
            "max": round(self._max, 4),
            "mean": round(mean, 4),
            "std_dev": round(std_dev, 4),
            "p50": round(percentile(0.50), 4),
            "p95": round(percentile(0.95), 4),
            "p99": round(percentile(0.99), 4),
        }


class _Timer:
    """Context manager that records elapsed wall time into a metric."""

    __slots__ = ("_metrics", "_name", "_started")

    def __init__(self, metrics: _Metrics, name: str) -> None:
        self._metrics = metrics
        self._name = name
        self._started = 0.0

    def __enter__(self) -> _Timer:
        self._started = time.monotonic()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._metrics.observe(self._name, time.monotonic() - self._started)


class _Metrics:
    """Collects counters, latency histograms, and gauges."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = collections.defaultdict(int)
        self._histograms: dict[str, _Histogram] = {}
        self._gauges: dict[str, float] = {}
        self._started = time.monotonic()

    def increment(self, name: str, amount: int = 1) -> None:
        """Increment a named event counter by ``amount``."""
        with self._lock:
            self._counters[name] += amount

    def observe(self, name: str, seconds: float) -> None:
        """Record a latency sample, skipping non-finite/negative values."""
        if not seconds or seconds < 0 or seconds != seconds:  # NaN guard
            return
        with self._lock:
            histogram = self._histograms.get(name)
            if histogram is None:
                histogram = _Histogram()
                self._histograms[name] = histogram
            histogram.observe(seconds)

    def set_gauge(self, name: str, value: float) -> None:
        """Record the most recent value of a resource gauge."""
        with self._lock:
            self._gauges[name] = float(value)

    def timer(self, name: str) -> _Timer:
        """Return a context manager that observes elapsed wall time."""
        return _Timer(self, name)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable summary of every tracked metric."""
        with self._lock:
            counters = dict(self._counters)
            histograms = {
                name: histogram.stats() for name, histogram in self._histograms.items()
            }
            gauges = dict(self._gauges)
            uptime = time.monotonic() - self._started
        return {
            "uptime_s": round(uptime, 2),
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "counters": counters,
            "histograms": histograms,
            "gauges": gauges,
        }

    def summary_text(self) -> str:
        """Return a compact, human-readable summary for logs/console."""
        snapshot = self.snapshot()
        counters = ", ".join(
            f"{key}={value}" for key, value in snapshot["counters"].items()
        )
        parts = [f"uptime={snapshot['uptime_s']}s", f"counters={{{counters}}}"]
        for name, stats in snapshot["histograms"].items():
            if stats["count"]:
                parts.append(
                    f"{name}: count={int(stats['count'])} "
                    f"mean={stats['mean']}s p95={stats['p95']}s"
                )
        if snapshot["gauges"]:
            gauges = ", ".join(
                f"{key}={value:.1f}" for key, value in snapshot["gauges"].items()
            )
            parts.append(f"gauges={{{gauges}}}")
        return " | ".join(parts)


# Public alias: components type their constructor argument as Metrics.
Metrics = _Metrics


# Module-level convenience factory so components can default to a shared,
# process-wide collector without globals leaking into the public API.
_default: Metrics | None = None


def get_metrics() -> Metrics:
    """Return the process-wide default :class:`Metrics` collector.

    Components accept a ``metrics`` argument that overrides this default,
    which keeps utilities optional and dependency-injection friendly.
    """
    global _default
    if _default is None:
        _default = _Metrics()
    return _default


def reset_default_metrics() -> None:
    """Clear the process-wide default collector (used in tests)."""
    global _default
    _default = None