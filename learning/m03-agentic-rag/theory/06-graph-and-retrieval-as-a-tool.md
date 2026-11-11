# 6. GraphRAG and retrieval as a tool

**GraphRAG-lite** (`graph.py`): relationship questions need edges, not similarity. The graph is parsed from
`corpus/service-graph.md`, so the documentation stays the single source of truth and the parser test fails if someone breaks the format.
- `dependencies(s)` lists what `s` calls, `dependents(s)` lists who calls it, and `blast_radius(s)` uses BFS upstream to find what is impacted if `s` fails.
- `owners` maps each service to its team, on-call rotation and runbook, which answers "who do I page?".
Full GraphRAG extracts entities and relations from *all* documents with an LLM and summarises graph communities. Start with
the graph you already have (a service catalog, CMDB, tracing dependency graph) before building one with an LLM.

**Retrieval as a tool** (`agent.py`): the agent gets `search_knowledge(query, strategy, doc_type)`, `service_graph(service)`
and `read_chunk(chunk_id)`, and decides the plan itself. Real Claude traces from this module:
- "what is affected if redis fails and who is on call?" → `service_graph` and `search_knowledge` in parallel in one step, citing
  `service-graph#dependencies` and `#ownership`.
- "cart items vanish, what happened before?" → corrective search, then a reformulated search, then `read_chunk` on the incident, then a
  filtered postmortem search. The answer cites `incidents#inc-4251-redis-evictions`.

Production checklist: per-tool timeouts and result caps (8 KB here), a step limit (`max_steps`), citation grounding, a
refusal path, a trace per run (`agent.trace`), and offline evals in CI (`tests/test_m03.py::test_eval_baseline_does_not_regress`).
