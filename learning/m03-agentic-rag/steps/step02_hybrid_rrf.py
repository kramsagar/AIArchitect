"""Step 2 - hybrid search with Reciprocal Rank Fusion: score = sum over retrievers of 1/(60 + rank).
Ranks, not scores, so BM25 and cosine never need calibrating. Keep each retriever's rank to explain results.

Run:  python steps/step02_hybrid_rrf.py
"""

from step00_naive_rag import naive_search
from step01_bm25 import bm25


def rrf(lists: dict[str, list[str]], k: int = 60) -> list[tuple[str, float, dict]]:
    fused: dict[str, list] = {}
    for name, ids in lists.items():
        for rank, cid in enumerate(ids, 1):
            entry = fused.setdefault(cid, [0.0, {}])
            entry[0] += 1 / (k + rank)
            entry[1][name] = rank
    return sorted(((cid, round(s, 4), r) for cid, (s, r) in fused.items()), key=lambda x: -x[1])


def hybrid(query: str, k: int = 3) -> list[str]:
    return [cid for cid, _, _ in rrf({"bm25": bm25(query, 20), "vector": naive_search(query, 20)})[:k]]


if __name__ == "__main__":
    for q in ["PG-53300 in the shop logs", "customers say cart items vanish", "checkout is slow, p95 above 1 second"]:
        print(q)
        for cid, score, ranks in rrf({"bm25": bm25(q, 20), "vector": naive_search(q, 20)})[:3]:
            print(f"   {score:.4f} {cid:45} ranks={ranks}")
