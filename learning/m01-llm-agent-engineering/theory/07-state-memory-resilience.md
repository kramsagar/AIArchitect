# 7. Agent state, memory, retries and timeouts

> Lab: `python -m m01_agent.labs.l07_resilience` · Code: `memory.py`, `resilience.py`, `telemetry.py`

## State vs memory
- **Run state** (per request): messages, steps, tool calls, budgets, deadline → `AgentResult.steps` / `Usage`. Dies with the request.
- **Session memory** (per conversation): recent turns + extracted facts (`last_service`). `ConversationMemory` keeps it bounded by turns and tokens.
- **Long-term memory** (per user/org): past incidents, preferences, runbooks; lives in a database/vector store (module 2).

Stateless services scale horizontally; keep memory **outside the process** (Redis/Postgres) in production (module 9). Module 1 keeps it in-process to stay simple.

## Timeouts (the most important reliability setting)
- Every external call has one: LLM call, tool call, whole run.
- Budget them: `run_timeout_s ≥ steps × (llm_timeout + tool_timeout)` is a *bad* sign; prefer a **deadline** that shrinks each step's timeout (`Deadline.remaining()`).
- Python threads can't be killed: a timed-out worker keeps running. Real clients (httpx, DB drivers) must receive the timeout themselves.

## Retries
- Only transient errors (timeouts, 429, 5xx); never validation/4xx.
- Exponential backoff with **full jitter** (`random(0, base·2^n)`) avoids synchronised retry storms.
- Small retry counts (1–3) and a **retry budget**; retries multiply load: 3 layers × 3 retries = 27× traffic on a sick dependency.
- Respect the deadline: don't start a retry you can't finish.

## Circuit breaker
closed → (N failures) → open (fail fast) → (reset timeout) → half-open (one probe) → closed/open.
Protects the dependency and your latency: failing in 1 ms beats timing out in 2 s at 10k RPS.

## Caching
TTL cache on idempotent reads (health metrics with 5 s TTL). At high TPS many agents ask the same question; a cache turns N backend queries into 1. Watch staleness vs freshness requirements.

## Observability of the agent itself
Every run emits spans (`agent.run`, `llm.decide`, `tool.<name>`) with latency, status, attempts and tokens. `m01-agent bench` reports throughput and p50/p95/p99. Module 7 exports this with OpenTelemetry GenAI semantic conventions.

## Check yourself
1. Run `m01-agent bench --tool-latency-ms 50 --failure-rate 0.2`. What happens to p99? Now raise `--concurrency`.
2. Why is retrying an LLM call that returned invalid JSON different from retrying a 503?
