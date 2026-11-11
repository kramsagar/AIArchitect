"""observability-mcp-server: Prometheus, Jaeger, Splunk, change data and runbook search over the Model Context Protocol.

Any MCP host (this module's agent, Claude Desktop, Claude Code, Cursor, an IDE) can discover and call these tools.
Tools are read-only and annotated as such; blocking HTTP calls run in worker threads so one slow backend does not
stall the server's event loop.

Run:  python -m m02_obs.server                      (stdio, for local hosts)
      python -m m02_obs.server --transport streamable-http --port 8765   (remote, http://localhost:8765/mcp)
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

import anyio
from m01_agent.errors import ToolError as BackendError
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from .backends import Backends, build_backends
from .config import ObsConfig
from .rag.index import KnowledgeBase

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)

INSTRUCTIONS = """Read-only observability tools for the ShopSphere lab (services: shopsphere-shop, payments-service).
Start broad (get_slo_status, list_firing_alerts, get_recent_changes), then drill down (search_traces -> get_trace,
search_logs by trace_id). Use search_runbooks for the procedure and cite chunk ids."""


def create_server(config: ObsConfig | None = None, backends: Backends | None = None, kb: KnowledgeBase | None = None,
                  **settings: Any) -> FastMCP:  # fmt: skip
    config = config or ObsConfig.from_env()
    be = backends or build_backends(config)
    kb = kb or KnowledgeBase.from_dirs()
    mcp = FastMCP("observability", instructions=INSTRUCTIONS, **settings)

    async def run(fn: Callable[[], Any]) -> Any:
        try:
            return await anyio.to_thread.run_sync(fn)
        except BackendError as exc:  # becomes isError=true with this message; the model can adapt its next call
            raise ToolError(f"{exc.error_type}: {exc}") from exc

    @mcp.tool(annotations=READ_ONLY)
    async def get_slo_status() -> dict:
        """Golden signals per service (rps, error ratio 5m/1h, burn rate vs the 99.5% SLO, p95/p99 ms), the checkout
        slow-request ratio and the slowest routes. Call this first."""
        return await run(be.metrics.slo_status)

    @mcp.tool(annotations=READ_ONLY)
    async def list_firing_alerts() -> dict:
        """Prometheus alerts currently firing or pending, with summary and runbook link."""
        return await run(be.metrics.alerts)

    @mcp.tool(annotations=READ_ONLY)
    async def promql_query(query: str) -> dict:
        """Run an instant PromQL query. Useful series: shopsphere:http_latency_seconds:p95_5m{service_name,http_route},
        shopsphere:http_errors:ratio_rate5m{service_name}, shop_orders_total{result}, shop_payments_total{result}.
        Returns at most 50 series."""
        return await run(lambda: be.metrics.query(query))

    @mcp.tool(annotations=READ_ONLY)
    async def search_traces(
        service: str,
        operation: str | None = None,
        errors_only: bool = False,
        min_duration_ms: int | None = None,
        lookback_minutes: int = 15,
        limit: int = 5,
    ) -> dict:
        """Search Jaeger traces for a service (shopsphere-shop or payments-service)
        e.g. operation='POST /api/checkout'.
        Returns per-trace summaries: duration, error spans, slowest spans. Use get_trace for one trace in depth."""
        return await run(
            lambda: be.traces.search(service, operation, errors_only, min_duration_ms, lookback_minutes, min(limit, 10))
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_trace(trace_id: str) -> dict:
        """One trace in depth: services involved, error spans and the 10 slowest spans."""
        return await run(lambda: be.traces.get_trace(trace_id))

    @mcp.tool(annotations=READ_ONLY)
    async def search_logs(query: str, earliest_minutes: int = 15, limit: int = 20) -> dict:
        """Read-only Splunk search (SPL). Must include index=main. Fields: service.name, otel.log.severity.text
        (INFO/WARN/ERROR), trace_id, span_id, _raw. Example: index=main otel.log.severity.text=ERROR |
        stats count by service.name. Write/export commands are rejected."""
        return await run(lambda: be.logs.search(query, earliest_minutes, limit))

    @mcp.tool(annotations=READ_ONLY)
    async def get_recent_changes() -> dict:
        """Active faults/changes per service (in the lab: chaos switches). Changes cause most incidents."""
        return await run(be.changes.recent_changes)

    @mcp.tool(annotations=READ_ONLY)
    async def search_runbooks(query: str, k: int = 3, doc_type: str | None = None) -> dict:
        """Semantic search over runbooks, postmortems, architecture and SLO policy. doc_type: runbook | postmortem |
        architecture | policy. Returns chunks with ids to cite."""
        filters = {"type": doc_type} if doc_type else None
        hits = await anyio.to_thread.run_sync(lambda: kb.search(query, k=min(k, 5), filters=filters))
        return {"query": query, "results": [{**h.citation(), "text": h.chunk.text} for h in hits]}

    @mcp.resource("runbook://{chunk_id}", mime_type="text/markdown")
    def runbook(chunk_id: str) -> str:
        """A knowledge-base chunk by id, e.g. runbook://runbooks#checkout-latency."""
        chunk = kb.get(chunk_id)
        if chunk is None:
            raise ValueError(f"no chunk {chunk_id}")
        return chunk.text

    @mcp.resource("kb://index", mime_type="application/json")
    def kb_index() -> str:
        """Every chunk id in the knowledge base with its type."""
        return json.dumps([{"id": c.id, "type": c.metadata.get("type")} for c in kb.store.chunks])

    @mcp.prompt()
    def investigate(symptom: str = "checkout is slow") -> str:
        """Standard investigation procedure for a symptom or alert name."""
        return (
            f"Investigate: {symptom}.\n1. get_slo_status, list_firing_alerts and get_recent_changes.\n"
            "2. search_runbooks for the matching runbook.\n3. Drill down: search_traces on the worst service/route, "
            "then get_trace on the slowest or failing trace; search_logs by its trace_id.\n"
            "4. Answer with cause, evidence (ids), mitigation first."
        )

    return mcp


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="observability MCP server")
    p.add_argument("--transport", choices=["stdio", "streamable-http", "sse"], default="stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--backend", choices=["fixture", "live"])
    p.add_argument("--scenario")
    a = p.parse_args(argv)
    cfg = ObsConfig.from_env(backend=a.backend, scenario=a.scenario)
    create_server(cfg, host=a.host, port=a.port, log_level="WARNING").run(transport=a.transport)


if __name__ == "__main__":
    main()
