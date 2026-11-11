"""Step 0 - a workflow is just functions passing a dict. No framework, no LLM. This is the baseline every later step
improves on: triage -> investigate -> conclude, in plain Python.

Run:  python steps/step00_workflow_in_python.py
"""

from common import tools


def triage(state: dict) -> dict:
    slo = state["tools"].slo()["services"]
    svc = max(slo, key=lambda s: (slo[s].get("burn_rate_1h") or 0) + (slo[s].get("p95_ms") or 0) / 500)
    return {**state, "focus": svc, "evidence": [f"slo:{svc} {slo[svc]}"]}


def investigate(state: dict) -> dict:
    faults = state["tools"].changes()["active_faults"]
    return {**state, "evidence": state["evidence"] + [f"change:{s} {c}" for s, c in faults.items()]}


def conclude(state: dict) -> dict:
    changes = [e for e in state["evidence"] if e.startswith("change:")]
    verdict = f"likely cause: {changes[0]}" if changes else "no change found, escalate"
    return {**state, "verdict": verdict}


if __name__ == "__main__":
    state = {"tools": tools()}
    for step in (triage, investigate, conclude):  # the "graph" is this list: fixed order, no branches
        state = step(state)
        print(f"after {step.__name__:<11} keys={sorted(k for k in state if k != 'tools')}")
    print("\nfocus:", state["focus"])
    print("verdict:", state["verdict"])
    print("\nLimits: no branching, no parallelism, no pause for a human, and a crash loses everything.")
