"""Step 3 - measure before you optimise: hit@k, MRR, nDCG on labelled questions, for every strategy.
The eval set (m03_rag.eval.EVAL_SET) mixes paraphrases, exact codes, relationship and multi-part questions.

Run:  python steps/step03_eval.py
"""

import math

from step00_naive_rag import naive_search
from step01_bm25 import bm25
from step02_hybrid_rrf import hybrid

from m03_rag.eval import EVAL_SET


def score(ranked: list[str], relevant: set[str], k: int = 3) -> tuple[float, float, float]:
    top = ranked[:k]
    first = next((i for i, c in enumerate(top, 1) if c in relevant), None)
    dcg = sum(1 / math.log2(i + 1) for i, c in enumerate(top, 1) if c in relevant)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return (1.0 if first else 0.0), (1 / first if first else 0.0), dcg / ideal


def report(name: str, search) -> None:
    rows = [score(search(q, 3), rel) for q, rel in EVAL_SET]
    hit, mrr, ndcg = (round(sum(col) / len(rows), 3) for col in zip(*rows, strict=True))
    misses = [q for (q, _), r in zip(EVAL_SET, rows, strict=True) if not r[0]]
    print(f"{name:8} hit@3={hit}  MRR={mrr}  nDCG@3={ndcg}  misses={misses}")


if __name__ == "__main__":
    print(f"{len(EVAL_SET)} labelled questions\n")
    for name, fn in [("vector", naive_search), ("bm25", bm25), ("hybrid", hybrid)]:
        report(name, fn)
    print("\nLesson: hybrid is not automatically better. Keep the strategy that wins on YOUR eval set.")
