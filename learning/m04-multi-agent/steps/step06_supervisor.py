"""Step 6 - the supervisor pattern: an LLM picks the next worker after every step (Command(goto=...)).
Compare the LLM-call count with the fixed workflow. The choice is validated and the loop is bounded.

Run:  python steps/step06_supervisor.py
"""

from common import llm, tools

from m04_crew.crew import Crew
from m04_crew.supervisor import build_supervisor_graph

if __name__ == "__main__":
    crew = Crew(tools(), llm())
    out = build_supervisor_graph(crew, max_turns=7).invoke({"alert": "checkout latency SLO"})
    for t in out["timeline"]:
        print(f"[{t['agent']:<10}] {t['event']}")
    print(f"\nLLM calls: {crew.llm.calls} (the fixed workflow reaches RCA with 1)")
