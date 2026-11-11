"""Step 1 - a production HTTP client for tools. Concepts: timeout, retry ONLY transient errors (5xx/connect),
fail fast on 4xx, circuit breaker, TTL cache. Reuses the primitives you built in Module 1 (m01_agent.resilience).

Run:  python steps/step01_resilient_client.py
"""

import time

import httpx
from common import LIVE, PROMETHEUS, mode
from m01_agent.errors import ToolError, TransientToolError
from m01_agent.resilience import CircuitBreaker, RetryPolicy, TTLCache, retry_call


class Backend:
    def __init__(self, base_url: str, timeout_s: float = 3.0, retries: int = 2, cache_ttl_s: float = 5.0, **httpx_kw):
        self.http = httpx.Client(base_url=base_url, timeout=timeout_s, **httpx_kw)  # ONE pooled client
        self.policy = RetryPolicy(max_retries=retries)
        self.breaker = CircuitBreaker(failure_threshold=5, reset_timeout_s=30)
        self.cache = TTLCache(cache_ttl_s)
        self.calls = 0

    def _once(self, method: str, path: str, **kw) -> httpx.Response:
        self.calls += 1
        try:
            resp = self.http.request(method, path, **kw)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientToolError(f"{type(exc).__name__} calling {path}") from exc
        if resp.status_code >= 500 or resp.status_code == 429:
            raise TransientToolError(f"HTTP {resp.status_code} from {path}")  # retryable
        if resp.status_code >= 400:
            raise ToolError(f"HTTP {resp.status_code} from {path}: {resp.text[:200]}")  # our fault: do not retry
        return resp

    def get_json(self, path: str, **params) -> dict:
        key = (path, tuple(sorted(params.items())))
        if (hit := self.cache.get(key)) is not None:
            return hit
        resp, _ = retry_call(lambda: self.breaker.call(lambda: self._once("GET", path, params=params)), self.policy)
        data = resp.json()
        self.cache.put(key, data)
        return data


def main() -> None:
    print(f"mode: {mode()}")
    if not LIVE:
        print("Start the lab (cd lab; docker compose up -d) to see real HTTP behaviour. Showing the failure path only.")
    prom = Backend(PROMETHEUS)
    if LIVE:
        for i in (1, 2):
            t = time.perf_counter()
            prom.get_json("/api/v1/query", query="shopsphere:http_requests:rate1m")
            ms = (time.perf_counter() - t) * 1000
            print(f"call {i}: {ms:.1f} ms (HTTP calls so far: {prom.calls})  <- 2nd = cache")
        try:
            prom.get_json("/api/v1/query", query="this is not promql(")
        except ToolError as exc:
            print(f"bad PromQL -> {type(exc).__name__} (no retry): {str(exc)[:90]}")
    dead = Backend("http://localhost:9", timeout_s=0.5, retries=2)  # nothing listens on port 9
    t = time.perf_counter()
    try:
        dead.get_json("/api/v1/query", query="up")
    except TransientToolError as exc:
        print(f"dead backend -> {exc} after {dead.calls} attempts, {(time.perf_counter() - t) * 1000:.0f} ms")


if __name__ == "__main__":
    main()
