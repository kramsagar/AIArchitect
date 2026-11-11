"""m02 CLI: knowledge base, MCP server, and the investigator agent (an MCP host)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager

from m01_agent.config import AgentConfig
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .agent import InvestigationResult, Investigator
from .config import ObsConfig
from .llm import ClaudeInvestigatorLLM, MockInvestigatorLLM
from .memory import LongTermMemory, SessionMemory
from .rag.index import KnowledgeBase


@asynccontextmanager
async def mcp_session(cfg: ObsConfig, url: str | None = None):
    """Connect to the observability MCP server: spawn it over stdio, or reach a running one over streamable HTTP."""
    if url:
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(url) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            yield session
        return
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "m02_obs.server"], env={**os.environ, **cfg.env()}
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


def build_llm(provider: str, model: str | None):
    if provider == "mock":
        return MockInvestigatorLLM(), AgentConfig(max_steps=8, max_tool_calls=14)
    cfg = AgentConfig.from_env(
        provider=provider,
        model=model,
        max_steps=8,
        max_tool_calls=14,
        run_timeout_s=180,
        llm_timeout_s=90,
        max_output_tokens=4096,
    )
    cfg.max_output_tokens = 4096
    if provider != "anthropic":
        raise SystemExit("M2 supports --provider mock or anthropic")
    return ClaudeInvestigatorLLM(cfg), cfg


def render(res: InvestigationResult, trace: bool) -> None:
    inv = res.investigation
    if trace:
        for s in res.steps:
            tools = ", ".join(
                f"{t.name}({json.dumps(t.arguments)[:70]}){'' if t.ok else ' ERR'} {t.ms}ms" for t in s.tools
            )
            print(f"  step {s.step} {s.kind}: {tools or s.note or ''}")
        print()
    print(f"[{inv.status.upper()}] {inv.summary}")
    if inv.suspected_cause:
        print(f"\nSuspected cause: {inv.suspected_cause}")
    if inv.affected_services:
        print(f"Affected: {', '.join(inv.affected_services)}")
    print("\nEvidence:")
    for e in inv.evidence:
        print(f"  - [{e.source}] {e.ref}\n      {e.finding}")
    print("\nActions:")
    for a in inv.recommended_actions:
        print(f"  - {a}")
    if inv.runbooks:
        print(f"Runbooks: {', '.join(inv.runbooks)}")
    extra = f" | dropped ungrounded: {res.dropped_evidence}" if res.dropped_evidence else ""
    extra += f" | recalled episodes: {res.recalled_episodes}" if res.recalled_episodes else ""
    print(
        f"\nconfidence={inv.confidence} status={res.status} llm_calls={res.llm_calls} tool_calls={res.tool_calls} "
        f"tokens={res.prompt_tokens}+{res.completion_tokens} elapsed={res.elapsed_ms}ms{extra}"
    )


async def _investigate(args, cfg: ObsConfig, questions: list[str] | None) -> None:
    llm, acfg = build_llm(args.provider, args.model)
    ltm = None if args.no_memory else LongTermMemory(cfg.memory_db)
    async with mcp_session(cfg, args.mcp_url) as session:
        agent = Investigator(llm, session, acfg, SessionMemory(), ltm)
        if questions is not None:
            for q in questions:
                res = await agent.run(q)
                print(res.model_dump_json(indent=2)) if args.json else render(res, args.trace)
            return
        print("Investigator chat (MCP tools discovered:", len(await agent.tool_schemas()), ") - empty line to quit")
        while True:
            q = (await asyncio.to_thread(input, "\nyou> ")).strip()
            if not q:
                return
            render(await agent.run(q), args.trace)


async def _list_tools(cfg: ObsConfig, url: str | None) -> None:
    async with mcp_session(cfg, url) as s:
        for t in (await s.list_tools()).tools:
            ro = " (read-only)" if t.annotations and t.annotations.readOnlyHint else ""
            print(f"tool     {t.name}{ro}: {(t.description or '').splitlines()[0]}")
            print(f"         args: {json.dumps(t.inputSchema.get('properties', {}))[:140]}")
        for r in (await s.list_resource_templates()).resourceTemplates:
            print(f"resource {r.uriTemplate}")
        for r in (await s.list_resources()).resources:
            print(f"resource {r.uri}")
        for p in (await s.list_prompts()).prompts:
            print(f"prompt   {p.name}: {p.description}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="m02", description="Module 2: RAG, memory and MCP over the observability lab")
    p.add_argument("--backend", choices=["fixture", "live"], help="fixture (offline, default) or live lab")
    p.add_argument("--scenario", choices=["checkout-latency", "payments-outage", "healthy"], help="fixture incident")
    p.add_argument("--provider", default=os.getenv("AGENT_PROVIDER", "mock"), choices=["mock", "anthropic"])
    p.add_argument("--model")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    ix = sub.add_parser("index", help="chunk + embed the corpus and list chunks")
    ix.add_argument("--show", action="store_true")
    se = sub.add_parser("search", help="semantic search over runbooks/postmortems/docs")
    se.add_argument("query")
    se.add_argument("-k", type=int, default=3)
    se.add_argument("--type", choices=["runbook", "postmortem", "architecture", "policy"])
    ev = sub.add_parser("eval", help="retrieval eval: recall@k and MRR")
    ev.add_argument("-k", type=int, default=3)
    sv = sub.add_parser("serve", help="run the observability MCP server")
    sv.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    sv.add_argument("--port", type=int, default=8765)
    for name in ("tools", "investigate", "chat"):
        sp = sub.add_parser(name)
        sp.add_argument("--mcp-url", help="use a running server, e.g. http://localhost:8765/mcp")
        if name != "tools":
            sp.add_argument("--trace", action="store_true")
            sp.add_argument("--json", action="store_true")
            sp.add_argument("--no-memory", action="store_true", help="disable long-term memory")
        if name == "investigate":
            sp.add_argument("question", nargs="+")
    mm = sub.add_parser("memory", help="show or clear long-term memory")
    mm.add_argument("--clear", action="store_true")
    mm.add_argument("--remember", nargs=2, metavar=("KEY", "VALUE"))
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, stream=sys.stderr)
    for noisy in ("httpx", "mcp"):
        logging.getLogger(noisy).setLevel(logging.INFO if args.verbose else logging.WARNING)
    cfg = ObsConfig.from_env(backend=args.backend, scenario=args.scenario)

    if args.cmd in ("index", "search", "eval"):
        kb = KnowledgeBase.from_dirs()
        if args.cmd == "index":
            print(f"{len(kb.store)} chunks, embedder={kb.embedder.name}")
            for c in kb.store.chunks:
                print(f"  {c.id:45} {c.metadata}")
                if args.show:
                    print("    " + c.text[:200].replace("\n", "\n    "))
        elif args.cmd == "search":
            for h in kb.search(args.query, k=args.k, filters={"type": args.type} if args.type else None):
                print(f"{h.score:.3f}  {h.chunk.id}\n       {h.chunk.text.splitlines()[1][:150]}")
        else:
            r = kb.evaluate(k=args.k)
            for c in r["cases"]:
                print(f"  rank={c['rank'] or '-':<2} {c['expected']:42} {c['question']}")
            print(f"recall@{r['k']}={r['recall_at_k']}  MRR={r['mrr']}")
    elif args.cmd == "serve":
        from .server import create_server

        create_server(cfg, port=args.port, log_level="WARNING").run(transport=args.transport)
    elif args.cmd == "tools":
        asyncio.run(_list_tools(cfg, args.mcp_url))
    elif args.cmd == "investigate":
        asyncio.run(_investigate(args, cfg, [" ".join(args.question)]))
    elif args.cmd == "chat":
        asyncio.run(_investigate(args, cfg, None))
    elif args.cmd == "memory":
        ltm = LongTermMemory(cfg.memory_db)
        if args.clear:
            ltm.clear()
        if args.remember:
            ltm.remember(*args.remember, source="cli")
        print(json.dumps({"db": str(cfg.memory_db), "facts": ltm.facts(), "episodes": ltm.episodes()}, indent=2))


if __name__ == "__main__":
    main()
