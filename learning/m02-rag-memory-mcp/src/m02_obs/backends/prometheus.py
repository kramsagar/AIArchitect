"""Prometheus HTTP API tool: raw PromQL plus two opinionated, token-cheap views (SLO status and firing alerts).

Design rule for agent tools on real backends: return *shaped* results (named fields, units in the key, rounded
numbers, capped rows), never the raw API payload."""

from __future__ import annotations

import math
from typing import Any

from m01_agent.errors import ToolError

from .http import BackendClient


def _num(value: str) -> float | None:
    v = float(value)
    return None if math.isnan(v) or math.isinf(v) else v


class PrometheusBackend:
    def __init__(self, client: BackendClient, max_rows: int = 50) -> None:
        self.client = client
        self.max_rows = max_rows

    def query(self, promql: str) -> dict[str, Any]:
        if not promql.strip():
            raise ToolError("promql must not be empty")
        data = self.client.get_json("/api/v1/query", params={"query": promql})
        if data.get("status") != "success":
            raise ToolError(f"prometheus: {data.get('errorType')}: {data.get('error')}")
        result = data["data"]["result"]
        rtype = data["data"]["resultType"]
        if rtype == "scalar":
            return {"query": promql, "type": rtype, "value": _num(result[1]), "series": []}
        series = [
            {"labels": {k: v for k, v in s["metric"].items() if k != "__name__"}, "value": _num(s["value"][1])}
            for s in result[: self.max_rows]
        ]
        return {"query": promql, "type": rtype, "series": series, "truncated": len(result) > self.max_rows}

    def _by(self, promql: str, *labels: str) -> dict[tuple[str, ...], float | None]:
        return {tuple(s["labels"].get(lb, "") for lb in labels): s["value"] for s in self.query(promql)["series"]}

    def slo_status(self) -> dict[str, Any]:
        """Golden signals per service from the lab's recording rules (prometheus/rules/slo.yml)."""
        rps = self._by("sum by (service_name) (shopsphere:http_requests:rate1m)", "service_name")
        err5 = self._by("shopsphere:http_errors:ratio_rate5m", "service_name")
        err1h = self._by("shopsphere:http_errors:ratio_rate1h", "service_name")
        p95 = self._by("max by (service_name) (shopsphere:http_latency_seconds:p95_5m)", "service_name")
        p99 = self._by("max by (service_name) (shopsphere:http_latency_seconds:p99_5m)", "service_name")
        worst = self._by("topk(3, shopsphere:http_latency_seconds:p95_5m)", "service_name", "http_route")
        slow = self.query("shopsphere:checkout_slow:ratio_rate5m")["series"]
        budget = 0.005  # 99.5% availability SLO
        services = {}
        for (svc,) in sorted(set(rps) | set(err5)):
            e5, e1 = err5.get((svc,)), err1h.get((svc,))
            services[svc] = {
                "rps": _r(rps.get((svc,))),
                "error_ratio_5m": _r(e5, 4),
                "error_ratio_1h": _r(e1, 4),
                "burn_rate_1h": _r(e1 / budget if e1 is not None else None),
                "p95_ms": _ms(p95.get((svc,))),
                "p99_ms": _ms(p99.get((svc,))),
            }
        return {
            "slo": {"availability": 0.995, "checkout_latency": "95% of checkouts < 1s"},
            "services": services,
            "checkout_slow_ratio_5m": _r(slow[0]["value"], 4) if slow else None,
            "slowest_routes_p95": [
                {"service": s, "route": r, "p95_ms": _ms(v)} for (s, r), v in worst.items() if v is not None
            ],
        }

    def alerts(self) -> dict[str, Any]:
        data = self.client.get_json("/api/v1/alerts")
        alerts = [
            {
                "alert": a["labels"].get("alertname"),
                "state": a.get("state"),
                "severity": a["labels"].get("severity"),
                "summary": a.get("annotations", {}).get("summary"),
                "runbook": a.get("annotations", {}).get("runbook"),
                "active_at": a.get("activeAt"),
            }
            for a in data["data"]["alerts"][: self.max_rows]
        ]
        return {
            "firing": [a for a in alerts if a["state"] == "firing"],
            "pending": [a for a in alerts if a["state"] == "pending"],
        }


def _r(v: float | None, nd: int = 2) -> float | None:
    return None if v is None else round(v, nd)


def _ms(v: float | None) -> float | None:
    return None if v is None else round(v * 1000, 1)
