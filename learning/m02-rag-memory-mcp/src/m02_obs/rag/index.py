"""Runbook knowledge base = corpus loader + chunker + embedder + vector store, plus a retrieval eval."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .chunking import Chunk, default_corpus_dirs, load_corpus
from .embeddings import Embedder, HashingEmbedder
from .store import Hit, VectorStore

# Labelled questions -> the chunk a good retriever must return. Grow this from real incidents (M3/M6).
RETRIEVAL_EVAL: list[tuple[str, str]] = [
    ("checkout is slow, p95 above 1 second", "runbooks#checkout-latency"),
    ("error budget burning fast, lots of 5xx", "runbooks#error-budget-burn"),
    ("payments returning 503, orders failing", "runbooks#payments-down"),
    ("p99 latency high across routes, requests queuing", "runbooks#high-latency"),
    ("what is the latency budget for the payments call during checkout", "architecture#dependency-budgets"),
    ("has payments latency hurt checkout before", "postmortems#pm-2026-09-payments-latency"),
    ("database connection pool too small", "postmortems#pm-2026-10-db-pool-exhaustion"),
    ("when do we freeze releases because of error budget", "slo-policy#error-budget-policy"),
    ("which services does checkout depend on", "architecture#service-map"),
    ("is it safe to retry a payment charge", "architecture#dependency-budgets"),
]


class KnowledgeBase:
    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or HashingEmbedder()
        self.store = VectorStore()

    @classmethod
    def from_dirs(cls, dirs: list[Path] | None = None, embedder: Embedder | None = None) -> KnowledgeBase:
        kb = cls(embedder)
        kb.add(load_corpus(dirs or default_corpus_dirs()))
        return kb

    def add(self, chunks: list[Chunk]) -> None:
        self.store.upsert(chunks, self.embedder.embed([c.text for c in chunks]))

    def search(
        self, query: str, k: int = 3, filters: dict[str, Any] | None = None, min_score: float = 0.05
    ) -> list[Hit]:  # noqa: E501
        return self.store.search(self.embedder.embed([query])[0], k=k, filters=filters, min_score=min_score)

    def get(self, chunk_id: str) -> Chunk | None:
        return next((c for c in self.store.chunks if c.id == chunk_id), None)

    def evaluate(self, k: int = 3, cases: list[tuple[str, str]] | None = None) -> dict[str, Any]:
        """recall@k: did the right chunk appear in the top k? MRR: how high (1/rank, 0 if missing)."""
        rows, rr = [], []
        for q, expected in cases or RETRIEVAL_EVAL:
            ids = [h.chunk.id for h in self.search(q, k=k, min_score=0.0)]
            rank = ids.index(expected) + 1 if expected in ids else None
            rr.append(1 / rank if rank else 0.0)
            rows.append({"question": q, "expected": expected, "rank": rank, "top": ids[:k]})
        n = len(rows)
        return {
            "k": k,
            "recall_at_k": round(sum(r["rank"] is not None for r in rows) / n, 3),
            "mrr": round(sum(rr) / n, 3),
            "cases": rows,
        }
