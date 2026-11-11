"""m03 search | eval | ask | graph  -- see README.md."""

from __future__ import annotations

import argparse
import json
import os

from m01_agent.config import load_dotenv


def _helper(provider: str):
    from .llm import ClaudeText, MockText

    return ClaudeText() if provider == "anthropic" else MockText()


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="m03", description="Agentic RAG over ShopSphere incident knowledge")
    p.add_argument("--provider", choices=["mock", "anthropic"], default=os.getenv("AGENT_PROVIDER", "mock"))
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--mode", choices=["vector", "bm25", "hybrid", "rerank", "corrective"], default="rerank")
    s.add_argument("-k", type=int, default=5)
    e = sub.add_parser("eval")
    e.add_argument("-k", type=int, default=3)
    a = sub.add_parser("ask")
    a.add_argument("question")
    a.add_argument("--trace", action="store_true")
    g = sub.add_parser("graph")
    g.add_argument("service")
    args = p.parse_args(argv)

    from .hybrid import HybridRetriever

    if args.cmd == "graph":
        from .graph import ServiceGraph

        print(json.dumps(ServiceGraph().describe(args.service), indent=2))
    elif args.cmd == "search":
        from .crag import corrective_retrieve
        from .rerank import lexical_rerank

        r = HybridRetriever()
        if args.mode == "corrective":
            res = corrective_retrieve(r, _helper(args.provider), args.query, k=args.k)
            for at in res.attempts:
                print(f"attempt {at.strategy:9} queries={at.queries} relevant={at.relevant}")
            hits = res.chunks
        elif args.mode == "rerank":
            hits = lexical_rerank(args.query, r.search(args.query, k=20), k=args.k)
        else:
            hits = r.search(args.query, k=args.k, mode=args.mode)
        for h in hits:
            print(json.dumps(h.citation()))
    elif args.cmd == "eval":
        from .eval import evaluate

        for name, row in evaluate(k=args.k, llm=_helper(args.provider)).items():
            misses = row.pop("misses")
            print(f"{name:14} {json.dumps(row)}  misses={len(misses)}")
    else:
        from .agent import KnowledgeAgent, MockKnowledgeClient

        if args.provider == "anthropic":
            import anthropic

            client, model = anthropic.Anthropic(max_retries=2, timeout=60), os.getenv("AGENT_MODEL", "claude-haiku-5-5")
        else:
            client, model = MockKnowledgeClient(), "mock"
        agent = KnowledgeAgent(client, model, helper_llm=_helper(args.provider))
        answer, meta = agent.ask(args.question)
        if args.trace:
            for t in agent.trace:
                print(f"  [step {t['step']}] {t['tool']}({json.dumps(t['input'])[:90]}) -> {t['out'][:90]}")
        print(answer.model_dump_json(indent=2))
        print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
