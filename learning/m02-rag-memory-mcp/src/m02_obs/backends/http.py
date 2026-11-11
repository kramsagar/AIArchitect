"""One resilient HTTP client per backend: timeout on every call, retries with jittered backoff for idempotent reads,
a circuit breaker so a dead backend fails fast, and a short TTL cache so N agents asking the same question cost
one upstream query. All built from the M1 primitives."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from m01_agent.errors import ToolError, TransientToolError
from m01_agent.resilience import CircuitBreaker, RetryPolicy, TTLCache, retry_call


class BackendClient:
    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        timeout_s: float = 5.0,
        max_retries: int = 2,
        cache_ttl_s: float = 0.0,
        auth: tuple[str, str] | None = None,
        verify: bool = True,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ) -> None:
        self.name = name
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout_s, auth=auth, verify=verify, transport=transport
        )
        self.retry = RetryPolicy(max_retries=max_retries, base_delay_s=0.2)
        self.breaker = CircuitBreaker(failure_threshold=5, reset_timeout_s=30.0)
        self.cache = TTLCache(cache_ttl_s) if cache_ttl_s > 0 else None
        self._sleep = sleep

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = self.http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise TransientToolError(f"{self.name}: timed out ({exc.__class__.__name__})") from exc
        except httpx.TransportError as exc:
            raise TransientToolError(f"{self.name}: unreachable at {self.http.base_url} ({exc})") from exc
        if resp.status_code in (429, 502, 503, 504):
            raise TransientToolError(f"{self.name}: HTTP {resp.status_code}")
        if resp.status_code in (401, 403):
            raise ToolError(f"{self.name}: authentication failed (HTTP {resp.status_code}); check credentials")
        if resp.status_code >= 400:
            raise ToolError(f"{self.name}: HTTP {resp.status_code}: {resp.text[:300]}")
        return resp

    def request(self, method: str, path: str, *, cache: bool = True, **kwargs: Any) -> httpx.Response:
        key = (method, path, json.dumps(kwargs, sort_keys=True, default=str))
        if cache and self.cache is not None and (hit := self.cache.get(key)) is not None:
            return hit
        resp, _ = retry_call(
            lambda: self.breaker.call(lambda: self._send(method, path, **kwargs)), self.retry, sleep=self._sleep
        )
        if cache and self.cache is not None:
            self.cache.put(key, resp)
        return resp

    def get_json(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs).json()
