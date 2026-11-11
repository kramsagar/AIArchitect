# 02 · RAG fundamentals: chunk, embed, store, retrieve, evaluate

RAG = give the model the *right few paragraphs* of your knowledge (runbooks, postmortems, architecture, policy) at
question time, instead of hoping it memorised them. Pipeline (all in `src/m02_obs/rag/`):

```
docs ─► chunk ─► embed ─► vector store ─► query embed ─► top-k (+filters) ─► cite ─► LLM
                                    ▲ offline / at ingest            ▲ online / per question (latency budget)
```

## Chunking
| Strategy | Good for | Trade-off |
|---|---|---|
| Fixed size (N tokens, overlap) | unstructured text | cuts mid-thought |
| **Structure-aware (headings)** | runbooks, docs, wikis | sections vary in size → split long ones |
| Semantic (embedding breakpoints) | long prose | cost at ingest |
| Parent-child (retrieve small, return big) | precise match + full context | more storage (M3) |

This module splits on `##` headings (one runbook section answers one question), splits long sections on paragraphs
with one paragraph of overlap, prefixes the heading path ("Runbooks > checkout-latency") into the text, and gives each
chunk a **stable id** (`runbooks#checkout-latency`). Stable ids make citations verifiable and re-ingestion idempotent.

## Embeddings and similarity
An embedding maps text to a vector so that similar meaning ≈ nearby vectors. Normalise vectors and cosine similarity
becomes a dot product. Options: `HashingEmbedder` (this repo: deterministic, offline, lexical — a baseline),
`all-MiniLM-L6-v2` (384-d, CPU, `pip install -e ".[embeddings]"`), hosted (Voyage — Anthropic's recommendation;
OpenAI; Cohere). Claude itself has no embeddings endpoint. Never mix embedders in one index: re-embed on model change.

## Vector stores
`VectorStore` here is a brute-force list: O(N) per query, fine to ~100k chunks. Production: **pgvector** (Postgres;
transactions, filters in SQL, HNSW/IVFFlat indexes — the enterprise default if you already run Postgres), OpenSearch /
Elasticsearch (hybrid lexical+vector), Chroma/FAISS (local/embedded), managed (Pinecone, Weaviate). ANN indexes trade a
little recall for 100x speed: tune `ef_search` / `lists` against your eval set.

## Metadata filters
Each chunk carries `type` (runbook / postmortem / architecture / policy), `services`, `alerts`. Filters cut the search
space and stop irrelevant-but-similar text (a payments postmortem when you asked for the policy). In multi-tenant
systems the filter is also a **security boundary** (tenant_id) — apply it in the store, never in the prompt.

## Evaluate retrieval before you tune prompts
`m02 eval` runs 10 labelled questions and reports **recall@k** (right chunk in top k?) and **MRR** (how high?).
Baseline here: recall@3 = 1.0, MRR ≈ 0.77. Every change (chunk size, embedder, filters) must move these numbers. M3
adds hybrid search, reranking and query rewriting; M6 turns this into a release gate.

## Check yourself
1. Why does prefixing the heading into the chunk text help retrieval?
2. What breaks if you change embedder without re-indexing?
3. Your index has 5M chunks and p95 search is 900ms. Which two knobs do you turn?
