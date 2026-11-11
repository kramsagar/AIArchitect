"""Step 6 - decomposition (one query per need) and HyDE (search with a fake answer: answers look like documents).

Run:  python steps/step06_decompose_hyde.py
"""

from common import llm
from step04_rerank import hybrid_rerank

from m03_rag.rewrite import decompose, hyde

if __name__ == "__main__":
    m = llm()
    q = "too many db connections after a deploy and what pool size should we use"
    subs = decompose(m, q)
    print(f"{q}\n  as one query : {hybrid_rerank(q)}")
    merged = list(dict.fromkeys(cid for s in subs for cid in hybrid_rerank(s, 2)))
    print(f"  sub-questions: {subs}\n  merged       : {merged}")
    q2 = "orders hang at the last step"
    fake = hyde(m, q2)
    print(f"\n{q2}\n  plain: {hybrid_rerank(q2)}\n  HyDE text: {fake[:160]}...\n  HyDE : {hybrid_rerank(fake)}")
