"""Step 2 - step 0's workflow as a LangGraph StateGraph: nodes, edges, compile, invoke, and `stream` to watch each
node's update as it happens.

Run:  python steps/step02_first_graph.py
"""

import operator
from typing import Annotated, TypedDict

from common import tools
from langgraph.graph import END, START, StateGraph

TB = tools()


class S(TypedDict, total=False):
    focus: str
    evidence: Annotated[list[str], operator.add]
    verdict: str


def triage(state: S) -> dict:
    slo = TB.slo()["services"]
    svc = max(slo, key=lambda s: (slo[s].get("burn_rate_1h") or 0) + (slo[s].get("p95_ms") or 0) / 500)
    return {"focus": svc, "evidence": [f"slo:{svc}"]}  # return ONLY what changed


def investigate(state: S) -> dict:
    return {"evidence": [f"change:{s}" for s in TB.changes()["active_faults"]]}


def conclude(state: S) -> dict:
    changes = [e for e in state["evidence"] if e.startswith("change:")]
    return {"verdict": f"likely cause: {changes[0]}" if changes else "escalate"}


def build():
    g = StateGraph(S)
    for fn in (triage, investigate, conclude):
        g.add_node(fn.__name__, fn)
    g.add_edge(START, "triage")
    g.add_edge("triage", "investigate")
    g.add_edge("investigate", "conclude")
    g.add_edge("conclude", END)
    return g.compile()


if __name__ == "__main__":
    app = build()
    for update in app.stream({}, stream_mode="updates"):
        print(update)
    print("\nfinal:", app.invoke({}))
    print("\n" + app.get_graph().draw_mermaid())  # paste into https://mermaid.live
