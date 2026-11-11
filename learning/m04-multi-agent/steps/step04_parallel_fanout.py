"""Step 4 - parallel fan-out and join. Triage fans out to 5 investigators that run in ONE super-step; the evidence
reducer merges their writes; `add_edge([...], "rca")` is a barrier, so rca waits for all of them.

Run:  python steps/step04_parallel_fanout.py
"""

import time

from common import tools
from langgraph.graph import END, START, StateGraph

from m04_crew.crew import Crew
from m04_crew.llm import MockCrewLLM
from m04_crew.state import IncidentState

INVESTIGATORS = ["metrics", "traces", "logs", "changes", "knowledge"]


def build(crew: Crew):
    g = StateGraph(IncidentState)
    g.add_node("triage", crew.triage)
    for name in INVESTIGATORS:
        g.add_node(name, getattr(crew, name))
    g.add_node("join", lambda s: {"timeline": [{"agent": "join", "event": f"{len(s['evidence'])} evidence items"}]})
    g.add_edge(START, "triage")
    for name in INVESTIGATORS:
        g.add_edge("triage", name)  # fan-out
    g.add_edge(INVESTIGATORS, "join")  # join (barrier)
    g.add_edge("join", END)
    return g.compile()


if __name__ == "__main__":
    t0 = time.perf_counter()
    out = build(Crew(tools(), MockCrewLLM())).invoke({"alert": "checkout latency SLO"})
    for t in out["timeline"]:
        print(f"[{t['agent']:<9}] {t['event']}")
    print("\nevidence ids:", [e["id"] for e in out["evidence"]])
    print(f"elapsed {1000 * (time.perf_counter() - t0):.0f} ms  (parallel: ~ the slowest investigator, not the sum)")
