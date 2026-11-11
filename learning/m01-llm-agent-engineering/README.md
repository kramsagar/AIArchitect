# Module 1: LLM & Agent Engineering (SRE Copilot)

Level 1 (Foundations) of the [Agentic AI Architect program](../ROADMAP.md).
Deliverable: a **single-agent SRE copilot with two tools**, strict structured output and production-style resilience.
It runs fully offline in mock mode, or against **Claude** (default) or OpenAI.

```
user ──> Agent.run ──> OBSERVE (system+developer+state+memory+user) ──> DECIDE (LLM)
              ^                                                         │
              │                       final ──> Pydantic validate ──> repair? ──> AssistantResponse
              │                       tool_calls
              └── observations <── ACT: ToolRegistry (validate · timeout · retry+jitter · circuit breaker · TTL cache · spans)
                                         ├─ get_service_health   (mock Prometheus/APM: RPS, p50/p95/p99, errors, saturation, SLOs, deps)
                                         └─ capacity_calculator  (safe AST: error budget, burn rate, Little's law, replicas, availability)
```

## Study plan (about 4 hours)
| # | Topic | Theory | Lab |
|---|---|---|---|
| 1 | Tokens, context window, embeddings, temperature | [01](theory/01-llm-architecture.md) | `python -m m01_agent.labs.l01_llm_basics` |
| 2 | System, developer and user instructions | [02](theory/02-instruction-hierarchy.md) | `python -m m01_agent.labs.l02_instruction_roles` |
| 3 | Prompt engineering vs context engineering | [03](theory/03-prompt-vs-context-engineering.md) | `python -m m01_agent.labs.l03_context_engineering` |
| 4 | Structured output with Pydantic | [04](theory/04-structured-output.md) | `python -m m01_agent.labs.l04_structured_output` |
| 5 | Function calling and tool schemas | [05](theory/05-function-calling.md) | `python -m m01_agent.labs.l05_function_calling` |
| 6 | Agent loop: Observe → Decide → Act → Observe | [06](theory/06-agent-loop.md) | `python -m m01_agent.labs.l06_agent_loop` |
| 7 | State, memory, retries, timeouts | [07](theory/07-state-memory-resilience.md) | `python -m m01_agent.labs.l07_resilience` |

Reading: [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/), then compare it with `src/m01_agent/sdk_agent.py`.

## Setup
```bash
cd learning/m01-llm-agent-engineering
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                                 # add ,sdk for the Agents SDK
```

## Run the deliverable
```bash
m01-agent ask "Is checkout-api healthy?" --trace
m01-agent ask "Can checkout-api handle 2x traffic?" --trace      # two hops: health -> replicas
m01-agent ask "Compare payments-gateway and search-api"           # parallel tool calls
m01-agent ask "Error budget for 99.95% over 30 days"
m01-agent ask "Is billing-api healthy?"                          # tool error handled
m01-agent chat                                                    # session memory: "is search-api ok?" then "can it handle 3x?"
m01-agent schemas                                                 # exactly what the model sees
m01-agent bench --requests 500 --concurrency 32 --tool-latency-ms 20 --failure-rate 0.1
m01-agent -v ask "Is auth-service healthy?"                       # JSON span logs on stderr
```

With Claude (put `ANTHROPIC_API_KEY` in your environment; see `.env.example`):
```bash
m01-agent --provider anthropic ask "Can checkout-api handle 2x traffic?" --trace
m01-agent --provider anthropic --model claude-haiku-5-5 bench --requests 20 --concurrency 4
pip install -e ".[sdk]" && m01-agent --provider anthropic ask "Is checkout-api healthy?" --sdk   # Agents SDK + LiteLLM
```
OpenAI works the same way with `--provider openai` and `OPENAI_API_KEY`.

### Claude vs OpenAI: what the adapter has to translate
| Concept | OpenAI Chat Completions | Anthropic Messages |
|---|---|---|
| Instructions | `system` / `developer` messages | top-level `system` parameter |
| Tool schema | `tools[].function.parameters` | `tools[].input_schema` |
| Tool call | `message.tool_calls[]` (JSON string args) | `tool_use` content block (object input) |
| Tool result | `role="tool"` message per call | `tool_result` blocks inside one `user` message |
| Structured output | `response_format.json_schema` | `output_config.format` json_schema |
Your agent loop stays provider-neutral; only `llm/*.py` changes. That is the seam that lets you add model routing and failover in module 10.

## Code map
| File | Concept |
|---|---|
| `schemas.py` | Pydantic contracts: tool args/results, `AssistantResponse`, traces |
| `jsonschema.py` | Pydantic → OpenAI strict JSON Schema |
| `prompts.py` | system vs developer instructions, repair prompt |
| `tools/` | the two tools + `ToolRegistry` (policy enforcement point) |
| `resilience.py` | timeout, retry with full jitter, deadline, circuit breaker, TTL cache |
| `memory.py` | bounded session memory + facts |
| `agent.py` | the loop, budgets, duplicate guard, repair, grounding, fail-closed fallbacks |
| `llm/mock.py`, `llm/anthropic_llm.py`, `llm/openai_llm.py` | deterministic offline model; Claude Messages API client; OpenAI client |
| `sdk_agent.py` | same agent on the OpenAI Agents SDK |
| `telemetry.py`, `cli.py bench` | spans, p50/p95/p99, throughput |

## Exercises
1. Add a third tool `get_recent_deploys(service)` and make the agent mention a deploy that correlates with the regression.
2. Make `checkout-api` flaky (`--failure-rate 0.5`) and tune retries vs breaker so p99 stays under 300 ms in `bench`.
3. Add a semantic rule: if `severity` is `ok` but the tool reported an SLO breach, reject the output and trigger repair.
4. Run the same 10 questions with `--provider anthropic` twice. Diff the answers. What is stable and what isn't?
5. Replace `ConversationMemory` with a Redis-backed implementation (preview of module 9).

## Done when
- [ ] You can explain every row of the theory table without notes.
- [ ] `pytest -q` is green and you can explain what each test protects against.
- [ ] You completed exercises 1–3.
