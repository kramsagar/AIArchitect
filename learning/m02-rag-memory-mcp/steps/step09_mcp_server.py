"""Step 9 - an MCP server. Concepts: Model Context Protocol = a standard way to expose TOOLS (actions),
RESOURCES (readable documents) and PROMPTS (templates) to ANY agent host (Claude Desktop, Claude Code, your agent).

Run:  python steps/step09_mcp_server.py            (in-process demo: list + call)
      python steps/step09_mcp_server.py --serve    (real stdio server; step 10 connects to this)
"""

import asyncio
import json
import sys

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from step02_jaeger import search_traces
from step03_splunk import search_logs
from step04_obs_agent import get_slo_status
from step05_chunking import load_corpus
from step06_vector_search import VectorStore

mcp = FastMCP("observability-steps", instructions="Read-only ShopSphere observability: start with get_slo_status.")
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
CHUNKS = {c.id: c for c in load_corpus()}
STORE = VectorStore(list(CHUNKS.values()))


@mcp.tool(annotations=READ_ONLY)
def slo_status() -> dict:
    """Traffic, error ratio and latency per service. Start every investigation here."""
    return get_slo_status()


@mcp.tool(annotations=READ_ONLY)
def traces(service: str, operation: str | None = None, min_ms: int | None = None) -> dict:
    """Recent traces with slowest and error spans, e.g. service='shopsphere-shop', operation='POST /api/checkout'."""
    return search_traces(service, operation, min_ms)


@mcp.tool(annotations=READ_ONLY)
def logs(spl: str) -> dict:
    """Read-only Splunk search; must include index=main (e.g. 'index=main trace_id=<id>')."""
    return search_logs(spl)


@mcp.tool(annotations=READ_ONLY)
def runbooks(query: str) -> list[dict]:
    """Search runbooks/postmortems; returns chunk ids to cite, e.g. runbooks#checkout-latency."""
    return [{"id": c.id, "score": s, "text": c.text[:500]} for c, s in STORE.search(query)]


@mcp.resource("runbook://{chunk_id}")
def runbook(chunk_id: str) -> str:
    """Full text of one runbook chunk."""
    return CHUNKS[chunk_id].text


@mcp.prompt()
def investigate(symptom: str = "checkout is slow") -> str:
    return f"Investigate: {symptom}. 1) slo_status 2) runbooks 3) traces then logs by trace_id. Cite ids."


async def demo() -> None:
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    async with connect(mcp._mcp_server) as session:  # client + server in one process, no subprocess
        tools = (await session.list_tools()).tools
        print("tools:", [(t.name, t.annotations.readOnlyHint) for t in tools])
        print("input schema of traces:", json.dumps(tools[1].inputSchema)[:200])
        result = await session.call_tool("runbooks", {"query": "checkout latency"})
        print("call runbooks ->", result.content[0].text[:200])
        doc = await session.read_resource("runbook://runbooks#payments-down")
        print("resource ->", doc.contents[0].text[:120])
        prompt = await session.get_prompt("investigate", {"symptom": "payments 503"})
        print("prompt ->", prompt.messages[0].content.text)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        mcp.run()  # stdio transport: the host starts this process and talks JSON-RPC over stdin/stdout
    else:
        asyncio.run(demo())
