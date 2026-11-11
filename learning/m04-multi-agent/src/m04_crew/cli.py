"""m04 run | resume | history | graph | supervisor  -- see README.md."""

from __future__ import annotations

import argparse
import json
import os
import uuid

from m01_agent.config import load_dotenv


def _print_updates(chunk: dict) -> None:
    for node, update in chunk.items():
        if node == "__interrupt__":
            req = update[0].value
            p = req["plan"]
            print(
                f"\n  >>> HUMAN APPROVAL NEEDED: {p['action']}({p['target']}) risk={p['risk']}\n      {p['rationale']}"
            )
            continue
        for t in (update or {}).get("timeline", []):
            print(f"  [{t['agent']:<10}] {t['event']}")


def _drive(app, payload, cfg, decide: str) -> dict:
    from langgraph.types import Command

    while True:
        for chunk in app.stream(payload, cfg, stream_mode="updates"):
            _print_updates(chunk)
        snap = app.get_state(cfg)
        if not snap.next:
            return snap.values
        if decide == "pause":
            print(
                f"\n  paused at {snap.next}. Resume: m04 resume --thread {cfg['configurable']['thread_id']} --approve"
            )
            return snap.values
        ok = input("  approve? [y/N] ").strip().lower() == "y" if decide == "ask" else decide == "approve"
        payload = Command(resume={"approved": ok, "by": os.getenv("USERNAME") or os.getenv("USER") or "cli"})


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="m04", description="Multi-agent incident-response crew (LangGraph)")
    p.add_argument("--provider", choices=["mock", "anthropic"], default=os.getenv("AGENT_PROVIDER", "mock"))
    p.add_argument("--backend", choices=["fixture", "live"], default=os.getenv("OBS_BACKEND", "fixture"))
    p.add_argument("--scenario", default=os.getenv("OBS_FIXTURE_SCENARIO", "checkout-latency"))
    p.add_argument("--checkpoint", default=os.getenv("M04_CHECKPOINT"), help="memory | file.db | postgresql://...")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("alert", nargs="?", default="ShopSphere SLO alert")
    r.add_argument("--thread")
    mode = r.add_mutually_exclusive_group()
    mode.add_argument("--approve", action="store_const", dest="decide", const="approve")
    mode.add_argument("--reject", action="store_const", dest="decide", const="reject")
    mode.add_argument("--pause", action="store_const", dest="decide", const="pause", help="stop at approval")
    r.add_argument("--crash-before", choices=["planner", "executor", "verifier"])
    r.add_argument("--postmortem", action="store_true", help="print the postmortem")
    rs = sub.add_parser("resume")
    rs.add_argument("--thread", required=True)
    m2 = rs.add_mutually_exclusive_group()
    m2.add_argument("--approve", action="store_const", dest="decide", const="approve")
    m2.add_argument("--reject", action="store_const", dest="decide", const="reject")
    rs.add_argument("--postmortem", action="store_true")
    h = sub.add_parser("history")
    h.add_argument("--thread", required=True)
    gr = sub.add_parser("graph")
    gr.add_argument("--supervisor", action="store_true")
    sp = sub.add_parser("supervisor")
    sp.add_argument("alert", nargs="?", default="ShopSphere SLO alert")
    args = p.parse_args(argv)

    from .checkpoint import open_checkpointer
    from .crew import Crew
    from .graph import build_graph
    from .llm import build_llm
    from .supervisor import build_supervisor_graph
    from .tools import Toolbox

    tools = Toolbox(args.backend, args.scenario)
    crew = Crew(tools, build_llm(args.provider), crash_before=getattr(args, "crash_before", None))

    if args.cmd == "graph":
        app = build_supervisor_graph(crew) if args.supervisor else build_graph(crew)
        print(app.get_graph().draw_mermaid())
        return 0
    if args.cmd == "supervisor":
        out = build_supervisor_graph(crew).invoke({"alert": args.alert})
        for t in out["timeline"]:
            print(f"  [{t['agent']:<10}] {t['event']}")
        print(f"\nllm_calls={crew.llm.calls}")
        return 0

    with open_checkpointer(args.checkpoint) as saver:
        app = build_graph(crew, checkpointer=saver)
        if args.cmd == "history":
            cfg = {"configurable": {"thread_id": args.thread}}
            for s in app.get_state_history(cfg):
                print(
                    f"  step={s.metadata.get('step'):>3} next={list(s.next)} "
                    f"id={s.config['configurable']['checkpoint_id']}"
                )
            return 0
        thread = getattr(args, "thread", None) or f"inc-{uuid.uuid4().hex[:8]}"
        cfg = {"configurable": {"thread_id": thread}}
        print(f"thread={thread} backend={tools.mode} provider={args.provider}")
        payload = None if args.cmd == "resume" else {"alert": args.alert}
        if args.cmd == "resume" and app.get_state(cfg).next == ("approval",) and app.get_state(cfg).tasks[0].interrupts:
            from langgraph.types import Command

            payload = Command(resume={"approved": args.decide == "approve", "by": "cli"})
        try:
            final = _drive(app, payload, cfg, args.decide or "ask")
        except RuntimeError as exc:
            print(f"\n  CRASH: {exc}. State is checkpointed. Resume: m04 resume --thread {thread} --approve")
            return 1
        print(
            f"\nstatus={final.get('status')} severity={final.get('severity')} llm_calls={crew.llm.calls} "
            f"writes={len(tools.writes)}"
        )
        if final.get("rca"):
            print("rca:", json.dumps(final["rca"]))
        if args.postmortem and final.get("postmortem"):
            print("\n" + final["postmortem"])
    return 0
