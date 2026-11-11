# 5. Function calling and tool schemas

> Lab: `python -m m01_agent.labs.l05_function_calling` · Code: `tools/`, `tools/registry.py`

## How it works
1. You send tool **schemas** (name, description, JSON Schema params).
2. The model returns `tool_calls` (name + JSON arguments): it **never executes anything**.
3. Your code validates, authorises, executes with timeouts, and returns results as `role="tool"` messages.
4. The model reads the results and either calls more tools or answers.

The model is an untrusted planner; your registry is the **policy enforcement point**.

## Good tool design (it is API design for a model)
- Name = verb_noun, description says *when* to use it and what it returns ("Returns golden signals... Use before any health or capacity judgement").
- Narrow, typed params; enums and patterns (`service: ^[a-z0-9-]{2,40}$`). Fewer params → fewer mistakes.
- Compact, labelled outputs with units (`p99_ms`, `error_rate_pct`).
- Idempotent reads first; writes need dry-run, approval and audit (module 4, 8).
- Return **errors as data** (`{"ok": false, "error_type": "timeout", ...}`) so the model can recover or explain, instead of crashing the loop.
- Never `eval()` model output. `capacity_calculator` parses an AST allow-list.

## Registry responsibilities (production checklist)
| Concern | Module 1 implementation |
|---|---|
| Unknown tool (hallucination) | `unknown_tool` observation |
| Malformed JSON / schema violation | Pydantic validation → `invalid_arguments` |
| Slow dependency | per-tool timeout |
| Flaky dependency | retries with exponential backoff + full jitter, only for transient errors |
| Hard-down dependency | circuit breaker (fail fast, protect the dependency) |
| Hot reads at high TPS | TTL cache on idempotent tools |
| Observability | span per tool call, metrics, attempts, latency |
| Authorisation | (module 8: RBAC per tool) |

## Parallel tool calls
Models can emit several calls in one turn ("compare A and B"). Execute independent reads concurrently to cut latency.

## Check yourself
1. Which errors should be retried? Which never?
2. Why do retries without a circuit breaker make outages worse at high TPS?
