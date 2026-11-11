"""Step 11 - the full crew (= m04_crew.graph): triage -> 5 parallel investigators -> RCA -> planner -> human
approval -> executor -> verifier -> postmortem, checkpointed in SQLite, with a simulated crash and resume.

Run:  python steps/step11_full_crew.py            (then try: m04 run --pause ; m04 resume --thread ... --approve)
"""

from common import llm, tools
from langgraph.types import Command

from m04_crew.checkpoint import open_checkpointer
from m04_crew.crew import Crew
from m04_crew.graph import build_graph


def run(crash_before: str | None = "verifier", db: str = "step11.db", thread: str = "inc-step11") -> dict:
    crew = Crew(tools(), llm(), crash_before=crash_before)
    with open_checkpointer(db) as saver:
        app = build_graph(crew, checkpointer=saver)
        cfg = {"configurable": {"thread_id": thread}}
        app.invoke({"alert": "ShopSphereCheckoutLatencySLO"}, cfg)  # stops at the approval interrupt
        print("paused at:", app.get_state(cfg).next, "plan:", app.get_state(cfg).values["plan"]["action"])
        try:
            app.invoke(Command(resume={"approved": True, "by": "alice"}), cfg)
        except RuntimeError as exc:
            print("CRASH:", exc, "| checkpoint says next =", app.get_state(cfg).next)
            app.invoke(None, cfg)  # resume from the last checkpoint: executor is NOT repeated
        final = app.get_state(cfg).values
    for t in final["timeline"]:
        print(f"  [{t['agent']:<10}] {t['event']}")
    print(f"\nstatus={final['status']} writes={len(crew.tools.writes)} llm_calls={crew.llm.calls}")
    return final


if __name__ == "__main__":
    import os

    if os.path.exists("step11.db"):
        os.remove("step11.db")
    print(run()["postmortem"][:600])
