"""Mock observability backend (think Prometheus + APM) returning golden signals per service.

Fault injection knobs (latency, failure rate, fail-first-N) let you practise timeouts, retries and circuit
breaking without a real cluster."""

from __future__ import annotations

import random
import threading
import time

from ..errors import ToolError, TransientToolError
from ..schemas import SLO, ServiceHealth, ServiceHealthArgs

# service -> (tier, rps, p50, p95, p99, err%, cpu%, saturation%, replicas, slo_avail, slo_p99, deps, recent_change)
# fmt: off
_CATALOG: dict[str, tuple] = {
    "checkout-api": (
        "tier-0", 12400, 38, 140, 620, 0.42, 86, 91, 24, 99.95, 300,
        {"payments-gateway": "healthy", "inventory-db": "degraded", "redis-cart": "healthy"},
        "v2.31.0 deployed 25m ago (connection pool 50 -> 20)",
    ),
    "payments-gateway": (
        "tier-0", 3100, 55, 210, 1450, 3.8, 48, 62, 12, 99.99, 800,
        {"card-network-psp": "degraded", "fraud-scoring": "healthy"},
        None,
    ),
    "search-api": (
        "tier-1", 8800, 12, 35, 70, 0.02, 41, 38, 16, 99.9, 150,
        {"opensearch": "healthy", "redis-search": "healthy"},
        None,
    ),
    "auth-service": (
        "tier-0", 21000, 6, 15, 28, 0.01, 52, 47, 30, 99.99, 50,
        {"user-db": "healthy", "jwks-cache": "healthy"},
        None,
    ),
    "inventory-db": (
        "tier-1", 5200, 9, 40, 90, 0.15, 93, 97, 3, 99.9, 100,
        {"block-storage": "healthy"},
        "nightly reindex started 40m ago",
    ),
    "notification-worker": (
        "tier-2", 650, 120, 480, 900, 0.9, 35, 30, 4, 99.5, 2000,
        {"kafka": "healthy", "smtp-relay": "healthy"},
        None,
    ),
}
# fmt: on

KNOWN_SERVICES = tuple(_CATALOG)


class MockMetricsBackend:
    """Callable tool implementation: `ServiceHealthArgs -> ServiceHealth`."""

    def __init__(
        self,
        *,
        latency_s: float = 0.0,
        failure_rate: float = 0.0,
        fail_first_n: int = 0,
        seed: int | None = None,
    ) -> None:
        self.latency_s = latency_s
        self.failure_rate = failure_rate
        self.fail_first_n = fail_first_n
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self.calls = 0

    def __call__(self, args: ServiceHealthArgs) -> ServiceHealth:
        with self._lock:
            self.calls += 1
            n = self.calls
            flaky = self._rng.random() < self.failure_rate
        if self.latency_s:
            time.sleep(self.latency_s)
        if n <= self.fail_first_n or flaky:
            raise TransientToolError("metrics backend returned HTTP 503 (query timeout on prometheus shard)")

        key = args.service.strip().lower().replace(" ", "-")
        if key not in _CATALOG:
            raise ToolError(f"unknown service '{args.service}'. Known services: {', '.join(KNOWN_SERVICES)}")
        tier, rps, p50, p95, p99, err, cpu, sat, replicas, slo_a, slo_p99, deps, change = _CATALOG[key]
        return ServiceHealth(
            service=key,
            tier=tier,
            window_minutes=args.window_minutes,
            rps=rps,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            latency_p99_ms=p99,
            error_rate_pct=err,
            cpu_util_pct=cpu,
            saturation_pct=sat,
            replicas=replicas,
            slo=SLO(availability_pct=slo_a, latency_p99_ms=slo_p99),
            dependencies=deps,
            recent_change=change,
        )


def burn_rate(h: ServiceHealth) -> float:
    return h.error_rate_pct / (100 - h.slo.availability_pct)


def assess(h: ServiceHealth) -> tuple[str, list[str]]:
    """Deterministic SLO assessment - code decides severity, the model explains it.

    critical: p99 above the latency SLO or error-budget burn rate >= 10x (fast burn, page now)
    warning:  burn rate > 1x, saturation >= 85% or a degraded/down dependency
    ok:       everything else"""
    issues: list[str] = []
    critical = False
    burn = burn_rate(h)
    if burn >= 10:
        critical = True
        issues.append(f"error budget burning at {burn:.1f}x (fast burn)")
    elif burn > 1:
        issues.append(f"error budget burning at {burn:.1f}x")
    if h.latency_p99_ms > h.slo.latency_p99_ms:
        critical = True
        issues.append(f"p99 {h.latency_p99_ms:.0f}ms breaches the {h.slo.latency_p99_ms:.0f}ms SLO")
    if h.saturation_pct >= 85:
        issues.append(f"saturation {h.saturation_pct:.0f}% leaves little headroom for spikes")
    bad_deps = [f"{d} is {s}" for d, s in h.dependencies.items() if s != "healthy"]
    if bad_deps:
        issues.append("dependency " + ", ".join(bad_deps))
    severity = "critical" if critical else ("warning" if issues else "ok")
    return severity, issues
