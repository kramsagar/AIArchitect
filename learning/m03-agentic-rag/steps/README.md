# Module 3, step by step: agentic RAG

Same approach as the Module 1 and 2 steps. Each step has four parts:
- **Run it.**
- **What's new:** `git diff --no-index steps\stepNN... steps\stepMM...` shows only the new lines.
- **Build it yourself:** add the same layer to `steps\my_rag.py`.
- **Check yourself.**

Steps 5–8 and 10–11 use Claude if `ANTHROPIC_API_KEY` is set. Steps 5–8 fall back to an offline mock otherwise (`$env:M03_OFFLINE="1"` forces it). Steps 10–11 need Claude.

| Step | File | New idea | Theory |
|---|---|---|---|
| 0 | `step00_naive_rag.py` | naive RAG baseline, and the 4 failure modes | 01 |
| 1 | `step01_bm25.py` | BM25 from scratch: TF, IDF, length normalisation, keeping codes whole | 02 |
| 2 | `step02_hybrid_rrf.py` | Reciprocal Rank Fusion, explaining results by rank | 02 |
| 3 | `step03_eval.py` | hit@k, MRR, nDCG for every strategy | 02 |
| 4 | `step04_rerank.py` | two-stage retrieval: retrieve 20, rerank to 3 | 03 |
| 5 | `step05_rewrite.py` | LLM query rewriting (symptom words → system words) | 04 |
| 6 | `step06_decompose_hyde.py` | decomposition and HyDE | 04 |
| 7 | `step07_grader.py` | grading retrieval as JSON, failing open | 05 |
| 8 | `step08_corrective_rag.py` | the corrective loop, with bounded attempts and refusal | 05 |
| 9 | `step09_service_graph.py` | GraphRAG-lite: edges, callers, blast radius | 06 |
| 10 | `step10_retrieval_tool_agent.py` | retrieval as a tool in a Claude tool loop | 06 |
| 11 | `step11_grounded_answer.py` | `Answer` JSON, grounding and refusal (= `m03_rag.agent`) | 05, 06 |

**Build it yourself, by step:**
- **0:** index the corpus and print the misses.
- **1:** write `tokenize` and `bm25`, then compare `IDF('the')` with `IDF('pg-53300')`.
- **2:** fuse your two lists and print each result's ranks.
- **3:** add 3 questions of your own to the eval and keep the strategy that wins.
- **4:** add a reranker and check whether MRR moves.
- **5:** rewrite a query, and keep the original if the model's output is bad.
- **6:** retrieve for each sub-question and merge the results.
- **7:** grade the chunks, always against the *original* question.
- **8:** loop over the strategies and return nothing when nothing is relevant.
- **9:** parse the edges and run BFS upstream.
- **10:** register your search, graph and read tools.
- **11:** validate the output, drop citations that no tool returned, and refuse when none are left.

**Check yourself:**
- Why does RRF use ranks instead of scores?
- Why grade against the original question?
- When is failing open on a grader error wrong?
- Why can't similarity search answer "what breaks if redis fails"?
- What does corrective retrieval cost per query at 200 TPS?

**From steps to production (`src/m03_rag/`):**
- Steps 1–2 → `bm25.py`, `hybrid.py`
- Step 3 → `eval.py`
- Step 4 → `rerank.py`
- Steps 5–6 → `rewrite.py`
- Step 7 → `grader.py`
- Step 8 → `crag.py`, which adds HyDE and `Attempt` traces
- Step 9 → `graph.py`, which adds owners
- Steps 10–11 → `agent.py` (`m03 ask`)
