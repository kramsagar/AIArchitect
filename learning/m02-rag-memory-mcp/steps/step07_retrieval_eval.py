"""Step 7 - RAG part 3: measure retrieval before trusting it. Concepts: labelled questions, recall@k, MRR,
and using the numbers to compare design choices (chunk size, k).

Run:  python steps/step07_retrieval_eval.py
"""

from step05_chunking import Chunk, load_corpus
from step06_vector_search import VectorStore

EVAL = [  # (question an on-call engineer would ask, the chunk that answers it)
    ("checkout p95 is above one second", "runbooks#checkout-latency"),
    ("error budget is burning fast, 5xx ratio high", "runbooks#error-budget-burn"),
    ("payments service returns 503 and orders fail", "runbooks#payments-down"),
    ("p99 latency high everywhere, CPU saturated", "runbooks#high-latency"),
    ("ShopSphereErrorBudgetFastBurn fired", "runbooks#error-budget-burn"),
]


def evaluate(store: VectorStore, k: int = 3) -> dict:
    hits, rr = 0, 0.0
    for question, expected in EVAL:
        ids = [c.id for c, _ in store.search(question, k=k)]
        if expected in ids:
            hits += 1
            rr += 1 / (ids.index(expected) + 1)
        print(f"  {'HIT ' if expected in ids else 'MISS'} {question[:45]:45} -> {ids}")
    return {"recall@k": round(hits / len(EVAL), 2), "MRR": round(rr / len(EVAL), 3)}


def main() -> None:
    store = VectorStore(load_corpus())
    for k in (1, 3):
        print(f"k={k}")
        print("  ", evaluate(store, k))
    print("\nSame corpus, chunks cut to 300 chars (less context per chunk):")
    small = VectorStore([Chunk(c.id, c.doc, c.section, c.text[:300], c.meta) for c in load_corpus()])
    print("  ", evaluate(small, 3))
    print("\nRule: every change to chunking/embeddings must keep these numbers up. Add your own questions to EVAL.")


if __name__ == "__main__":
    main()
