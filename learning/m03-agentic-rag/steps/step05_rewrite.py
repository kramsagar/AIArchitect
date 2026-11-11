"""Step 5 - query rewriting: symptom words -> system words, keeping ids exact. One LLM call before retrieval.

Run:  python steps/step05_rewrite.py
"""

from common import llm
from step04_rerank import hybrid_rerank

from m03_rag.llm import json_from

SYSTEM = (
    "[rewrite] Rewrite the SRE question into a search query for runbooks, postmortems and architecture docs. "
    "Add the technical terms an SRE would use (service names, metrics, error codes). Keep ids and codes exactly. "
    'Reply with ONLY {"query": "..."}.'
)


def rewrite(model, question: str) -> str:
    out = json_from(model.complete(SYSTEM, f"QUESTION: {question}", max_tokens=200))
    return out.get("query", question) if isinstance(out, dict) else question  # bad output -> keep the original


if __name__ == "__main__":
    m = llm()
    for q in ["customers say cart items vanish", "card processor lag makes buying slow"]:
        r = rewrite(m, q)
        print(f"\n{q}\n  before: {hybrid_rerank(q)}\n  query : {r}\n  after : {hybrid_rerank(r)}")
