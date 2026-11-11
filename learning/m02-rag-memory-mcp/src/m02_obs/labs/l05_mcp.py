"""Lab 5 - MCP: connect as a client to the observability server over stdio, discover and call tools/resources/prompts.

python -m m02_obs.labs.l05_mcp
Then try a remote server:  m02 serve --transport streamable-http   and   m02 tools --mcp-url http://localhost:8765/mcp
"""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "m02_obs.server"])
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        init = await s.initialize()
        print(f"server: {init.serverInfo.name} protocol={init.protocolVersion}")
        print("instructions:", (init.instructions or "")[:120], "...")
        tools = (await s.list_tools()).tools
        for t in tools:
            print(f"  tool {t.name:20} readOnly={t.annotations.readOnlyHint}")
        res = await s.call_tool("list_firing_alerts", {})
        print("\ncall list_firing_alerts ->", res.content[0].text[:300])
        bad = await s.call_tool("search_logs", {"query": "index=main | delete"})
        print("call search_logs(delete) -> isError =", bad.isError, "|", bad.content[0].text)
        doc = await s.read_resource("runbook://runbooks#checkout-latency")
        print("\nresource runbook://runbooks#checkout-latency ->", doc.contents[0].text[:200])
        prompt = await s.get_prompt("investigate", {"symptom": "ShopSphereCheckoutLatencySLO"})
        print("\nprompt investigate ->", prompt.messages[0].content.text[:200])
    print("\nExercise: add a tool `get_dependency_map` to server.py; it appears here with no client change.")


if __name__ == "__main__":
    asyncio.run(main())
