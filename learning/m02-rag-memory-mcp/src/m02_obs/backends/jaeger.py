"""Jaeger (APM) query API tool. Traces are huge: one checkout is 20-40 spans. The tool returns a summary per trace
(root op, duration, error spans, slowest spans) and the agent drills into one trace only when it needs to."""

from __future__ import annotations

import json
from typing import Any

from m01_agent.errors import ToolError

from .http import BackendClient


def _tags(span: dict[str, Any]) -> dict[str, Any]:
    return {t["key"]: t["value"] for t in span.get("tags", [])}


def _is_error(span: dict[str, Any]) -> bool:
    tags = _tags(span)
    return tags.get("error") in (True, "true") or tags.get("otel.status_code") == "ERROR"


def summarize_trace(trace: dict[str, Any], top: int = 5) -> dict[str, Any]:
    procs = {pid: p["serviceName"] for pid, p in trace.get("processes", {}).items()}
    spans = trace.get("spans", [])
    if not spans:
        raise ToolError("trace has no spans")
    ids = {s["spanID"] for s in spans}
    roots = [s for s in spans if not any(r.get("spanID") in ids for r in s.get("references", []))] or spans
    root = max(roots, key=lambda s: s["duration"])

    def view(s: dict[str, Any]) -> dict[str, Any]:
        tags = _tags(s)
        out = {
            "service": procs.get(s["processID"], "?"),
            "operation": s["operationName"],
            "ms": round(s["duration"] / 1000, 1),
        }
        status = tags.get("http.response.status_code") or tags.get("http.status_code")
        if status:
            out["status"] = status
        if _is_error(s):
            out["error"] = tags.get("otel.status_description") or "error"
        return out

    return {
        "trace_id": trace["traceID"],
        "root": view(root),
        "duration_ms": round(root["duration"] / 1000, 1),
        "services": sorted(set(procs.values())),
        "span_count": len(spans),
        "error_spans": [view(s) for s in spans if _is_error(s)][:top],
        "slowest_spans": [view(s) for s in sorted(spans, key=lambda s: -s["duration"]) if s is not root][:top],
    }


class JaegerBackend:
    def __init__(self, client: BackendClient, max_rows: int = 50) -> None:
        self.client = client
        self.max_rows = max_rows

    def services(self) -> list[str]:
        return [s for s in self.client.get_json("/api/services")["data"] or [] if s != "jaeger-all-in-one"]

    def search(
        self,
        service: str,
        operation: str | None = None,
        errors_only: bool = False,
        min_duration_ms: int | None = None,
        lookback_minutes: int = 15,
        limit: int = 10,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"service": service, "lookback": f"{lookback_minutes}m", "limit": min(limit, 20)}
        if operation:
            params["operation"] = operation
        if errors_only:
            params["tags"] = json.dumps({"error": "true"})
        if min_duration_ms:
            params["minDuration"] = f"{min_duration_ms}ms"
        data = self.client.get_json("/api/traces", params=params, cache=False)
        if data.get("errors"):
            raise ToolError(f"jaeger: {data['errors']}")
        traces = sorted((summarize_trace(t) for t in data.get("data") or []), key=lambda t: -t["duration_ms"])
        return {"query": params, "count": len(traces), "traces": traces[:limit]}

    def get_trace(self, trace_id: str) -> dict[str, Any]:
        if not trace_id.isalnum() or len(trace_id) > 32:
            raise ToolError("trace_id must be a hex trace id")
        data = self.client.get_json(f"/api/traces/{trace_id}")
        if not data.get("data"):
            raise ToolError(f"trace {trace_id} not found (expired or wrong id)")
        return summarize_trace(data["data"][0], top=10)
