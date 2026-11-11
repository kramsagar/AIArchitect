"""Retrieval evaluation across strategies. The labelled set mixes the four query types that break naive RAG:
paraphrased symptoms, exact codes, relationship questions and multi-part questions."""

from __future__ import annotations

import math
import time

from m02_obs.rag.index import RETRIEVAL_EVAL

from .crag import corrective_retrieve
from .hybrid import HybridRetriever
from .llm import MockText, TextLLM
from .rerank import lexical_rerank

ALSO_RELEVANT = {  # M2 labels, extended because the M3 corpus adds documents that answer them too
    "runbooks#payments-down": {"incidents#inc-4203-pay-503-upstream"},
    "architecture#service-map": {"service-graph#dependencies"},
    "postmortems#pm-2026-10-db-pool-exhaustion": {"incidents#inc-4188-pg-53300"},
}
EVAL_SET: list[tuple[str, set[str]]] = [(q, {cid} | ALSO_RELEVANT.get(cid, set())) for q, cid in RETRIEVAL_EVAL] + [
    ("the purchase flow is sluggish and the place order button spins", {"incidents#inc-4127-purchase-flow-sluggish"}),
    ("PG-53300 in the shop logs", {"incidents#inc-4188-pg-53300"}),
    ("PAY-503-UPSTREAM errors", {"incidents#inc-4203-pay-503-upstream"}),
    ("customers say cart items vanish", {"incidents#inc-4251-redis-evictions"}),
    ("what is affected if redis fails", {"service-graph#dependencies"}),
    ("who is on call for postgres", {"service-graph#ownership"}),
    ("card processor lag makes buying slow", {"incidents#inc-4127-purchase-flow-sluggish",
                                               "postmortems#pm-2026-09-payments-latency"}),
    ("too many db connections after a deploy and what pool size should we use",
     {"incidents#inc-4188-pg-53300", "postmortems#pm-2026-10-db-pool-exhaustion"}),
]  # fmt: skip


def metrics(ranked: list[str], relevant: set[str], k: int) -> dict[str, float]:
    top = ranked[:k]
    hit = next((i for i, cid in enumerate(top, 1) if cid in relevant), None)
    dcg = sum(1 / math.log2(i + 1) for i, cid in enumerate(top, 1) if cid in relevant)
    idcg = sum(1 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return {
        "hit": 1.0 if hit else 0.0,  # at least one relevant chunk in the top k (enough to answer)
        "recall": len(relevant & set(top)) / min(len(relevant), k),  # share of the relevant chunks found
        "mrr": 1 / hit if hit else 0.0,  # how high the first relevant chunk is
        "ndcg": dcg / idcg,  # graded ranking quality
    }


def run_strategy(name: str, retriever: HybridRetriever, llm: TextLLM, question: str, k: int) -> list[str]:
    if name in ("vector", "bm25", "hybrid"):
        return [r.chunk.id for r in retriever.search(question, k=k, mode=name)]
    if name == "hybrid+rerank":
        return [r.chunk.id for r in lexical_rerank(question, retriever.search(question, k=20), k=k)]
    if name == "crag":
        return corrective_retrieve(retriever, llm, question, k=k).ids
    raise ValueError(name)


def evaluate(strategies=("vector", "bm25", "hybrid", "hybrid+rerank", "crag"), k: int = 3,
             llm: TextLLM | None = None, retriever: HybridRetriever | None = None) -> dict[str, dict]:  # fmt: skip
    retriever, llm = retriever or HybridRetriever(), llm or MockText()
    report = {}
    for name in strategies:
        totals, misses, t0, calls0 = (
            {"hit": 0.0, "recall": 0.0, "mrr": 0.0, "ndcg": 0.0},
            [],
            time.perf_counter(),
            llm.calls,
        )
        for question, relevant in EVAL_SET:
            m = metrics(run_strategy(name, retriever, llm, question, k), relevant, k)
            for key in totals:
                totals[key] += m[key]
            if m["hit"] < 1:
                misses.append(question)
        n = len(EVAL_SET)
        report[name] = {f"{key}@{k}": round(v / n, 3) for key, v in totals.items()} | {
            "ms_per_query": round((time.perf_counter() - t0) * 1000 / n, 2),
            "llm_calls": llm.calls - calls0,
            "misses": misses,
        }
    return report
