"""Step 4 - two-stage retrieval: retrieve 20 for recall, rerank to 3 for precision. The reranker sees the query
and the chunk TOGETHER (coverage, title match); an embedding compares them separately.

Run:  python steps/step04_rerank.py
"""

from common import BY_ID
from step01_bm25 import tokenize
from step02_hybrid_rrf import hybrid
from step03_eval import report


def rerank(query: str, candidates: list[str], k: int = 3) -> list[str]:
    q = set(tokenize(query))

    def score(pos_cid):
        pos, cid = pos_cid
        c = BY_ID[cid]
        coverage = len(q & set(tokenize(c.text))) / max(len(q), 1)
        title = len(q & set(tokenize(c.section.replace("-", " ")))) / max(len(q), 1)
        return 0.5 * coverage + 0.3 * title + 0.2 / (pos + 1)  # keep a little of the first-stage order

    return [cid for _, cid in sorted(enumerate(candidates), key=lambda pc: -score(pc))[:k]]


def hybrid_rerank(query: str, k: int = 3) -> list[str]:
    return rerank(query, hybrid(query, 20), k)


if __name__ == "__main__":
    q = "is it safe to retry a payment charge"
    print(f"{q}\n  hybrid       -> {hybrid(q)}\n  hybrid+rerank-> {hybrid_rerank(q)}\n")
    report("hybrid", hybrid)
    report("+rerank", hybrid_rerank)
