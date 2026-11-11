"""Lab 1 - real tools: call Prometheus, Jaeger, Splunk and the chaos API through the resilient backends.

python -m m02_obs.labs.l01_real_tools              # offline fixtures
python -m m02_obs.labs.l01_real_tools --live       # against the running lab
"""

import json
import sys

from m01_agent.errors import ToolError

from m02_obs.backends import build_backends
from m02_obs.config import ObsConfig


def show(title, fn):
    try:
        out = fn()
        text = json.dumps(out, indent=1)
        print(f"\n== {title}  ({len(text)} chars)\n{text[:700]}")
    except ToolError as exc:
        print(f"\n== {title}  -> {exc.error_type}: {exc}")


def main() -> None:
    cfg = ObsConfig.from_env(backend="live" if "--live" in sys.argv else None)
    be = build_backends(cfg)
    print(f"backend mode: {be.mode}")
    show("SLO status (coarse tool)", be.metrics.slo_status)
    show("firing alerts", be.metrics.alerts)
    show("PromQL (fine tool): p95 by route", lambda: be.metrics.query("shopsphere:http_latency_seconds:p95_5m"))
    traces = be.traces.search("shopsphere-shop", "POST /api/checkout", limit=2)
    show("Jaeger search, shaped", lambda: traces)
    if traces["traces"]:
        tid = traces["traces"][0]["trace_id"]
        show("one trace", lambda: be.traces.get_trace(tid))
        show("its logs in Splunk", lambda: be.logs.search(f"index=main trace_id={tid}"))
    show("guardrail: write command", lambda: be.logs.search("index=main | outputlookup stolen.csv"))
    show("guardrail: index not allowed", lambda: be.logs.search("index=_audit action=login"))
    show("recent changes (chaos)", be.changes.recent_changes)
    print("\nExercise: run with --live, enable payments-latency chaos, run again and compare SLO + traces.")


if __name__ == "__main__":
    main()
