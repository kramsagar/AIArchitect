"""Step 10 - act and verify: the executor performs the ONE allowed write (reset_faults) with an idempotency key,
the verifier checks the fault state and alerts (not the API's return code), and a bounded loop retries or gives up.

Run:  python steps/step10_executor_verify.py      ($env:OBS_BACKEND="live" to reset real lab chaos)
"""

from common import tools

MAX_ATTEMPTS = 2


def execute(tb, target: str, key: str) -> str:
    return tb.reset_faults(target, key)["result"]


def verify(tb, target: str) -> dict:
    return {
        "fault_cleared": target not in tb.changes()["active_faults"],
        "firing": [a["alert"] for a in tb.alerts()["firing"]],
    }


if __name__ == "__main__":
    tb = tools()
    faults = tb.changes()["active_faults"]
    print("active faults:", faults)
    target = next(iter(faults), None)
    if not target:
        raise SystemExit("nothing to remediate (set OBS_FIXTURE_SCENARIO=payments-outage, or apply chaos in the lab)")
    for attempt in range(MAX_ATTEMPTS):
        key = f"inc-step10:reset_faults:{target}:{attempt}"
        print(f"attempt {attempt}: {execute(tb, target, key)}")
        print(f"  same key again: {execute(tb, target, key)}  <- idempotent, no second write")
        v = verify(tb, target)
        print("  verify:", v)
        if v["fault_cleared"]:
            break
    print("writes performed:", tb.writes)
