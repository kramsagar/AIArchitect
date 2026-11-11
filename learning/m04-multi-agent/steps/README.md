# Module 4 – step by step

Same pattern as Modules 1–3. For each step:
1. **Run it** (`python steps\stepNN_*.py`, from `learning\m04-multi-agent`).
2. **See what's new** with `git diff --no-index steps\<previous> steps\<this>`.
3. **Build it yourself** in `steps\my_crew.py`.
4. **Check yourself** with the questions.

All steps run offline. Steps 5, 6 and 11 use Claude when `ANTHROPIC_API_KEY` is set (`$env:M04_OFFLINE="1"` forces the mock). Steps 10 and 11 reset real lab chaos with `$env:OBS_BACKEND="live"`.

| Step | Idea | Build it yourself | Check yourself |
|---|---|---|---|
| 0 `workflow_in_python` | a workflow is functions passing a dict | write triage → investigate → conclude as three functions | What can't this do? (branch, parallel, pause, survive a crash) |
| 1 `state_reducers` | parallel writes need a reducer | make two nodes write one key; see the `InvalidUpdateError`; add `Annotated[list, operator.add]` | Why is "last writer wins" worse than an error? |
| 2 `first_graph` | `StateGraph`, nodes, edges, `stream` | port step 0 to LangGraph; nodes return only what changed | What does `stream_mode="updates"` show that `invoke` doesn't? |
| 3 `conditional_edges` | a pure function picks the next node | route healthy → END, errors → error path, latency → latency path | Why keep routing functions free of LLM calls and side effects? |
| 4 `parallel_fanout` | fan-out + join barrier | 5 investigators from triage, `add_edge([...], "join")` | Why is elapsed ≈ the slowest investigator? |
| 5 `llm_specialist` | an LLM node with a contract + grounding | RCA returns `RootCause`; drop ids no investigator produced | What happens to confidence when an id is invented? |
| 6 `supervisor` | an LLM router (`Command(goto=)`) | add a supervisor; validate its choice; cap turns | Count the LLM calls: is the flexibility worth it here? |
| 7 `handoff` | swarm / peer hand-off | on-call hands payments faults to a payments expert | Where would you log hand-offs, and why? |
| 8 `checkpoints` | `SqliteSaver`, `thread_id`, history | compile with a checkpointer; print `get_state_history` | What is saved, and when? (after each super-step) |
| 9 `human_approval` | `interrupt()` + `Command(resume=)` | pause before the executor; approve and reject | Why does code before `interrupt()` run twice? |
| 10 `executor_verify` | idempotent write + verify + bounded retry | key = `thread:action:target:attempt`; verify the fault state and alerts | Why verify the SLO and not the HTTP 200? |
| 11 `full_crew` | everything = `m04_crew.graph` | wire all of it; crash before the verifier; resume | Which node re-runs after the crash, and which must not? |

**Map to production:** steps 1–4 → `state.py` + `graph.py`; step 5 → `Crew.rca`; step 6 → `supervisor.py`; steps 8–9 → `checkpoint.py` + `Crew.approval`; step 10 → `tools.reset_faults` + `Crew.executor/verifier`; step 11 → `m04 run`.
