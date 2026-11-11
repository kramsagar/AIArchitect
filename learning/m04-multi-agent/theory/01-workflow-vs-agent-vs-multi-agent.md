# 1. Workflow vs agent vs multi-agent, and when *not* to go multi-agent

| | Workflow | Agent | Multi-agent |
|---|---|---|---|
| Who picks the next step | your code (fixed edges) | the LLM, in a loop | several LLM roles, plus a router or the edges |
| Predictability | high: same path every time | medium | lowest, unless the graph constrains it |
| Cost / latency | lowest | one LLM call per step | one call per agent and per routing hop |
| Debugging | read the code | read the trace | read the trace *and* the hand-offs |
| Use it when | the procedure is known (an incident runbook) | the path depends on what you find | roles need different tools, prompts, permissions or models |

Anthropic's "Building effective agents" puts it simply: start with the simplest thing that works. Most "multi-agent"
production systems are really **workflows with a few LLM-powered nodes**, and that's what `m04_crew.graph` is:
- **Deterministic** where it has to be exact: triage picks the worst service by burn rate, the investigators call APIs, the executor enforces an allowlist.
- **LLM** where judgement is needed: RCA, the plan, the postmortem.

**Reasons to split into several agents:**
1. **Separation of permissions.** Only the executor can write. The investigators are read-only. This is least privilege per agent, which matters more in M8.
2. **Focused context.** Each specialist sees only its own payload, never one 50k-token conversation.
3. **Parallelism.** Five investigators run in the same super-step, so wall-clock time ≈ the slowest one, not the sum.
4. **Independent evolution.** A different model or prompt per role, evaluated separately (M6).

**Reasons not to:**
- Each hop adds latency, tokens and another place for errors to compound (0.95⁵ ≈ 0.77).
- Agents that "chat" freely loop and cost money.
- A shared state that nobody owns.

Rule: if you can draw the procedure as a flowchart, build a workflow. Only let an LLM choose an edge where the flowchart really has a judgement diamond.
