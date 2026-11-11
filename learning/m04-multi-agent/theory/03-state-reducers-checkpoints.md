# 3. State graphs, reducers and checkpoints

**State** (`m04_crew.state.IncidentState`) is a TypedDict. Each node returns a *partial* update, and LangGraph merges it in.
- A plain key is **overwritten**: `status`, `plan`, `rca`.
- A key annotated with a **reducer** is **combined**:
  - `evidence: Annotated[list, merge_evidence]` appends and de-duplicates by id.
  - `timeline: Annotated[list, operator.add]` appends.

Why it matters: the five investigators run **in the same super-step** and all write `evidence`. Without a reducer, LangGraph raises `InvalidUpdateError` because there are concurrent writes to one key. With "last writer wins" you'd silently lose four agents' work. Step 1 shows both.

**Super-step:** every node that is ready runs, in parallel; then their updates are merged and a **checkpoint** is saved. `g.add_edge([a, b, c], "rca")` is a *barrier*: rca runs only after all of them have finished.

**Checkpointer** (`m04_crew.checkpoint`): it saves the full state after every super-step, keyed by `thread_id` (one incident = one thread).
- `InMemorySaver` for tests.
- `SqliteSaver` for one machine.
- `PostgresSaver` for many workers. The lab exposes Postgres at `localhost:55432` for this.

What checkpoints give you:
| Capability | API |
|---|---|
| resume after a crash | `app.invoke(None, cfg)` continues from the last checkpoint |
| human-in-the-loop | `interrupt()` saves state and returns; resume later, even from another process or pod |
| inspect | `app.get_state(cfg)`: values, `next` nodes, pending interrupts |
| audit / time travel | `app.get_state_history(cfg)`; re-run from any `checkpoint_id` |
