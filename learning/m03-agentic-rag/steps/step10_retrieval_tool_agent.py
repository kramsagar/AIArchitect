"""Step 10 - retrieval as a TOOL: Claude decides whether/how to search, when to use the graph, when to read
a full chunk. Same tool loop as Module 1, new tools.

Run:  python steps/step10_retrieval_tool_agent.py "what is affected if redis fails and who is on call?"
"""

import json
import sys

import anthropic
from common import BY_ID, MODEL, llm
from step04_rerank import hybrid_rerank
from step08_corrective_rag import corrective

from m03_rag.agent import TOOLS
from m03_rag.graph import ServiceGraph

GRAPH, HELPER = ServiceGraph(), None
SYSTEM = "You are an SRE knowledge assistant. Answer only from tool results and cite chunk ids like runbooks#x."


def run_tool(name: str, args: dict) -> dict:
    if name == "search_knowledge":
        ids = (
            corrective(HELPER, args["query"])[0]
            if args.get("strategy") == "corrective"
            else hybrid_rerank(args["query"])
        )
        return {"results": [{"id": i, "snippet": BY_ID[i].text[:400]} for i in ids]}
    if name == "service_graph":
        return GRAPH.describe(args["service"]) | {"cite_as": ["service-graph#dependencies", "service-graph#ownership"]}
    if name == "read_chunk":
        return (
            {"id": args["chunk_id"], "text": BY_ID[args["chunk_id"]].text}
            if args["chunk_id"] in BY_ID
            else {"error": "unknown id"}
        )
    return {"error": f"unknown tool {name}"}


def agent(question: str, max_steps: int = 6) -> tuple[str, list]:
    c, messages, calls = anthropic.Anthropic(), [{"role": "user", "content": question}], []
    for _ in range(max_steps):
        resp = c.messages.create(model=MODEL, max_tokens=1500, system=SYSTEM, tools=TOOLS, messages=messages)
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            return "".join(b.text for b in resp.content if b.type == "text"), calls
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for u in uses:
            out = json.dumps(run_tool(u.name, u.input))
            calls.append((u.name, u.input, out))
            print(f"  -> {u.name}({json.dumps(u.input)[:80]})")
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": out[:8000]})
        messages.append({"role": "user", "content": results})
    return "Stopped: step limit.", calls


if __name__ == "__main__":
    HELPER = llm()
    print("\n" + agent(" ".join(sys.argv[1:]) or "what is affected if redis fails and who is on call?")[0])
