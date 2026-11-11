"""Step 10 - an MCP client. Concepts: the host starts the server as a subprocess (stdio), initialize handshake,
discover tools AT RUNTIME (no hard-coded tool list), call them, turn MCP tool schemas into Claude tool specs.

Run:  python steps/step10_mcp_client.py
"""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = StdioServerParameters(
    command=sys.executable, args=[str(Path(__file__).with_name("step09_mcp_server.py")), "--serve"]
)


def to_claude_tools(mcp_tools) -> list[dict]:
    """MCP and Claude both describe tools with JSON schema, so the mapping is 1:1."""
    return [{"name": t.name, "description": t.description or "", "input_schema": t.inputSchema} for t in mcp_tools]


async def main() -> None:
    async with stdio_client(SERVER) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        print(f"connected to {init.serverInfo.name}, protocol {init.protocolVersion}")
        tools = (await session.list_tools()).tools
        print("discovered tools:", [t.name for t in tools])
        print("as Claude tool specs:", [t["name"] for t in to_claude_tools(tools)])
        result = await session.call_tool("slo_status", {})
        print("slo_status ->", result.content[0].text[:300])
        bad = await session.call_tool("logs", {"spl": "index=main | delete"})
        print(f"logs(delete) -> isError={bad.isError}: {bad.content[0].text[:120]}")


if __name__ == "__main__":
    asyncio.run(main())
