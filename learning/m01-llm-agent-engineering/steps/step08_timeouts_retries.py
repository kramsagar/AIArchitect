"""Step 8 - timeouts and retries. Concepts: a hard time budget per call, retry ONLY transient errors,
exponential backoff with full jitter, bounded attempts.

Run:  python steps/step08_timeouts_retries.py
"""

import random
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from functools import partial

from common import client
from step03_tool_schema import HEALTH_TOOL, get_service_health
from step05_agent_loop import run_agent
from step06_two_tools import CALC_TOOL, SYSTEM6
from step07_tool_errors import TransientError, safe_execute

_POOL = ThreadPoolExecutor(max_workers=8)


def with_timeout(fn, timeout_s: float):
    """Stop WAITING after timeout_s. (Python cannot kill the thread; real clients must also pass a timeout down.)"""
    future = _POOL.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeout:
        raise TransientError(f"timed out after {timeout_s}s") from None


def backoff(attempt: int, base_s: float = 0.2, cap_s: float = 2.0) -> float:
    """Full jitter: random in [0, base * 2^attempt]. Spreads retries out so clients do not stampede."""
    return random.uniform(0, min(cap_s, base_s * 2**attempt))


def retry(fn, max_retries: int = 2, sleep=time.sleep):
    for attempt in range(max_retries + 1):
        try:
            return fn(), attempt + 1
        except TransientError as exc:
            if attempt == max_retries:
                raise
            delay = backoff(attempt)
            print(f"      attempt {attempt + 1} failed ({exc}); retrying in {delay:.2f}s")
            sleep(delay)


class FlakyMetrics:
    """Pretends to be a remote metrics API: the first `fail_first` calls return 503, each call takes `latency_s`."""

    def __init__(self, fail_first: int = 2, latency_s: float = 0.05) -> None:
        self.fail_first, self.latency_s, self.calls = fail_first, latency_s, 0

    def __call__(self, args):
        self.calls += 1
        time.sleep(self.latency_s)
        if self.calls <= self.fail_first:
            raise TransientError("HTTP 503 from metrics API")
        return get_service_health(args)


def resilient_run(tool, args, timeout_s: float = 1.0, max_retries: int = 2):
    result, attempts = retry(lambda: with_timeout(lambda: tool.fn(args), timeout_s), max_retries)
    return result


def main() -> None:
    args = HEALTH_TOOL.args_model(service="checkout-api")
    print("A) backend fails twice, then works:")
    flaky = FlakyMetrics(fail_first=2)  # ONE backend instance: it remembers how many calls it has seen
    result, attempts = retry(lambda: with_timeout(lambda: flaky(args), 1.0))
    print(f"   success after {attempts} attempts, p99_ms={result['p99_ms']}")

    print("B) backend is too slow (2s) for a 0.3s budget:")
    slow = FlakyMetrics(0, latency_s=2.0)
    try:
        retry(lambda: with_timeout(lambda: slow(args), 0.3), max_retries=1)
    except TransientError as exc:
        print(f"   gave up: {exc}")

    print("\nC) agent with a flaky metrics backend (fails twice first):")
    flaky_health = type(HEALTH_TOOL)(HEALTH_TOOL.name, HEALTH_TOOL.description, HEALTH_TOOL.args_model, FlakyMetrics(2))
    tools = {t.name: t for t in (flaky_health, CALC_TOOL)}
    execute = partial(safe_execute, run=resilient_run)
    print("\n" + run_agent(client(), "Is checkout-api healthy?", tools=tools, system=SYSTEM6, execute=execute))


if __name__ == "__main__":
    main()
