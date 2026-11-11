"""Lab 3 - vector search, metadata filters and retrieval evaluation (recall@k, MRR).

python -m m02_obs.labs.l03_vector_search
"""

from m02_obs.rag.chunking import default_corpus_dirs, load_corpus
from m02_obs.rag.index import KnowledgeBase


def main() -> None:
    kb = KnowledgeBase.from_dirs()
    q = "payments latency made checkout slow"
    print(f"query: {q}")
    for f in (None, {"type": "runbook"}, {"type": "postmortem"}, {"services": "postgres"}):
        hits = kb.search(q, k=3, filters=f)
        print(f"  filter={f}: {[(h.chunk.id, round(h.score, 3)) for h in hits]}")

    print("\nretrieval eval by k:")
    for k in (1, 3, 5):
        r = kb.evaluate(k=k)
        print(f"  k={k}: recall@k={r['recall_at_k']}  MRR={r['mrr']}")

    print("\nchunk size vs quality (k=3):")
    for size in (300, 600, 1200, 4000):
        kb2 = KnowledgeBase()
        kb2.add(load_corpus(default_corpus_dirs(), max_chars=size))
        r = kb2.evaluate(k=3)
        misses = [c["expected"] for c in r["cases"] if c["rank"] is None]
        stats = f"recall@3={r['recall_at_k']} MRR={r['mrr']} misses={misses}"
        print(f"  max_chars={size:5}: {len(kb2.store):3} chunks {stats}")
    print("\nExercise: add 3 questions of your own to RETRIEVAL_EVAL (rag/index.py) and make one fail on purpose.")


if __name__ == "__main__":
    main()
