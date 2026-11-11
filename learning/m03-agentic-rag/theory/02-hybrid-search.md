# 2. Hybrid search: BM25 + vectors, fused with RRF

**BM25** scores a document by the query terms it contains. Rare terms count more (IDF), repeated terms count with diminishing returns (`k1`), and
long documents are normalised (`b`). It is exact, explainable and fast, so it is good for error codes, metric names and service names.
`bm25.tokenize` keeps `pg-53300` whole *and* splits it, so both "PG-53300" and "53300" match.

**Vectors** score by meaning. They are good for paraphrases, and weak for rare identifiers and negation.

**Reciprocal Rank Fusion** (`hybrid.rrf`): `score(d) = Σ_retrievers 1 / (k + rank_r(d))`, with `k = 60`.
- It uses ranks only, so BM25's unbounded scores and cosine's [-1, 1] never need calibrating.
- A document ranked well by *both* retrievers beats one ranked first by only one of them.
- `Retrieved.sources` keeps each retriever's rank, so you can explain *why* a chunk was returned.

**Measured lesson** (`m03 eval`): on this corpus, hybrid is **not** automatically better than BM25. It wins some queries and
loses others, because a hashing embedder is a weak second opinion. Never assume a technique helps: measure it on *your* eval set.
In production, pair BM25 with a strong neural embedder. Metadata filters (`filters={"type": "incident"}`) apply to both retrievers.

**Production:** OpenSearch/Elasticsearch (BM25 + kNN in one query), Postgres `tsvector` + pgvector, or Vespa/Weaviate hybrid.
Index-time work (tokenising, embedding) is done once. Query time should stay in single-digit milliseconds at high TPS.
