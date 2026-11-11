# 2. Multi-agent patterns: supervisor, hierarchical, swarm/hand-off

```
Supervisor                 Hierarchical                       Swarm / hand-off
   [supervisor]            [incident commander]               [triage] --handoff--> [payments expert]
   /   |   |   \             /               \                    ^                       |
 [chg][trc][log][rca]   [investigation lead] [ops lead]           +-------handoff---------+
                          /    |    \          |    \
                       [trc] [log] [chg]  [planner][executor]
```
- **Supervisor** (`m04_crew.supervisor`): one LLM router picks the next worker after every step, and workers always come back to it.
  - Flexible, but it costs N extra LLM calls, and the path can wander.
  - Production rules: bound it with `max_turns`, **validate the choice** against the worker list (the model can name a worker that doesn't exist), and force a conclusion (`rca`) before FINISH.
- **Hierarchical:** supervisors of supervisors. A sub-graph is compiled and used as a node of the parent graph. This scales to large teams, and each team keeps its own state schema.
- **Swarm / hand-off** (step 7): an agent returns `Command(goto="other_agent", update={...})`. There's no central router, and control moves like a phone transfer. It suits conversational routing (L1 → L2 support). It's harder to reason about, so log every hand-off.
- **Workflow with LLM nodes** (`m04_crew.graph`, the production choice here): edges are fixed, and conditional edges are pure functions of state. Only the content of a node uses the LLM.

Measured in this repo (`m04 run` vs `m04 supervisor`, mock LLM):
- **Workflow:** 3 LLM calls per incident (rca, plan, postmortem).
- **Supervisor:** 7 calls just to reach RCA (6 routing calls + rca).
- **Live Claude:** each routing call adds about 1–2 s.
