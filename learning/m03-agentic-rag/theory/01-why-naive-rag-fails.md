# 1. Why naive RAG fails in operations

Naive RAG is `embed(question) -> top-k -> stuff into prompt -> answer`. On-call questions break it in four ways:

| Failure | Example (ShopSphere) | Why naive RAG misses | Fix (this module) |
|---|---|---|---|
| **Vocabulary mismatch** | "the purchase flow is sluggish" | docs say *checkout latency* | query rewriting, HyDE (`rewrite.py`) |
| **Exact identifiers** | "PG-53300 in the logs", trace ids, metric names | embeddings blur rare tokens | BM25 + hybrid fusion (`bm25.py`, `hybrid.py`) |
| **Relationships** | "what breaks if redis fails?" | similarity can't follow edges | service graph (`graph.py`) |
| **Multi-part questions** | "too many db connections *and* what pool size?" | one query vector for two needs | decomposition (`rewrite.decompose`) |

Two more failures happen at answer time:
- **Bad retrieval goes unnoticed.** The model answers from whatever came back. Fix: grade the retrieval and try again (`grader.py`, `crag.py`).
- **Ungrounded citations.** The model cites ids it never saw. Fix: check citations against the tool outputs (`agent._ground`).

**Agentic RAG** makes retrieval a *decision*. The model chooses whether to search, how (strategy, filters), whether the results are good enough, and when to stop.
That costs latency and tokens, so the design goal is to *use the cheap path by default and escalate only when needed*.

Cost and latency ladder, per query, measured by `m03 eval` (`ms_per_query`, `llm_calls`):
`bm25 (~0.1 ms) < vector (~1 ms) < hybrid (~1 ms) < +rerank (~2 ms) < corrective (1-4 LLM calls, 1-5 s with Claude)`.
