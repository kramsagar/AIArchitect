"""BM25 keyword search. Vectors find *meaning* ("sluggish" ~ "slow"); BM25 finds *exact tokens* (error codes,
metric names, trace ids) that embeddings blur. Production: OpenSearch/Elasticsearch, or Postgres full-text search."""

from __future__ import annotations

import math
import re
from collections import Counter

from m02_obs.rag.chunking import Chunk

STOP = {"the", "a", "an", "is", "are", "of", "to", "and", "or", "in", "on", "for", "why", "what", "how", "it", "be",
        "we", "our", "with", "at", "by", "was", "do", "does", "this", "that", "if", "when", "which"}  # fmt: skip


def tokenize(text: str) -> list[str]:
    """Keep codes like PG-53300 and dotted span names intact as extra tokens, plus their parts."""
    text = text.lower()
    whole = re.findall(r"[a-z0-9]+(?:[-_.:][a-z0-9]+)+", text)
    parts = re.findall(r"[a-z0-9]+", text)
    return [t for t in parts + whole if t not in STOP]


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks, self.k1, self.b = chunks, k1, b
        self.docs = [Counter(tokenize(f"{c.section} {c.text}")) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_len = sum(self.lengths) / max(len(self.docs), 1)
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query: str, i: int) -> float:
        doc, length, s = self.docs[i], self.lengths[i], 0.0
        for t in set(tokenize(query)):
            if t in doc:
                tf = doc[t]
                s += self.idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self.avg_len))
        return s

    def search(self, query: str, k: int = 5) -> list[tuple[Chunk, float]]:
        scored = [(c, self.score(query, i)) for i, c in enumerate(self.chunks)]
        return [h for h in sorted(scored, key=lambda h: -h[1])[:k] if h[1] > 0]
