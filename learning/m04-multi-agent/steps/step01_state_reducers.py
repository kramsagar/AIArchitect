"""Step 1 - LangGraph state and reducers. Two nodes run in parallel and both write `evidence`.
Without a reducer LangGraph refuses (concurrent writes to one key); with `operator.add` both writes are kept.

Run:  python steps/step01_state_reducers.py
"""

import operator
from typing import Annotated, TypedDict

from langgraph.errors import InvalidUpdateError
from langgraph.graph import START, StateGraph


class NoReducer(TypedDict):
    evidence: list[str]


class WithReducer(TypedDict):
    evidence: Annotated[list[str], operator.add]  # reducer: how to combine two writes


def traces(state):
    return {"evidence": ["trace: payments-service authorize 2.1s"]}


def logs(state):
    return {"evidence": ["log: WARN payment authorize slow"]}


def build(schema):
    g = StateGraph(schema)
    g.add_node("traces", traces)
    g.add_node("logs", logs)
    g.add_edge(START, "traces")  # two edges from START = both run in the same super-step
    g.add_edge(START, "logs")
    return g.compile()


if __name__ == "__main__":
    try:
        build(NoReducer).invoke({"evidence": []})
    except InvalidUpdateError as exc:
        print("without reducer ->", type(exc).__name__, str(exc).splitlines()[0][:90])
    print("with reducer    ->", build(WithReducer).invoke({"evidence": []})["evidence"])
