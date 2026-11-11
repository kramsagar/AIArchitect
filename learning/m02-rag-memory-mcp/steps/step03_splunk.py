"""Step 3 - logs from Splunk, safely. Concepts: SPL over the REST API, a READ-ONLY guardrail on model-written
queries (allowed indexes, no write/exec commands), time bounds and row limits.

Run:  python steps/step03_splunk.py
"""

import json
import re

from common import FIX, LIVE, SPLUNK, SPLUNK_AUTH, mode
from m01_agent.errors import ToolError
from step01_resilient_client import Backend

ALLOWED_INDEXES = ("main",)
DENIED = {"delete", "collect", "outputlookup", "outputcsv", "sendemail", "script", "run", "rest", "map", "dbxquery"}


def validate_spl(spl: str) -> str:
    """The model writes the query, so treat it like user input: allow-list, deny-list, bounds."""
    spl = spl.strip().removeprefix("search ").strip()
    if not spl or spl.startswith("|"):
        raise ToolError("query must start with a search over an index, e.g. index=main ...")
    if "`" in spl:
        raise ToolError("macros are not allowed")
    indexes = re.findall(r"\bindex\s*=\s*\"?([\w*-]+)", spl)
    if not indexes or any(i not in ALLOWED_INDEXES for i in indexes):
        raise ToolError(f"query must name an allowed index explicitly: {ALLOWED_INDEXES}")
    commands = {seg.strip().split()[0].lower() for seg in spl.split("|")[1:] if seg.strip()}
    if bad := commands & DENIED:
        raise ToolError(f"command(s) not allowed (read-only tool): {sorted(bad)}")
    return spl


def search_logs(spl: str, earliest_minutes: int = 15, limit: int = 20) -> dict:
    spl = validate_spl(spl)
    if not LIVE:
        return FIX.log_search(spl, earliest_minutes, limit)
    splunk = Backend(SPLUNK, auth=SPLUNK_AUTH, verify=False, timeout_s=15)  # lab uses a self-signed cert
    resp = splunk.http.post(
        "/services/search/jobs/export",
        data={
            "search": f"search {spl} | head {limit}",
            "output_mode": "json",
            "earliest_time": f"-{earliest_minutes}m",
        },
    )
    resp.raise_for_status()
    rows = []  # the export API streams one JSON object per line; only some carry a "result"
    for line in resp.text.splitlines():
        if line.strip().startswith("{") and (row := json.loads(line).get("result")):
            rows.append(row)
    keep = ("_time", "service.name", "otel.log.severity.text", "_raw", "trace_id")
    return {"search": spl, "count": len(rows), "results": [{k: r.get(k) for k in keep if k in r} for r in rows]}


def main() -> None:
    print(f"mode: {mode()}\n")
    for spl in [
        "index=main sourcetype=shopsphere:otel otel.log.severity.text=ERROR",
        "index=main | delete",
        "index=_audit action=login",
        "| rest /services/authentication/users",
    ]:
        try:
            out = search_logs(spl, limit=3)
            print(f"OK   {spl}\n     {json.dumps(out)[:400]}")
        except ToolError as exc:
            print(f"DENY {spl}\n     {exc}")


if __name__ == "__main__":
    main()
