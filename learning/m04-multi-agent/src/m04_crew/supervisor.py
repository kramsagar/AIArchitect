"""The same specialists under a *supervisor*: instead of fixed edges, an LLM looks at what has been done so far and
picks the next worker (or FINISH). More flexible, but every hop costs an LLM call and the path is no longer
predictable, so it is bounded by `max_turns` and the choice is validated against the worker list."""

from __future__ import annotations

import json

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from .crew import Crew
from .llm import json_from
from .state import IncidentState

WORKERS = ["changes", "traces", "metrics", "logs", "knowledge", "rca"]

SUPERVISOR_SYSTEM = """[supervisor] You coordinate an SRE incident crew. Workers: changes, traces, metrics, logs,
knowledge (runbooks), rca (root cause; call it last, once there is enough evidence). Given what is done and the
evidence so far, return ONLY JSON {"next": <worker or "FINISH">, "why": str}. Do not repeat a done worker."""


def build_supervisor_graph(crew: Crew, max_turns: int = 7, checkpointer=None):
    def supervisor(state: IncidentState) -> Command:
        done = [t["agent"] for t in state.get("timeline", []) if t["agent"] in WORKERS]
        if "rca" in done or len(done) >= max_turns:
            return Command(goto=END)
        payload = {
            "symptom": state.get("symptom"),
            "workers": WORKERS,
            "done": done,
            "evidence": [e["id"] for e in state.get("evidence", [])],
        }
        choice = (json_from(crew.llm.complete(SUPERVISOR_SYSTEM, json.dumps(payload), max_tokens=200)) or {}).get(
            "next"
        )
        if choice == "FINISH" and "rca" not in done:
            choice = "rca"  # always end with a conclusion
        if choice not in WORKERS or choice in done:  # validate the model's routing decision
            choice = next((w for w in WORKERS if w not in done), "rca")
        return Command(goto=choice, update={"timeline": [{"agent": "supervisor", "event": f"-> {choice}"}]})

    g = StateGraph(IncidentState)
    g.add_node("triage", crew.triage)
    g.add_node("supervisor", supervisor, destinations=(*WORKERS, END))
    for w in WORKERS:
        g.add_node(w, getattr(crew, w))
        g.add_edge(w, "supervisor")
    g.add_edge(START, "triage")
    g.add_edge("triage", "supervisor")
    return g.compile(checkpointer=checkpointer)
