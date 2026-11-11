# Module 3: Agentic RAG over SRE incident knowledge

Naive RAG (`embed -> top-k -> answer`) breaks on the questions on-call engineers actually ask: symptom words ("purchase
flow sluggish"), exact codes (`PG-53300`), relationships ("what breaks if redis fails?") and multi-part questions. This
module fixes each one, **measures** every fix, and ends with an agent that treats retrieval as a tool, grades its own
retrieval, re-queries, and refuses when the documents don't answer the question.

**Deliverable:** `m03 ask "..."`, an incident-knowledge agent. It uses Claude by default, with `--provider mock` for offline runs.

## Setup (Windows PowerShell)
```powershell
cd learning\m03-agentic-rag
py -3.12 -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e ..\m01-llm-agent-engineering -e ..\m02-rag-memory-mcp -e ".[dev]"
copy ..\m01-llm-agent-engineering\.env .env       # ANTHROPIC_API_KEY=...
pytest -q                                          # offline
```

## Run it
```powershell
m03 search "PG-53300" --mode bm25                  # vector | bm25 | hybrid | rerank | corrective
m03 graph redis                                    # dependencies, callers, blast radius, owner
m03 eval                                           # hit@3 / MRR / nDCG / latency / LLM calls per strategy
m03 --provider anthropic ask "customers say cart items vanish, what happened before and how was it fixed?" --trace
m03 --provider anthropic ask "how do I rotate the TLS certificate on the edge proxy?"   # -> insufficient_evidence
```

## Learn it step by step
[`steps/README.md`](steps/README.md) has 12 small runnable files, from naive RAG (step 0) to the grounded agent (step 11).

## Files
| File | Role |
|---|---|
| `corpus/incidents.md`, `corpus/service-graph.md` | new docs: raw incident reports (symptom words, error codes) and the dependency/ownership graph. The M2 corpus and `lab/docs` are reused. |
| `bm25.py` | keyword index; the tokenizer keeps `pg-53300` whole and also splits it |
| `hybrid.py` | `HybridRetriever` (BM25 + M2 vector store) fused with `rrf()`; `Retrieved.sources` explains the ranks |
| `rerank.py` | `lexical_rerank` (a cross-scorer) and `llm_rerank`, which falls back to the lexical one on bad output |
| `rewrite.py` | `rewrite`, `decompose`, `hyde` |
| `grader.py` | LLM relevance grading as JSON (fails open; see theory 05) |
| `crag.py` | `corrective_retrieve`: original → rewrite → decompose → hyde, graded against the original question, with every `Attempt` recorded |
| `graph.py` | `ServiceGraph`, parsed from the docs: `dependencies`, `dependents`, `blast_radius`, `owners` |
| `agent.py` | `KnowledgeAgent` (tools `search_knowledge`, `service_graph`, `read_chunk`), `Answer` schema, `_ground`, `MockKnowledgeClient` |
| `eval.py` | 18 labelled questions; `hit`, `recall`, `MRR`, `nDCG`, ms/query and LLM calls per strategy |
| `llm.py` | `ClaudeText` (skips thinking blocks, no temperature) and `MockText` (deterministic) |

## Measured results (`m03 eval`, k=3, 18 questions, hashing embedder)
| Strategy | hit@3 | MRR | ms/query | LLM calls |
|---|---|---|---|---|
| vector | 0.889 | 0.722 | 0.7 | 0 |
| bm25 | 0.889 | 0.824 | 0.1 | 0 |
| hybrid (RRF) | 0.833 | 0.806 | 0.9 | 0 |
| hybrid + rerank | 0.833 | 0.769 | 1.7 | 0 |
| corrective (Claude Haiku) | 0.833 | 0.769 | 1520 | 18 |

These numbers are the lesson. With a weak embedder, fusion and corrective retrieval **don't** beat plain BM25 on this set,
but corrective retrieval is far more expensive. What the agentic parts do buy is shown in the live `ask` traces rather than
in hit@3:
- Claude reformulates the query and reads the full incident to answer "cart items vanish".
- It uses the graph for blast-radius questions.
- It **refuses** the TLS question instead of making something up.

To improve the table, swap in a neural embedder (`m02_obs` `sentence-transformers` extra) and a cross-encoder reranker, then re-run the eval.

Theory: `theory/01`–`06`, covering naive RAG failures, hybrid search, reranking, query transformation, corrective and self-RAG, and GraphRAG with retrieval as a tool.
