"""Step 6 - RAG part 2: embeddings + similarity search. Concepts: text -> vector, cosine similarity, top-k,
metadata filters. A deterministic hashing embedder keeps it free/offline; swap in a neural model later.

Run:  python steps/step06_vector_search.py
      python steps/step06_vector_search.py "payments returning 503"
"""

import hashlib
import math
import re
import sys

from step05_chunking import Chunk, load_corpus

STOP = {"the", "a", "an", "is", "are", "of", "to", "and", "or", "in", "on", "for", "why", "what", "how", "it", "be"}


def tokens(text: str) -> list[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)  # ShopSphereHighP99 -> Shop Sphere High P99
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


def embed(text: str, dim: int = 512) -> list[float]:
    """Feature hashing of words + word pairs into a fixed-size, L2-normalised vector."""
    vec = [0.0] * dim
    toks = tokens(text)
    for t in toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False)]:
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0 if (h >> 8) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))  # vectors are normalised -> dot product = cosine


class VectorStore:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.items = [(c, embed(c.text)) for c in chunks]  # "indexing" = embed once, store with the chunk

    def search(self, query: str, k: int = 3, filters: dict | None = None) -> list[tuple[Chunk, float]]:
        q = embed(query)
        hits = [
            (c, round(cosine(q, v), 3))
            for c, v in self.items
            if not filters or all(c.meta.get(key) == val for key, val in filters.items())
        ]
        return sorted(hits, key=lambda h: -h[1])[:k]


def main() -> None:
    store = VectorStore(load_corpus())
    query = " ".join(sys.argv[1:]) or "checkout is slow, p95 above 1s"
    print(f"query: {query}")
    for c, score in store.search(query):
        print(f"  {score:.3f}  {c.id}")
    print("\nsame query, only postmortems:")
    for c, score in store.search(query, filters={"type": "postmortem"}):
        print(f"  {score:.3f}  {c.id}")


if __name__ == "__main__":
    main()
