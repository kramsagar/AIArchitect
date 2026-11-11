"""Step 8 - corrective RAG: retrieve -> grade -> not enough? rewrite / decompose -> retrieve -> grade ->
still nothing? return NO chunks so the answer can say "insufficient evidence". Bounded attempts = bounded cost.

Run:  python steps/step08_corrective_rag.py
"""

from common import llm
from step04_rerank import hybrid_rerank
from step05_rewrite import rewrite
from step07_grader import grade

from m03_rag.rewrite import decompose


def corrective(model, question: str, max_attempts: int = 3) -> tuple[list[str], list[str]]:
    relevant, log = [], []
    strategies = [("original", lambda: [question]), ("rewrite", lambda: [rewrite(model, question)]),
                  ("decompose", lambda: decompose(model, question))][:max_attempts]  # fmt: skip
    for name, make_queries in strategies:
        ids = list(dict.fromkeys(cid for q in make_queries() for cid in hybrid_rerank(q)))
        new = [cid for cid, ok in grade(model, question, ids).items() if ok and cid not in relevant]
        relevant += new
        log.append(f"{name}: {len(new)} relevant of {len(ids)}")
        if relevant:
            break
    return relevant, log


if __name__ == "__main__":
    m = llm()
    for q in ["customers say cart items vanish", "how do I rotate the TLS certificate on the edge proxy?"]:
        ids, log = corrective(m, q)
        print(f"\n{q}\n  attempts: {log}\n  chunks  : {ids or 'NONE -> answer must say insufficient evidence'}")
