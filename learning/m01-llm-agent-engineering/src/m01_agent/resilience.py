"""Resilience primitives used by the agent runtime: retry with backoff + jitter, timeouts, deadlines,
circuit breaker and a TTL cache. Each one is small on purpose so it can be read in a minute."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, TypeVar

from .errors import ToolError, ToolTimeoutError, TransientToolError

T = TypeVar("T")

_EXECUTOR = ThreadPoolExecutor(max_workers=64, thread_name_prefix="tool")


def call_with_timeout(fn: Callable[[], T], timeout_s: float) -> T:
    """Run `fn` with a hard wall-clock budget.

    Python threads cannot be killed, so a timed-out call keeps running in the background; the caller just stops
    waiting. Real tools should also pass the timeout down (HTTP client timeout, DB statement timeout)."""
    future = _EXECUTOR.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeout as exc:
        future.cancel()
        raise ToolTimeoutError(f"timed out after {timeout_s:.2f}s") from exc


def backoff_delay(attempt: int, base_s: float, max_s: float, rng: random.Random | None = None) -> float:
    """Exponential backoff with full jitter: uniform(0, min(max, base * 2**attempt)).
    Jitter de-synchronises clients so retries do not arrive as a thundering herd."""
    cap = min(max_s, base_s * (2**attempt))
    return (rng or random).uniform(0, cap)


@dataclass
class RetryPolicy:
    max_retries: int = 2
    base_delay_s: float = 0.1
    max_delay_s: float = 2.0
    retry_on: tuple[type[Exception], ...] = (TransientToolError,)


def retry_call(
    fn: Callable[[], T],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], None] = time.sleep,
    deadline: Deadline | None = None,
) -> tuple[T, int]:
    """Call `fn`, retrying retryable errors. Returns (result, attempts). Never sleeps past the deadline."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn(), attempt
        except policy.retry_on:
            if attempt > policy.max_retries:
                raise
            delay = backoff_delay(attempt - 1, policy.base_delay_s, policy.max_delay_s)
            if deadline is not None and deadline.remaining() <= delay:
                raise
            sleep(delay)


@dataclass
class Deadline:
    """An end-to-end time budget that is propagated down to every LLM and tool call."""

    budget_s: float
    started: float = field(default_factory=time.monotonic)

    def remaining(self) -> float:
        return max(0.0, self.budget_s - (time.monotonic() - self.started))

    def expired(self) -> bool:
        return self.remaining() <= 0

    def cap(self, timeout_s: float) -> float:
        return max(0.001, min(timeout_s, self.remaining()))


class CircuitOpenError(ToolError):
    error_type = "circuit_open"


class CircuitBreaker:
    """closed -> (N consecutive failures) -> open -> (cooldown) -> half_open -> success: closed / failure: open.
    While open, calls fail fast instead of piling load on an unhealthy dependency."""

    def __init__(
        self, failure_threshold: int = 5, reset_timeout_s: float = 30.0, clock: Callable[[], float] | None = None
    ):
        self.failure_threshold = failure_threshold
        self.reset_timeout_s = reset_timeout_s
        self._clock = clock or time.monotonic
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state()

    def _state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self.reset_timeout_s:
            return "half_open"
        return "open"

    def call(self, fn: Callable[[], T]) -> T:
        with self._lock:
            if self._state() == "open":
                raise CircuitOpenError("circuit open: dependency is failing, not calling it (fail fast)")
        try:
            result = fn()
        except TransientToolError:
            with self._lock:
                self._failures += 1
                if self._failures >= self.failure_threshold or self._opened_at is not None:
                    self._opened_at = self._clock()
            raise
        with self._lock:
            self._failures = 0
            self._opened_at = None
        return result


class TTLCache:
    """Tiny thread-safe TTL cache for idempotent read tools (cuts p99 latency and upstream load at high TPS)."""

    def __init__(self, ttl_s: float, max_items: int = 1024, clock: Callable[[], float] | None = None):
        self.ttl_s = ttl_s
        self.max_items = max_items
        self._clock = clock or time.monotonic
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item and self._clock() - item[0] < self.ttl_s:
                self.hits += 1
                return item[1]
            self._data.pop(key, None)
            self.misses += 1
            return None

    def put(self, key: Any, value: Any) -> None:
        with self._lock:
            if len(self._data) >= self.max_items:
                self._data.pop(next(iter(self._data)))
            self._data[key] = (self._clock(), value)
