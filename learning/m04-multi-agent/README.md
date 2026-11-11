# Module 4 – Multi-agent incident-response crew (LangGraph)

A crew of specialist agents that handles a ShopSphere incident end to end. It stops for a **human approval** before
it changes anything, and every step is **checkpointed** (SQLite or Postgres), so a crash or a long wait for approval
loses nothing.

```
                 ┌─> metrics ──┐
                 ├─> traces ───┤
alert ─> triage ─┼─> logs ─────┼─> rca ─> planner ─> approval ─┬─> executor ─> verifier ─┬─> postmortem
   (healthy: END)├─> changes ──┤          ^   (LLM)  interrupt()│ (reset_faults)          │
                 └─> knowledge ┘          └────── bounded retry (max 2) ─────────────────┘
                                                    rejected / escalated ───────────────────> postmortem
```
- **Deterministic code** does what must be exact: triage picks the worst service by burn rate, the investigators call the M2 backends and the M3 retriever, the executor enforces an action allowlist and idempotency keys.
- **The LLM** (Claude, or a deterministic mock) does what needs judgement: the root cause, the plan and the postmortem.

## Setup (Windows PowerShell)
```powershell
cd learning\m04-multi-agent
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ..\m01-llm-agent-engineering -e ..\m02-rag-memory-mcp -e ..\m03-agentic-rag -e ".[dev,postgres]"
copy ..\m01-llm-agent-engineering\.env .env          # ANTHROPIC_API_KEY=...
pytest -q                                            # 22 tests, offline
```

## Run it
```powershell
m04 run --approve --postmortem                       # offline fixture world, mock LLM, free
m04 --scenario payments-outage run                   # asks you: approve? [y/N]
m04 run --pause                                      # stops at approval; prints the resume command
m04 resume --thread inc-xxxx --approve               # ...from any later process
m04 run --approve --crash-before verifier            # simulated crash, then:
m04 resume --thread inc-xxxx --approve               # continues; the executor is NOT repeated
m04 history --thread inc-xxxx                        # every checkpoint
m04 graph                                            # Mermaid diagram (paste into https://mermaid.live)
m04 supervisor                                       # the same crew under an LLM supervisor (compare LLM calls)
```
Against the live lab, with Claude, and with Postgres checkpoints:
```powershell
cd ..\..\lab; docker compose up -d                   # Postgres is now exposed on 127.0.0.1:55432
curl.exe -X POST localhost:8080/api/chaos/scenarios/payments-outage
# wait ~2 minutes for the alerts, then:
cd ..\learning\m04-multi-agent
$env:M04_CHECKPOINT = "postgresql://shop:shop@localhost:55432/shop"
m04 --backend live --provider anthropic run "payments errors page" --postmortem
```

### A real run (live lab, Claude Haiku, `payments-outage` chaos)
```
[triage    ] sev2: errors on payments-service; firing=['ShopSphereErrorBudgetFastBurn']
[metrics   ] 3 slow routes            [changes   ] active changes: ['payments']
[knowledge ] runbooks: ['postmortems#pm-2026-10-payments-outage', ...]
[traces    ] 2 traces on payments-service           [logs      ] 3 ERROR log lines
[rca       ] [high] payments-service is down (rps 0, error ratio 1.0) following a change recorded as down ...
[planner   ] reset_faults payments: ... Rolling back the payments fault is the only allowed action ...
>>> HUMAN APPROVAL NEEDED: reset_faults(payments) risk=medium
[approval  ] APPROVED by ubuntu
[executor  ] reset_faults(payments) -> PUT /api/chaos/payments -> 200
[verifier  ] mitigated: fault_cleared=True firing=['ShopSphereErrorBudgetFastBurn']
status=mitigated severity=sev2 llm_calls=3 writes=1
```
The status is `mitigated`, not `recovered`, because the fault is gone but the burn-rate alert uses 5m/1h windows and is still catching up. The verifier checks the SLO, not the API's `200`.

## Files
| File | Role |
|---|---|
| `src/m04_crew/state.py` | `IncidentState` with reducers (`merge_evidence`, `operator.add`); `RootCause` and `Plan` contracts |
| `src/m04_crew/tools.py` | `Toolbox`: M2 backends (fixture/live), M3 hybrid runbook search, and the one write, `reset_faults` (idempotent, allowlisted) |
| `src/m04_crew/crew.py` | the specialists: triage, 5 investigators, rca, planner, approval (`interrupt`), executor, verifier, postmortem; routing functions |
| `src/m04_crew/graph.py` | the production workflow graph: fan-out, join, conditional edges, bounded retry loop |
| `src/m04_crew/supervisor.py` | the same workers under an LLM supervisor (`Command(goto=...)`), validated and bounded |
| `src/m04_crew/checkpoint.py` | `memory`, SQLite or Postgres checkpointer from one URL |
| `src/m04_crew/llm.py` | Claude (via M3) or the deterministic `MockCrewLLM` |
| `src/m04_crew/cli.py` | `m04 run / resume / history / graph / supervisor` |
| `theory/` | 6 notes: workflow vs agent, patterns, state and checkpoints, HITL, durable execution, production |
| `steps/` | 12-step build-it-yourself track, see [steps/README.md](steps/README.md) |

## Theory
1. [Workflow vs agent vs multi-agent, and when not to](theory/01-workflow-vs-agent-vs-multi-agent.md)
2. [Supervisor, hierarchical, swarm/hand-off](theory/02-patterns-supervisor-hierarchical-handoff.md)
3. [State graphs, reducers, checkpoints](theory/03-state-reducers-checkpoints.md)
4. [Human-in-the-loop interrupts](theory/04-human-in-the-loop.md)
5. [Durable execution, replay and side effects](theory/05-durable-execution-and-side-effects.md)
6. [Multi-agent in production](theory/06-production-multi-agent.md)

**Measured lesson:** the fixed workflow reaches a conclusion with **1** LLM call (3 for the whole incident). The supervisor needs **7** just to reach RCA. Use the LLM where it decides something, not to route a procedure you already know.
