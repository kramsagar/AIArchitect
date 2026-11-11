# 6. Multi-agent in production: latency, cost, failure modes

**Latency budget per incident (live Claude Haiku, measured in this repo):**
- Triage and the 5 parallel investigators: deterministic API calls, about 0.2–1 s against the lab, gated by the slowest backend.
- RCA, plan and postmortem: 3 LLM calls, about 2–6 s each with Claude.
- The human approval dominates wall-clock time. That's why durable state matters more than raw speed here.

**Failure modes and the guard for each:**
| Failure | Guard in this module |
|---|---|
| a backend is down during investigation | each investigator is independent; M2's retries, timeouts and circuit breakers; RCA works with whatever evidence arrived |
| the LLM hallucinates evidence | RCA `evidence_ids` are grounded against the evidence list, and confidence is lowered |
| the LLM proposes a dangerous action | `Plan.action` is a `Literal` allowlist; policy refuses targets with no active fault |
| routing loops (supervisor) | `max_turns`, choice validation, forced conclusion |
| crash mid-remediation | checkpoints and idempotency keys |
| remediation doesn't help | verifier, bounded retry, then escalate |
| concurrent writes to state | reducers |

**Scaling out (M5, M9):**
- Run the graph in workers that pull incidents from a queue.
- Share a Postgres checkpointer.
- Use one `thread_id` per incident.
- Expose `resume` behind an authenticated API.
- Split specialists into separate services with A2A (M5) when they need their own deployment, scaling or ownership.
