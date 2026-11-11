"""Offline backends: scripted incidents with the same shapes as the live tools, so every lab, test and CI run works
without Docker. Scenarios mirror the lab's chaos scenarios."""

from __future__ import annotations

from typing import Any

from m01_agent.errors import ToolError

from .jaeger import summarize_trace
from .splunk import validate_spl

SHOP, PAY = "shopsphere-shop", "payments-service"


def _span(sid: str, parent: str | None, pid: str, op: str, ms: float, *, error: str | None = None, status: int = 200):
    tags = [{"key": "http.response.status_code", "value": status}] if op.startswith(("POST", "GET")) else []
    if error:
        tags += [{"key": "error", "value": True}, {"key": "otel.status_description", "value": error}]
    refs = [{"refType": "CHILD_OF", "spanID": parent}] if parent else []
    return {
        "spanID": sid,
        "operationName": op,
        "duration": int(ms * 1000),
        "processID": pid,
        "tags": tags,
        "references": refs,
    }


def _checkout_trace(tid: str, pay_ms: float, *, down: bool = False) -> dict[str, Any]:
    err = "payment provider unavailable" if down else None
    status = 502 if down else 200
    spans = [
        _span("a1", None, "p1", "POST /api/checkout", pay_ms + 140, error=err, status=status),
        _span("a2", "a1", "p1", "checkout.price_and_reserve", 38),
        _span("a3", "a2", "p1", "SELECT", 6),
        _span("a4", "a2", "p1", "UPDATE", 9),
        _span("a5", "a1", "p1", "POST", pay_ms + 12, error=err, status=503 if down else 200),
        _span("b1", "a5", "p2", "POST /api/payments/charge", pay_ms, error=err, status=503 if down else 200),
        _span("b2", "b1", "p2", "payment-provider.authorize", max(pay_ms - 6, 1), error=err),
        _span("a6", "a1", "p1", "INSERT", 11),
    ]
    return {"traceID": tid, "spans": spans, "processes": {"p1": {"serviceName": SHOP}, "p2": {"serviceName": PAY}}}


SCENARIOS: dict[str, dict[str, Any]] = {
    "healthy": {
        "services": {
            SHOP: {"rps": 41.3, "error_ratio_5m": 0.0004, "error_ratio_1h": 0.0003, "burn_rate_1h": 0.06, "p95_ms": 48.0, "p99_ms": 120.0},
            PAY: {"rps": 2.1, "error_ratio_5m": 0.0, "error_ratio_1h": 0.0, "burn_rate_1h": 0.0, "p95_ms": 31.0, "p99_ms": 60.0},
        },
        "checkout_slow_ratio_5m": 0.0,
        "slowest_routes_p95": [{"service": SHOP, "route": "/api/checkout", "p95_ms": 160.0}],
        "alerts": [],
        "changes": {},
        "traces": [],
        "logs": [{"service.name": SHOP, "otel.log.severity.text": "INFO", "_raw": "order placed", "trace_id": "5e1f00aa00000000000000000000beef"}],
    },
    "checkout-latency": {
        "services": {
            SHOP: {"rps": 39.8, "error_ratio_5m": 0.0021, "error_ratio_1h": 0.0012, "burn_rate_1h": 0.24, "p95_ms": 410.0, "p99_ms": 2380.0},
            PAY: {"rps": 2.0, "error_ratio_5m": 0.0, "error_ratio_1h": 0.0, "burn_rate_1h": 0.0, "p95_ms": 2050.0, "p99_ms": 2410.0},
        },
        "checkout_slow_ratio_5m": 0.41,
        "slowest_routes_p95": [
            {"service": PAY, "route": "/api/payments/charge", "p95_ms": 2050.0},
            {"service": SHOP, "route": "/api/checkout", "p95_ms": 2240.0},
            {"service": SHOP, "route": "/api/search", "p95_ms": 62.0},
        ],
        "alerts": [{"alert": "ShopSphereCheckoutLatencySLO", "state": "firing", "severity": "page",
                    "summary": "more than 5% of checkouts slower than 1s (41%)", "runbook": "docs/runbooks.md#checkout-latency",
                    "active_at": "2026-11-11T05:20:00Z"}],
        "changes": {"payments": {"latency_ms": 1500, "jitter_ms": 500}},
        "traces": [_checkout_trace("7c1e5d0a9b3f4e2d8a6b1c0d9e8f7a6b", 2104), _checkout_trace("1f2e3d4c5b6a79808f7e6d5c4b3a2910", 1876)],
        "logs": [
            {"service.name": PAY, "otel.log.severity.text": "WARN", "_raw": "payment authorize slow", "trace_id": "7c1e5d0a9b3f4e2d8a6b1c0d9e8f7a6b", "shop.duration_ms": "2098"},
            {"service.name": SHOP, "otel.log.severity.text": "INFO", "_raw": "order placed", "trace_id": "7c1e5d0a9b3f4e2d8a6b1c0d9e8f7a6b"},
        ],
    },
    "payments-outage": {
        "services": {
            SHOP: {"rps": 40.2, "error_ratio_5m": 0.052, "error_ratio_1h": 0.011, "burn_rate_1h": 2.2, "p95_ms": 55.0, "p99_ms": 140.0},
            PAY: {"rps": 2.2, "error_ratio_5m": 1.0, "error_ratio_1h": 0.18, "burn_rate_1h": 36.0, "p95_ms": 3.0, "p99_ms": 5.0},
        },
        "checkout_slow_ratio_5m": 0.0,
        "slowest_routes_p95": [{"service": SHOP, "route": "/api/checkout", "p95_ms": 150.0}],
        "alerts": [
            {"alert": "ShopSphereErrorBudgetFastBurn", "state": "firing", "severity": "page",
             "summary": "payments-service burning error budget 14x (2% of 30d budget per hour)",
             "runbook": "docs/runbooks.md#error-budget-burn", "active_at": "2026-11-11T05:21:00Z"},
            {"alert": "ShopSpherePaymentsErrors", "state": "firing", "severity": "page",
             "summary": "payments failing", "runbook": "docs/runbooks.md#payments-down", "active_at": "2026-11-11T05:21:30Z"},
        ],
        "changes": {"payments": {"down": True}},
        "traces": [_checkout_trace("9a8b7c6d5e4f30211203f4e5d6c7b8a9", 4, down=True)],
        "logs": [
            {"service.name": PAY, "otel.log.severity.text": "ERROR", "_raw": "injected fault", "trace_id": "9a8b7c6d5e4f30211203f4e5d6c7b8a9"},
            {"service.name": SHOP, "otel.log.severity.text": "ERROR", "_raw": "payment failed: provider unavailable", "trace_id": "9a8b7c6d5e4f30211203f4e5d6c7b8a9"},
        ],
    },
}  # fmt: skip


