"""Step 1 - BM25 keyword search from scratch: term frequency, inverse document frequency, length normalisation.
Exact tokens (PG-53300, PAY-503-UPSTREAM) are where it beats embeddings.

Run:  python steps/step01_bm25.py
"""

import math
import re
from collections import Counter

from common import CHUNKS
from step00_naive_rag import naive_search


def tokenize(text: str) -> list[str]:
    text = text.lower()
    return re.findall(r"[a-z0-9]+", text) + re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)+", text)  # parts + whole codes


DOCS = [Counter(tokenize(c.text)) for c in CHUNKS]
AVG = sum(sum(d.values()) for d in DOCS) / len(DOCS)
DF = Counter(t for d in DOCS for t in d)
IDF = {t: math.log(1 + (len(DOCS) - f + 0.5) / (f + 0.5)) for t, f in DF.items()}  # rare term -> high weight


def bm25(query: str, k: int = 3, k1: float = 1.5, b: float = 0.75) -> list[str]:
    def score(d: Counter) -> float:
        n = sum(d.values())
        return sum(
            IDF[t] * d[t] * (k1 + 1) / (d[t] + k1 * (1 - b + b * n / AVG)) for t in set(tokenize(query)) if t in d
        )

    ranked = sorted(range(len(CHUNKS)), key=lambda i: -score(DOCS[i]))
    return [CHUNKS[i].id for i in ranked[:k]]


if __name__ == "__main__":
    for q in ["PG-53300", "PAY-503-UPSTREAM errors", "customers say cart items vanish", "purchase flow sluggish"]:
        print(f"{q:32} bm25   -> {bm25(q)}\n{'':32} vector -> {naive_search(q)}")
    print(f"\nIDF('the')={IDF.get('the', 0):.2f}  IDF('pg-53300')={IDF['pg-53300']:.2f}  <- why rare tokens dominate")
