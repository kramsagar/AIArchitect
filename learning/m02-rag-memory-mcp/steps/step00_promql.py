"""Step 0 - talk to Prometheus over HTTP. Concepts: the PromQL HTTP API, recording rules, shaping raw JSON for an LLM.

Run:  python steps/step00_promql.py
      python steps/step00_promql.py "shopsphere:http_latency_seconds:p99_5m"
"""

import json
import sys

import httpx
from common import FIX, LIVE, PROMETHEUS, mode


def prom_query(promql: str, timeout_s: float = 5.0) -> dict:
    """Instant query -> a SMALL, flat result: [{labels, value}]. LLM context is precious; never pass raw JSON."""
    if not LIVE:
        return FIX.query(promql)
    resp = httpx.get(f"{PROMETHEUS}/api/v1/query", params={"query": promql}, timeout=timeout_s)
    resp.raise_for_status()
    data = resp.json()["data"]
    series = [
        {"labels": r["metric"], "value": round(float(r["value"][1]), 4)}
        for r in data["result"]
        if r["value"][1] != "NaN"  # no traffic in the window -> NaN; drop it instead of confusing the model
    ]
    return {"query": promql, "type": data["resultType"], "series": series[:20], "truncated": len(series) > 20}


def main() -> None:
    print(f"mode: {mode()}\n")
    for q in sys.argv[1:] or [
        "sum by (service_name) (shopsphere:http_requests:rate1m)",  # traffic (recording rule from lab/prometheus)
        'shopsphere:http_latency_seconds:p95_5m{http_route="/api/checkout"}',  # checkout latency
        "shopsphere:http_errors:ratio_rate5m",  # error ratio per service
    ]:
        print(f"PromQL: {q}\n{json.dumps(prom_query(q), indent=1)[:700]}\n")
    if LIVE:
        raw = httpx.get(f"{PROMETHEUS}/api/v1/query", params={"query": "shopsphere:http_errors:ratio_rate5m"}).text
        print(f"Raw API answer was {len(raw)} chars; the shaped one is what the agent will see.")


if __name__ == "__main__":
    main()
