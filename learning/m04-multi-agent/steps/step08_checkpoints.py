"""Step 8 - checkpoints: the same graph compiled with a SqliteSaver. Every super-step is saved under a thread_id,
so you can inspect state, list history, and continue later from another process.

Run:  python steps/step08_checkpoints.py
"""

import sqlite3

from common import tools
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph  # noqa: E402,I001
from step02_first_graph import S, conclude, investigate, triage

_ = tools


def build(saver):
    g = StateGraph(S)
    for fn in (triage, investigate, conclude):
        g.add_node(fn.__name__, fn)
    g.add_edge(START, "triage")
    g.add_edge("triage", "investigate")
    g.add_edge("investigate", "conclude")
    g.add_edge("conclude", END)
    return g.compile(checkpointer=saver)


if __name__ == "__main__":
    saver = SqliteSaver(sqlite3.connect("step08.db", check_same_thread=False))
    app = build(saver)
    cfg = {"configurable": {"thread_id": "inc-step08"}}
    app.invoke({}, cfg)
    snap = app.get_state(cfg)
    print("values :", snap.values)
    print("next   :", snap.next, "(empty = finished)")
    print("history (newest first):")
    for s in app.get_state_history(cfg):
        print(
            f"  step={s.metadata['step']:>2} next={list(s.next)} writes={list((s.metadata.get('writes') or {}).keys())}"
        )
    print("\nRun it again: the thread keeps its state in step08.db; a new thread_id starts fresh.")
