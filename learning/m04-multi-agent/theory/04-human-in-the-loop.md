# 4. Human-in-the-loop with interrupts

`Crew.approval` calls `interrupt({...plan...})`. LangGraph then:
1. saves a checkpoint with the interrupt payload,
2. returns to the caller (`result["__interrupt__"]`, `get_state(cfg).next == ("approval",)`), and
3. waits, for minutes or days. Nothing is running, and nothing is held in memory.

When `app.invoke(Command(resume={"approved": True, "by": "alice"}), cfg)` is called, the **approval node runs again from its first line**, and this time `interrupt()` returns the resume value.

Production rules:
- **Code before `interrupt()` runs twice.** Keep it free of side effects, or make it idempotent.
- **Approve a concrete, validated plan**, not free text. Here that's `Plan` (an allowlisted action, a target, risk, rationale and runbook), so the human approves exactly what will run.
- **Policy decides what needs a human.** `escalate` skips approval, `reset_faults` requires it. In M8 this becomes risk-based policy: auto-approve low risk in non-prod, require two approvers for prod and high risk.
- **Record who approved, and when**: `approval.by` goes into the timeline and the postmortem, which gives you the audit trail.
- **Reject is a first-class path**: the run goes to the postmortem with `status=rejected`, and nothing executes.
- In a real system the interrupt payload goes to Slack/PagerDuty or a UI, and the button click calls the resume API (M9).
