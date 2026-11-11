"""A minimal vector store: cosine similarity over normalised vectors, metadata filters, a score floor and JSON
persistence. Production swaps this for pgvector / OpenSearch / a managed DB with ANN indexes (HNSW, IVF); the
interface (upsert, search with filters, top-k) stays the same."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .chunking import Chunk


@dataclass
class Hit:
    chunk: Chunk
    score: float

    def citation(self) -> dict[str, Any]:
        return {
            "id": self.chunk.id,
            "section": self.chunk.section,
            "type": self.chunk.metadata.get("type"),
            "score": round(self.score, 3),
        }


def _matches(meta: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, want in filters.items():
        have = meta.get(key)
        if isinstance(have, list):
            if want not in have:
                return False
        elif have != want:
            return False
    return True


class VectorStore:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self.vectors: list[list[float]] = []

    def __len__(self) -> int:
        return len(self.chunks)

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        index = {c.id: i for i, c in enumerate(self.chunks)}
        for c, v in zip(chunks, vectors, strict=True):
            if c.id in index:
                self.chunks[index[c.id]], self.vectors[index[c.id]] = c, v
            else:
                self.chunks.append(c)
                self.vectors.append(v)

    def search(
        self, qvec: list[float], k: int = 3, filters: dict[str, Any] | None = None, min_score: float = 0.0
    ) -> list[Hit]:  # noqa: E501
        hits = [
            Hit(c, sum(a * b for a, b in zip(qvec, v, strict=False)))
            for c, v in zip(self.chunks, self.vectors, strict=False)
            if not filters or _matches(c.metadata, filters)
        ]
        hits.sort(key=lambda h: -h.score)
        return [h for h in hits[:k] if h.score >= min_score]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"chunks": [asdict(c) for c in self.chunks], "vectors": self.vectors}))

    @classmethod
    def load(cls, path: Path) -> VectorStore:
        data = json.loads(path.read_text())
        store = cls()
        store.upsert([Chunk(**c) for c in data["chunks"]], data["vectors"])
        return store
