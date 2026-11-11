# 4. Resilience and production concerns for A2A

| Failure | Mitigation in this module | Production next step |
|---|---|---|
| Agent down | timeout + bounded jittered retries (`RetryPolicy`) | circuit breaker per agent (M1), health-checked registry |
| Slow agent | per-hop timeout | deadline propagation, async tasks + `GetTask` polling / push notifications |
| Partial outage of an investigator | graceful degradation: proceed with less evidence, record DEGRADED | RCA lowers confidence when evidence sources are missing |
| Retry duplicates a write | idempotency key travels with the request, checked in the executor | durable dedupe store (Redis/Postgres) shared by replicas |
| Wrong agent asked to do a privileged skill | executor rejects unknown skills (`TASK_STATE_REJECTED`) | per-skill authZ (M8) |
| Contract drift | spec-typed cards + tests that read live cards | contract tests in CI, versioned skills |

**Where state lives.** Specialists are stateless; the orchestrator owns workflow state + checkpoints (LangGraph) and the
human approval gate. That keeps agents horizontally scalable and makes crash-resume a property of one component.

**Cost of the hop.** Local fixture run: 11 hops, 40-230 ms each. Parallel investigators overlap, so wall time ≈ the
critical path, not the sum. Measure before splitting (M10 goes deeper on latency budgets).
