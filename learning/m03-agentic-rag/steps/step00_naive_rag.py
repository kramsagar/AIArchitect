"""Step 0 - naive RAG and where it breaks. embed(question) -> top-3 -> done. Watch it miss on
symptom words, exact error codes and relationship questions (the 4 failure modes in theory/01).

Run:  python steps/step00_naive_rag.py
"""

from common import CHUNKS
from m02_obs.rag.embeddings import HashingEmbedder

emb = HashingEmbedder()
VECS = emb.embed([c.text for c in CHUNKS])


def naive_search(query: str, k: int = 3) -> list[str]:
    q = emb.embed([query])[0]
    scored = sorted(zip(CHUNKS, VECS, strict=True), key=lambda cv: -sum(a * b for a, b in zip(q, cv[1], strict=True)))
    return [c.id for c, _ in scored[:k]]


TESTS = [  # (question, the chunk that answers it)
    ("checkout is slow, p95 above 1 second", "runbooks#checkout-latency"),
    ("customers say cart items vanish", "incidents#inc-4251-redis-evictions"),
    ("what is affected if redis fails", "service-graph#dependencies"),
    ("card processor lag makes buying slow", "incidents#inc-4127-purchase-flow-sluggish"),
]

if __name__ == "__main__":
    print(f"{len(CHUNKS)} chunks indexed\n")
    for q, want in TESTS:
        got = naive_search(q)
        print(f"{'HIT ' if want in got else 'MISS'} {q:40} -> {got}")
