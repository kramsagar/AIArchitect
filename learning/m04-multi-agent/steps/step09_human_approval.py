"""Step 9 - human-in-the-loop: the approval node calls interrupt(plan). The graph saves and STOPS; nothing runs
while the human thinks. Resume with Command(resume=...) - the node re-runs and interrupt() returns the answer.

Run:  python steps/step09_human_approval.py
"""

import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class S(TypedDict, total=False):
    plan: dict
    approved: bool
    log: Annotated[list[str], operator.add]


def planner(state):
    return {"plan": {"action": "reset_faults", "target": "payments", "risk": "medium"}, "log": ["planned"]}


def approval(state):
    print("   (approval node starts - code before interrupt() runs again on resume, keep it side-effect free)")
    answer = interrupt({"question": "approve?", "plan": state["plan"]})
    return {"approved": answer["approved"], "log": [f"approval={answer['approved']} by {answer['by']}"]}


def executor(state):
    return {"log": ["EXECUTED reset_faults(payments)"]}


def build():
    g = StateGraph(S)
    for fn in (planner, approval, executor):
        g.add_node(fn.__name__, fn)
    g.add_edge(START, "planner")
    g.add_edge("planner", "approval")
    g.add_conditional_edges(
        "approval", lambda s: "executor" if s["approved"] else "end", {"executor": "executor", "end": END}
    )
    g.add_edge("executor", END)
    return g.compile(checkpointer=InMemorySaver())  # interrupts NEED a checkpointer


if __name__ == "__main__":
    app = build()
    for decision in (True, False):
        cfg = {"configurable": {"thread_id": f"t-{decision}"}}
        first = app.invoke({}, cfg)
        print("paused with:", first["__interrupt__"][0].value, "| next:", app.get_state(cfg).next)
        final = app.invoke(Command(resume={"approved": decision, "by": "alice"}), cfg)
        print("final log  :", final["log"], "\n")
