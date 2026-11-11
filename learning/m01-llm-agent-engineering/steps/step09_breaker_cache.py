"""Step 9 - circuit breaker + cache. Concepts: stop hammering a dependency that keeps failing (fail fast),
serve repeated identical reads from memory (lower latency and load at high TPS).

Run:  python steps/step09_breaker_cache.py           (offline demo)
      python steps/step09_breaker_cache.py --agent   (plus an agent run)
"""

import sys
import time
from collections import defaultdict
from functools import partial

from common import client
from step03_tool_schema import HEALTH_TOOL
from step05_agent_loop import run_agent
from step06_two_tools import CALC_TOOL, SYSTEM6
from step07_tool_errors import ToolError, TransientError, safe_execute
from step08_timeouts_retries import FlakyMetrics, resilient_run


class CircuitOpen(ToolError):
    pass


class CircuitBreaker:
    """closed -> `threshold` failures in a row -> open (fail fast) -> after `reset_s` one trial call -> closed/open."""

    def __init__(self, threshold: int = 3, reset_s: float = 10.0, clock=time.monotonic) -> None:
        self.threshold, self.reset_s, self.clock = threshold, reset_s, clock
        self.failures, self.opened_at = 0, None

    def call(self, fn):
        if self.opened_at is not None and self.clock() - self.opened_at < self.reset_s:
            raise CircuitOpen("circuit open: dependency keeps failing, not calling it")
        try:
            result = fn()
        except TransientError:
            self.failures += 1
            if self.failures >= self.threshold or self.opened_at is not None:
                self.opened_at = self.clock()
            raise
        self.failures, self.opened_at = 0, None
        return result


class TTLCache:
    def __init__(self, ttl_s: float = 5.0, clock=time.monotonic) -> None:
        self.ttl_s, self.clock, self.data = ttl_s, clock, {}

    def get(self, key):
        hit = self.data.get(key)
        return hit[1] if hit and self.clock() - hit[0] < self.ttl_s else None

    def put(self, key, value) -> None:
        self.data[key] = (self.clock(), value)


class Protected:
    """The full call path for one tool call: cache -> breaker -> retry -> timeout -> tool."""

    def __init__(self, max_retries: int = 2) -> None:
        self.breakers = defaultdict(CircuitBreaker)
        self.cache = TTLCache()
        self.max_retries = max_retries

    def __call__(self, tool, args):
        key = (tool.name, args.model_dump_json())
        if (hit := self.cache.get(key)) is not None:
            return hit
        result = self.breakers[tool.name].call(lambda: resilient_run(tool, args, max_retries=self.max_retries))
        self.cache.put(key, result)
        return result


def main() -> None:
    args = HEALTH_TOOL.args_model(service="checkout-api")
    down = type(HEALTH_TOOL)(HEALTH_TOOL.name, "", HEALTH_TOOL.args_model, FlakyMetrics(fail_first=10**9))
    run = Protected(max_retries=0)
    print("A) metrics API is down; 5 calls in a row:")
    for i in range(1, 6):
        started = time.perf_counter()
        try:
            run(down, args)
        except ToolError as exc:
            print(f"   call {i}: {type(exc).__name__}: {exc}  ({(time.perf_counter() - started) * 1000:.0f} ms)")

    print("B) healthy API; same call twice:")
    healthy = type(HEALTH_TOOL)(HEALTH_TOOL.name, "", HEALTH_TOOL.args_model, FlakyMetrics(0, latency_s=0.2))
    run = Protected()
    for i in (1, 2):
        started = time.perf_counter()
        run(healthy, args)
        print(
            f"   call {i}: {(time.perf_counter() - started) * 1000:.0f} ms (backend calls so far: {healthy.fn.calls})"
        )

    if "--agent" in sys.argv:
        tools = {t.name: t for t in (HEALTH_TOOL, CALC_TOOL)}
        execute = partial(safe_execute, run=Protected())
        print("\n" + run_agent(client(), "Can checkout-api handle 2x traffic?", tools, SYSTEM6, execute))


if __name__ == "__main__":
    main()
