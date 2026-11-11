# 3. Two-stage retrieval: recall first, precision second

Stage 1 (retrieval) is tuned for **recall**: put the right chunk *somewhere* in the top 20, cheaply.
Stage 2 (reranking) is tuned for **precision**: look at each (query, chunk) pair *together* and put the best one first.

- A **bi-encoder** (an embedding model) encodes the query and the document separately. It is fast and can be indexed, but it is coarse.
- A **cross-encoder** reads the query and the document in one pass. It is accurate but slow (one model call per pair), so only use it on about 20 candidates.
- An **LLM reranker** (`rerank.llm_rerank`) is the most flexible and the most expensive. Treat its output as untrusted: if it isn't a JSON list of ids,
  **fall back** to the cheap reranker rather than failing.

`rerank.lexical_rerank` is a teaching cross-scorer. It combines query-term coverage, a title match and the fused score.
Production options include `bge-reranker`, Cohere Rerank and Vertex ranking.

Latency budget example at 200 TPS with a p95 target under 300 ms: retrieval 10 ms, cross-encoder over 20 candidates on GPU 40 ms, generation the rest.
LLM reranking (500–1500 ms) doesn't fit that budget, so reserve it for offline or low-TPS paths.
