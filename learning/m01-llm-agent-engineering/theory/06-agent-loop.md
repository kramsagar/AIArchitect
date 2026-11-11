# 6. The agent loop: Observe → Decide → Act → Observe

> Lab: `python -m m01_agent.labs.l06_agent_loop` · Code: `agent.py: Agent.run`

```
          +-----------------------------------------------+
          v                                               |
 OBSERVE (context: instructions+state+memory+evidence)   |
          |                                               |
 DECIDE  (LLM: final answer OR tool calls)               |
          |                         |                     |
          | final                   | tool calls          |
          v                         v                     |
 VALIDATE (Pydantic) --bad--> repair    ACT (registry: validate, timeout, retry, breaker)
          |                                   |           |
          v                                   +-- results appended as observations
        RETURN
```

An agent = **LLM + tools + loop + state + stopping conditions**. Remove the stopping conditions and you have a cost and outage generator.

## Stopping conditions (all enforced in `Agent.run`)
- Final valid answer.
- `max_steps` (LLM turns) and `max_tool_calls` (budget).
- End-to-end deadline (`run_timeout_s`): latency SLO for the agent itself.
- Duplicate-call guard: same tool + same args = loop; return a `duplicate_call` observation instead.
- Repair limit for invalid output.
- Every exit returns a valid `AssistantResponse` with a `status`, never an exception to the caller.

## Workflow vs agent
| | Workflow (deterministic) | Agent (model chooses) |
|---|---|---|
| Control flow | code | LLM |
| Predictability, latency | high, low | lower, higher |
| Use when | steps known (alert → fetch → classify) | steps depend on findings (RCA) |

Rule: **use the least autonomy that solves the problem**. Many "agents" in production are workflows with one or two LLM decisions. Module 4 (LangGraph) mixes both.

## Agent SDKs
`sdk_agent.py` builds the same agent with the OpenAI Agents SDK (`Agent`, `function_tool`, `Runner`, `output_type`). The SDK gives you the loop, handoffs, guardrails, sessions and tracing; the hand-written loop shows you what it does underneath. Learn the loop, then use the SDK.

## Check yourself
1. Trace "Can checkout-api handle 2x traffic?" step by step. Why are two LLM→tool hops needed?
2. Which stopping condition protects your bill? Which protects your latency SLO?
