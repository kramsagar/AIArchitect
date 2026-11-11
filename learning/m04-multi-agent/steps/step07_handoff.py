"""Step 7 - swarm / hand-off: no central router. An agent decides to transfer control to a peer by returning
Command(goto=peer, update=...). Here the generic on-call agent hands payments problems to the payments expert.

Run:  python steps/step07_handoff.py
"""

import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from m04_crew.tools import Toolbox


class S(TypedDict, total=False):
    log: Annotated[list[str], operator.add]


def build(tb: Toolbox):
    def oncall(state) -> Command[Literal["payments_expert", "__end__"]]:
        faults = tb.changes()["active_faults"]
        if "payments" in faults:
            return Command(goto="payments_expert", update={"log": ["oncall: payments involved -> hand off"]})
        return Command(goto=END, update={"log": ["oncall: handled, nothing for payments"]})

    def payments_expert(state) -> dict:
        return {"log": [f"payments_expert: fault {tb.changes()['active_faults']['payments']}; owns the fix"]}

    g = StateGraph(S)
    g.add_node("oncall", oncall)
    g.add_node("payments_expert", payments_expert)
    g.add_edge(START, "oncall")
    g.add_edge("payments_expert", END)
    return g.compile()


if __name__ == "__main__":
    for scenario in ("healthy", "payments-outage"):
        print(scenario, "->", build(Toolbox("fixture", scenario)).invoke({})["log"])
