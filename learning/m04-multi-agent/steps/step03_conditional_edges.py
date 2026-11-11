"""Step 3 - conditional edges: a pure function of state picks the next node. Healthy system -> stop early,
errors -> error path, latency -> latency path.

Run:  python steps/step03_conditional_edges.py
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from m04_crew.tools import Toolbox


class S(TypedDict, total=False):
    kind: str
    evidence: Annotated[list[str], operator.add]


def build(tb: Toolbox):
    def triage(state):
        worst = max(
            tb.slo()["services"].values(),
            key=lambda s: (s.get("error_ratio_5m") or 0) * 100 + (s.get("p95_ms") or 0) / 500,
        )
        kind = (
            "errors"
            if (worst.get("error_ratio_5m") or 0) > 0.01
            else "latency"
            if (worst.get("p95_ms") or 0) > 500
            else "healthy"
        )
        return {"kind": kind}

    def errors(state):
        return {"evidence": ["checked ERROR logs + failing traces"]}

    def latency(state):
        return {"evidence": ["checked slow traces + slowest routes"]}

    def route(state) -> str:  # NO side effects, NO LLM: easy to test, same answer every time
        return {"healthy": "end"}.get(state["kind"], state["kind"])

    g = StateGraph(S)
    g.add_node("triage", triage)
    g.add_node("errors", errors)
    g.add_node("latency", latency)
    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", route, {"errors": "errors", "latency": "latency", "end": END})
    g.add_edge("errors", END)
    g.add_edge("latency", END)
    return g.compile()


if __name__ == "__main__":
    for scenario in ("healthy", "checkout-latency", "payments-outage"):
        out = build(Toolbox("fixture", scenario)).invoke({})
        print(f"{scenario:<17} kind={out['kind']:<8} evidence={out.get('evidence', [])}")
