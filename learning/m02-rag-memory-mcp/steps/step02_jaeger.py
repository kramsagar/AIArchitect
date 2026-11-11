"""Step 2 - traces from Jaeger. Concepts: trace search, span tree, finding the bottleneck span, shaping a trace.

Run:  python steps/step02_jaeger.py
"""

import json

from common import FIX, JAEGER, LIVE, mode
from step01_resilient_client import Backend

jaeger = Backend(JAEGER)


def summarize(trace: dict) -> dict:
    """A trace has dozens of spans; the agent needs: who was involved, how long, what failed, what was slowest."""
    procs = {pid: p["serviceName"] for pid, p in trace["processes"].items()}
    spans = []
    for s in trace["spans"]:
        tags = {t["key"]: t["value"] for t in s.get("tags", [])}
        spans.append(
            {
                "service": procs[s["processID"]],
                "operation": s["operationName"],
                "ms": round(s["duration"] / 1000, 1),  # Jaeger uses microseconds
                "error": bool(tags.get("error")) or str(tags.get("http.response.status_code", "200")).startswith("5"),
                "root": not s.get("references"),
            }
        )
    root = next((s for s in spans if s["root"]), spans[0])
    return {
        "trace_id": trace["traceID"],
        "root": f"{root['service']} {root['operation']}",
        "duration_ms": root["ms"],
        "services": sorted({s["service"] for s in spans}),
        "error_spans": [s for s in spans if s["error"]][:3],
        "slowest_spans": sorted((s for s in spans if not s["root"]), key=lambda s: -s["ms"])[:3],
    }


def search_traces(service: str, operation: str | None = None, min_ms: int | None = None, limit: int = 5) -> dict:
    if not LIVE:
        return FIX.search(service, operation, min_duration_ms=min_ms, limit=limit)
    params = {"service": service, "limit": limit, "lookback": "15m"}
    if operation:
        params["operation"] = operation
    if min_ms:
        params["minDuration"] = f"{min_ms}ms"
    data = jaeger.get_json("/api/traces", **params)["data"]
    return {"count": len(data), "traces": [summarize(t) for t in data]}


def main() -> None:
    print(f"mode: {mode()}\n")
    if LIVE:
        print("services:", jaeger.get_json("/api/services")["data"])
    result = search_traces("shopsphere-shop", "POST /api/checkout", limit=3)
    print(json.dumps(result, indent=1)[:1500])
    print(
        "\nRead slowest_spans: the biggest child span is where the time goes (DB? payments? nothing = the app itself)."
    )


if __name__ == "__main__":
    main()
