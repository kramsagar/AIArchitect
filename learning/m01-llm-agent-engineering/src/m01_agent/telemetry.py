"""Minimal observability: structured JSON logs, spans and latency histograms with p50/p95/p99.

In production you would export the same signals with OpenTelemetry (GenAI semantic conventions) to your
tracing backend; the shape of the data (run_id, span name, duration, attributes) is what matters here."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("m01_agent")


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[str, int] = defaultdict(int)
        self.timings: dict[str, list[float]] = defaultdict(list)

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self.counters[name] += value

    def observe(self, name: str, ms: float) -> None:
        with self._lock:
            self.timings[name].append(ms)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            hist = {
                name: {
                    "count": len(v),
                    "p50_ms": round(percentile(v, 50), 2),
                    "p95_ms": round(percentile(v, 95), 2),
                    "p99_ms": round(percentile(v, 99), 2),
                    "max_ms": round(max(v), 2),
                }
                for name, v in self.timings.items()
                if v
            }
            return {"counters": dict(self.counters), "latency": hist}

    def reset(self) -> None:
        with self._lock:
            self.counters.clear()
            self.timings.clear()


METRICS = Metrics()


def log_event(event: str, **fields: Any) -> None:
    if logger.isEnabledFor(logging.INFO):
        logger.info(json.dumps({"event": event, **fields}, default=str))


@contextmanager
def span(name: str, run_id: str, **attrs: Any) -> Iterator[dict[str, Any]]:
    """Times a unit of work, records it in METRICS and emits one structured log line when it ends."""
    record: dict[str, Any] = dict(attrs)
    start = time.perf_counter()
    status = "ok"
    try:
        yield record
    except Exception as exc:
        status = f"error:{type(exc).__name__}"
        raise
    finally:
        ms = (time.perf_counter() - start) * 1000
        METRICS.observe(name, ms)
        log_event("span", span=name, run_id=run_id, span_status=status, duration_ms=round(ms, 2), **record)
