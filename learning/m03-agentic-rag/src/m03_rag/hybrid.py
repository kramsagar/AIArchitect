"""Hybrid retrieval: run BM25 and vector search, then fuse the two ranked lists with Reciprocal Rank Fusion.
RRF uses ranks, not raw scores, so the two incomparable score scales never need calibrating."""

from __future__ import annotations

from dataclasses import dataclass, field

from m02_obs.rag.chunking import Chunk, default_corpus_dirs, load_corpus
from m02_obs.rag.embeddings import Embedder, build_embedder
from m02_obs.rag.store import VectorStore, _matches

from .bm25 import BM25Index


@dataclass
class Retrieved:
    chunk: Chunk
    score: float
    sources: dict[str, int] = field(default_factory=dict)  # retriever -> rank (1-based), for explainability

    def citation(self) -> dict:
        return {"id": self.chunk.id, "type": self.chunk.metadata.get("type"), "score": round(self.score, 4),
                "ranks": self.sources}  # fmt: skip


def rrf(ranked_lists: dict[str, list[Chunk]], k: int = 60) -> list[Retrieved]:
    fused: dict[str, Retrieved] = {}
    for name, chunks in ranked_lists.items():
        for rank, c in enumerate(chunks, start=1):
            r = fused.setdefault(c.id, Retrieved(c, 0.0))
            r.score += 1.0 / (k + rank)
            r.sources[name] = rank
    return sorted(fused.values(), key=lambda r: -r.score)


def corpus_dirs() -> list:
    from pathlib import Path

    return [Path(__file__).resolve().parent / "corpus", *default_corpus_dirs()]


class HybridRetriever:
    def __init__(self, chunks: list[Chunk] | None = None, embedder: Embedder | None = None) -> None:
        self.chunks = chunks if chunks is not None else load_corpus(corpus_dirs())
        self.by_id = {c.id: c for c in self.chunks}
        self.embedder = embedder or build_embedder("hashing")
        self.store = VectorStore()
        self.store.upsert(self.chunks, self.embedder.embed([c.text for c in self.chunks]))
        self.bm25 = BM25Index(self.chunks)

    def vector(self, query: str, k: int = 10, filters: dict | None = None) -> list[Chunk]:
        return [h.chunk for h in self.store.search(self.embedder.embed([query])[0], k=k, filters=filters)]

    def keyword(self, query: str, k: int = 10, filters: dict | None = None) -> list[Chunk]:
        hits = [c for c, _ in self.bm25.search(query, k=len(self.chunks))]
        return [c for c in hits if not filters or _matches(c.metadata, filters)][:k]

    def search(self, query: str, k: int = 5, mode: str = "hybrid", filters: dict | None = None) -> list[Retrieved]:
        if mode == "vector":
            return [Retrieved(c, 1.0 / r, {"vector": r}) for r, c in enumerate(self.vector(query, k, filters), 1)]
        if mode == "bm25":
            return [Retrieved(c, 1.0 / r, {"bm25": r}) for r, c in enumerate(self.keyword(query, k, filters), 1)]
        lists = {"bm25": self.keyword(query, 20, filters), "vector": self.vector(query, 20, filters)}
        return rrf(lists)[:k]
