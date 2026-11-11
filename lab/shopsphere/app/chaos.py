"""Fault injection, shared across services through Redis so one API controls the whole system.

Each service reads `chaos:<service>` (cached for 1s) and applies it in middleware and DB calls.
Faults: added latency (+ jitter), error rate, slow DB queries, CPU burn, dependency down."""

from __future__ import annotations

import asyncio
import json
import random
import time

from pydantic import BaseModel, Field

SERVICES = ("shop", "payments")


class ChaosConfig(BaseModel):
    latency_ms: int = Field(0, ge=0, le=30_000, description="fixed latency added to every /api request")
    jitter_ms: int = Field(0, ge=0, le=30_000, description="extra random latency 0..jitter_ms")
    error_rate: float = Field(0.0, ge=0, le=1, description="fraction of /api requests that fail with HTTP 500")
    slow_db_ms: int = Field(0, ge=0, le=30_000, description="pg_sleep added to DB queries")
    cpu_burn_ms: int = Field(0, ge=0, le=5_000, description="busy-loop per request (saturates the event loop)")
    down: bool = Field(False, description="service answers every /api request with 503")
    routes: list[str] = Field(default_factory=list, description="only affect these path prefixes (empty = all)")

    def active(self) -> bool:
        return self != ChaosConfig(routes=self.routes)

    def applies_to(self, path: str) -> bool:
        return not self.routes or any(path.startswith(r) for r in self.routes)


SCENARIOS: dict[str, dict[str, ChaosConfig]] = {
    "reset": {s: ChaosConfig() for s in SERVICES},
    "checkout-latency": {"shop": ChaosConfig(latency_ms=900, jitter_ms=600, routes=["/api/checkout"])},
    "payments-outage": {"payments": ChaosConfig(down=True)},
    "payments-flaky": {"payments": ChaosConfig(error_rate=0.3, latency_ms=200, jitter_ms=400)},
    "slow-db": {"shop": ChaosConfig(slow_db_ms=400)},
    "cpu-spike": {"shop": ChaosConfig(cpu_burn_ms=40)},
    "error-storm": {"shop": ChaosConfig(error_rate=0.25)},
    "search-degraded": {"shop": ChaosConfig(latency_ms=1200, error_rate=0.1, routes=["/api/search"])},
}


class ChaosStore:
    def __init__(self, redis, service: str, ttl_s: float = 1.0) -> None:
        self.redis, self.service, self.ttl_s = redis, service, ttl_s
        self._cached: ChaosConfig = ChaosConfig()
        self._at = 0.0

    async def get(self, service: str | None = None) -> ChaosConfig:
        if service and service != self.service:
            raw = await self.redis.get(f"chaos:{service}")
            return ChaosConfig.model_validate_json(raw) if raw else ChaosConfig()
        if time.monotonic() - self._at > self.ttl_s:
            try:
                raw = await self.redis.get(f"chaos:{self.service}")
                self._cached = ChaosConfig.model_validate_json(raw) if raw else ChaosConfig()
            except Exception:  # chaos control plane must never take the app down
                pass
            self._at = time.monotonic()
        return self._cached

    async def set(self, service: str, cfg: ChaosConfig) -> None:
        await self.redis.set(f"chaos:{service}", cfg.model_dump_json())
        self._at = 0.0

    async def all(self) -> dict[str, dict]:
        return {s: json.loads((await self.get(s if s != self.service else None)).model_dump_json()) for s in SERVICES}


async def apply_request_faults(cfg: ChaosConfig) -> int | None:
    """Returns an HTTP status to fail with, or None. Latency is async (doesn't block the loop); CPU burn does."""
    if cfg.down:
        return 503
    delay = cfg.latency_ms + (random.randint(0, cfg.jitter_ms) if cfg.jitter_ms else 0)
    if delay:
        await asyncio.sleep(delay / 1000)
    if cfg.cpu_burn_ms:
        end = time.perf_counter() + cfg.cpu_burn_ms / 1000
        while time.perf_counter() < end:
            pass
    if cfg.error_rate and random.random() < cfg.error_rate:
        return 500
    return None
