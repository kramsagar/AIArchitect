# 1. Why agent-to-agent (A2A)?

M4 ran every specialist in **one process**. That stops working when:

| Pressure | Example in ShopSphere |
|---|---|
| Different teams own different agents | Payments team ships its own `payments-diagnoser`; SRE owns the crew |
| Different stacks | knowledge-agent in Python, a vendor's APM agent in Java |
| Independent scaling / blast radius | telemetry-agent needs 10 replicas at peak; executor-agent exactly 1 |
| Least privilege | only executor-agent holds the credential that writes to production |

**MCP vs A2A** - they are complementary:
- **MCP** (M2) = agent ↔ *tool/data*. The tool is dumb; the agent decides. Synchronous function call semantics.
- **A2A** = agent ↔ *agent*. The callee is itself an agent with its own model, tools and policy, possibly long-running.
  The unit of work is a **Task** with a lifecycle, not a function return.

**When NOT to split into A2A agents:** one team, one deployable, latency-critical inner loop. Every hop adds
serialization, auth, network latency (measured here: ~40-230 ms per hop locally) and a new failure mode. Start in-process
(M4); extract an agent when ownership, scaling or privilege boundaries demand it.
