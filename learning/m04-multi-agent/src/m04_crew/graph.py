"""Wire the crew into a LangGraph StateGraph. The graph *is* the workflow: nodes are agents, edges are hand-offs,
conditional edges are decisions, the checkpointer makes every step durable."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .crew import Crew
from .state import IncidentState

INVESTIGATORS = ["metrics", "traces", "logs", "changes", "knowledge"]


def build_graph(crew: Crew, checkpointer=None):
    g = StateGraph(IncidentState)
    g.add_node("triage", crew.triage)
    for name in INVESTIGATORS:
        g.add_node(name, getattr(crew, name))
    for name in ("rca", "planner", "approval", "executor", "verifier", "postmortem"):
        g.add_node(name, getattr(crew, name))

    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", crew.after_triage, {**{n: n for n in INVESTIGATORS}, "end": END})
    g.add_edge(INVESTIGATORS, "rca")  # join: rca waits for ALL investigators (a barrier)
    g.add_edge("rca", "planner")
    g.add_edge("planner", "approval")
    g.add_conditional_edges("approval", crew.after_approval, ["executor", "postmortem"])
    g.add_edge("executor", "verifier")
    g.add_conditional_edges("verifier", crew.after_verify, ["planner", "postmortem"])
    g.add_edge("postmortem", END)
    return g.compile(checkpointer=checkpointer)
