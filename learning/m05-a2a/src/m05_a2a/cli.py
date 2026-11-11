"""m05 - A2A incident crew.

m05 serve [--agent rca-agent]            # one agent (or all) as A2A servers
m05 cards                                # discovery: print every agent card's skills
m05 run --spawn --approve                # orchestrate an incident over A2A (spawn local agents first)
"""

from __future__ import annotations

import argparse
import json
import time
import uuid

from .agents import AGENTS, registry_urls
from .client import A2AClient
from .launcher import serve_all, serve_one, stop_all


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="m05")
    p.add_argument("--backend", default="fixture", choices=["fixture", "live"])
    p.add_argument("--scenario", default="checkout-latency")
    p.add_argument("--provider", default="mock", choices=["mock", "anthropic"])
    p.add_argument("--host", default="127.0.0.1")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--agent", default="all", choices=["all", *AGENTS])
    sub.add_parser("cards")
    r = sub.add_parser("run")
    r.add_argument("--spawn", action="store_true", help="start all agents in this process first")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--approve", action="store_true")
    g.add_argument("--reject", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "serve":
        if args.agent == "all":
            serve_all(args.backend, args.scenario, args.provider, args.host)
            print("serving:", ", ".join(f"{n}:{a.port}" for n, a in AGENTS.items()), "(Ctrl+C to stop)")
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                return 0
        serve_one(args.agent, args.backend, args.scenario, args.provider, args.host).run()
        return 0

    servers = serve_all(args.backend, args.scenario, args.provider, args.host) if getattr(args, "spawn", False) else []
    try:
        client = A2AClient(registry_urls(args.host))
        skills = client.discover()
        if args.cmd == "cards":
            for name, card in client.cards.items():
                print(f"{name:16} skills={[k['id'] for k in card['skills']]}  {card['supportedInterfaces'][0]['url']}")
            return 0
        return _run(client, skills, args)
    finally:
        stop_all(servers)


def _run(client: A2AClient, skills, args) -> int:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from .orchestrator import build_remote_graph

    app = build_remote_graph(client, InMemorySaver())
    cfg = {"configurable": {"thread_id": f"a2a-{uuid.uuid4().hex[:8]}"}}
    payload: object = {"alert": "ShopSphere SLO alert"}
    decide = "approve" if args.approve else "reject" if args.reject else "ask"
    while True:
        app.invoke(payload, cfg)
        snap = app.get_state(cfg)
        if not snap.next:
            break
        plan = snap.values.get("plan", {})
        print(f"  approval needed: {plan.get('action')}({plan.get('target')}) - {plan.get('rationale', '')[:100]}")
        ok = input("  approve? [y/N] ").strip().lower() == "y" if decide == "ask" else decide == "approve"
        payload = Command(resume={"approved": ok, "by": "a2a-cli"})
    v = snap.values
    for h in client.hops:
        print(f"  hop {h['agent']:16} {h['skill']:10} {h['state']:22} {h['ms']:>7} ms")
    print(f"\nstatus={v.get('status')} trace_id={client.trace_id} hops={len(client.hops)}")
    print(json.dumps({"rca": v.get("rca"), "executed": v.get("executed")}, default=str, indent=1)[:800])
    return 0
