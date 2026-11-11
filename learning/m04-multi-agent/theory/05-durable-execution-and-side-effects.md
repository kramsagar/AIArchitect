# 5. Durable execution, replay and side effects

A checkpoint is written **after** each super-step. If the process dies *inside* a node, that node runs again on resume. So:
- **Node = unit of retry.** Keep nodes small, and put each side effect in its own node (`executor`) so a crash elsewhere never repeats it.
- **Side effects must be idempotent.** `executor` builds the key `thread:action:target:attempt` and checks it twice: in the state (`executed`) and in the tool (`Toolbox.writes`). In production the downstream API takes an `Idempotency-Key` header. The payments service in the lab does this for charges.
- **Crash drill** (`m04 run --crash-before verifier`, then `m04 resume`): the executor's checkpoint already exists, so the reset is **not** repeated. The run continues at `verifier`.
- **Bounded loops:** `verifier → planner` retries at most `MAX_REMEDIATION_ATTEMPTS` times. Then it goes to the postmortem with `remediation_failed`, and a human takes over. An unbounded remediation loop is an outage multiplier.
- **Replay vs re-execute:** `get_state_history` lets you inspect or fork from an old checkpoint. Forking re-runs nodes *after* that point, side effects included. Treat that like re-running a deploy.
- **Verify against the SLO, not the action's return code.** A `200` from the chaos API means the change was applied, not that users have recovered. The verifier checks the fault state and the alerts, and says when the alert windows (5m/1h) are still catching up.
