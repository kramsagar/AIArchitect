"""Splunk search tool over the REST API (/services/search/jobs/export).

Letting a model write SPL is letting it run code on your log platform. The guardrail here is an allow-list:
read-only search commands, an index allow-list, a time window and a row cap. Commands that write (`collect`,
`outputlookup`, `delete`), call out (`sendemail`, `rest`, `script`, `map`) or fan out cost are rejected before
anything reaches Splunk."""

from __future__ import annotations

import json
import re
from typing import Any

from m01_agent.errors import ToolError

from .http import BackendClient

DENIED_COMMANDS = {
    "delete", "collect", "outputlookup", "outputcsv", "outputtext", "sendemail", "sendalert", "script", "run",
    "runshellscript", "rest", "map", "tscollect", "mcollect", "meventcollect", "dbxquery", "dbxoutput", "summaryindex",
    "sistats", "sitimechart", "sichart", "sirare", "sitop",
}  # fmt: skip  # fmt: skip
INDEX_RE = re.compile(r"\bindex\s*=\s*\"?([\w\-*]+)\"?", re.IGNORECASE)
COMMAND_RE = re.compile(r"\|\s*([a-zA-Z_]+)")
FIELDS = ("_time", "service.name", "otel.log.severity.text", "_raw", "trace_id", "span_id", "count")


def validate_spl(spl: str, allowed_indexes: tuple[str, ...]) -> str:
    """Return a normalised, safe SPL string or raise ToolError explaining what to change."""
    q = spl.strip()
    if not q:
        raise ToolError("query must not be empty")
    if q.startswith("|"):
        raise ToolError("generating commands (queries starting with '|') are not allowed; start with index=...")
    if "`" in q:
        raise ToolError("macros are not allowed")
    for cmd in COMMAND_RE.findall(q):
        if cmd.lower() in DENIED_COMMANDS:
            raise ToolError(f"command '{cmd}' is not allowed (read-only search only)")
    indexes = INDEX_RE.findall(q)
    if not indexes:
        raise ToolError(f"specify an index, e.g. index={allowed_indexes[0]}")
    for idx in indexes:
        if idx not in allowed_indexes:
            raise ToolError(f"index '{idx}' is not allowed; allowed: {', '.join(allowed_indexes)}")
    return q if q.lower().startswith("search ") else f"search {q}"


class SplunkBackend:
    def __init__(self, client: BackendClient, allowed_indexes: tuple[str, ...] = ("main",), max_rows: int = 50) -> None:
        self.client = client
        self.allowed_indexes = allowed_indexes
        self.max_rows = max_rows

    def search(self, spl: str, earliest_minutes: int = 15, limit: int = 20) -> dict[str, Any]:
        limit = max(1, min(limit, self.max_rows))
        safe = validate_spl(spl, self.allowed_indexes) + f" | head {limit}"
        resp = self.client.request(
            "POST",
            "/services/search/jobs/export",
            cache=False,
            data={
                "search": safe,
                "output_mode": "json",
                "earliest_time": f"-{earliest_minutes}m",
                "latest_time": "now",
            },
        )
        rows, messages = [], []
        for line in resp.text.splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            messages += [m["text"] for m in item.get("messages", []) if m.get("type") in ("ERROR", "FATAL")]
            if "result" in item:
                r = item["result"]
                row = {k: r[k] for k in FIELDS if k in r}
                row.update(
                    {
                        k: v
                        for k, v in r.items()
                        if not k.startswith("_")
                        and k not in row
                        and len(row) < 12
                        and k not in ("host", "index", "linecount", "source", "sourcetype", "splunk_server")
                    }
                )
                if "_raw" in row:
                    row["_raw"] = str(row["_raw"])[:300]
                rows.append(row)
        if messages and not rows:
            raise ToolError(f"splunk: {'; '.join(messages)[:300]}")
        return {"search": safe, "earliest": f"-{earliest_minutes}m", "count": len(rows), "results": rows}