class FixtureBackends:
    def __init__(self, scenario: str = "checkout-latency") -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}; choose from {', '.join(SCENARIOS)}")
        self.scenario = scenario
        self.s = SCENARIOS[scenario]

    # Prometheus
    def query(self, promql: str) -> dict[str, Any]:
        if not promql.strip():
            raise ToolError("promql must not be empty")
        key = "p95_ms" if "latency" in promql else "error_ratio_5m" if "error" in promql else "rps"
        scale = 1000 if key == "p95_ms" else 1
        series = [{"labels": {"service_name": k}, "value": v[key] / scale} for k, v in self.s["services"].items()]
        return {"query": promql, "type": "vector", "series": series, "truncated": False, "note": "fixture data"}

    def slo_status(self) -> dict[str, Any]:
        return {
            "slo": {"availability": 0.995, "checkout_latency": "95% of checkouts < 1s"},
            "services": self.s["services"],
            "checkout_slow_ratio_5m": self.s["checkout_slow_ratio_5m"],
            "slowest_routes_p95": self.s["slowest_routes_p95"],
        }

    def alerts(self) -> dict[str, Any]:
        return {"firing": [a for a in self.s["alerts"] if a["state"] == "firing"], "pending": []}

    # Jaeger
    def services(self) -> list[str]:
        return [SHOP, PAY]

    def search(self, service, operation=None, errors_only=False, min_duration_ms=None, lookback_minutes=15, limit=10):
        if service not in (SHOP, PAY):
            raise ToolError(f"unknown service '{service}'; known: {SHOP}, {PAY}")
        traces = [summarize_trace(t) for t in self.s["traces"]]
        if errors_only:
            traces = [t for t in traces if t["error_spans"]]
        if min_duration_ms:
            traces = [t for t in traces if t["duration_ms"] >= min_duration_ms]
        return {"query": {"service": service, "operation": operation}, "count": len(traces), "traces": traces[:limit]}

    def get_trace(self, trace_id: str) -> dict[str, Any]:
        for t in self.s["traces"]:
            if t["traceID"] == trace_id:
                return summarize_trace(t, top=10)
        raise ToolError(f"trace {trace_id} not found (expired or wrong id)")

    # Splunk
    def log_search(self, spl: str, earliest_minutes: int = 15, limit: int = 20) -> dict[str, Any]:
        safe = validate_spl(spl, ("main",)) + f" | head {limit}"
        rows = self.s["logs"]
        lowered = spl.lower()
        for sev in ("error", "warn"):
            if f"severity.text={sev}" in lowered:
                rows = [r for r in rows if r["otel.log.severity.text"].lower() == sev]
        for r in self.s["logs"]:
            if r["trace_id"] in spl:
                rows = [x for x in rows if x["trace_id"] == r["trace_id"]]
                break
        return {
            "search": safe,
            "earliest": f"-{earliest_minutes}m",
            "count": len(rows[:limit]),
            "results": rows[:limit],
        }

    # Changes
    def recent_changes(self) -> dict[str, Any]:
        return {"source": "fixture", "active_faults": self.s["changes"], "any_active": bool(self.s["changes"])}
