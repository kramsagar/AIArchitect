"""Lab 2 - chunking and embeddings: see chunks, metadata, and why similarity works (and where lexical fails).

python -m m02_obs.labs.l02_chunk_embed
"""

from m02_obs.rag.chunking import default_corpus_dirs, load_corpus
from m02_obs.rag.embeddings import HashingEmbedder, tokenize


def cos(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def main() -> None:
    chunks = load_corpus(default_corpus_dirs())
    print(f"{len(chunks)} chunks from {[str(d) for d in default_corpus_dirs()]}\n")
    for c in chunks[:4]:
        print(f"{c.id:42} {len(c.text):5} chars  {c.metadata}")
    for size in (300, 600, 1200):
        print(f"max_chars={size:5}: {len(load_corpus(default_corpus_dirs(), max_chars=size))} chunks")

    emb = HashingEmbedder()
    pairs = [
        ("checkout is slow", "checkout latency p95 above 1s"),
        ("checkout is slow", "payments returning 503"),
        ("checkout is slow", "purchase takes forever"),  # synonym: lexical embedder misses it
    ]
    print("\ncosine similarity (hashing embedder):")
    for a, b in pairs:
        va, vb = emb.embed([a, b])
        print(f"  {cos(va, vb):.3f}  '{a}' vs '{b}'")
    print("\ntokens:", tokenize("ShopSphereCheckoutLatencySLO fired for the checkout route"))
    print("\nExercise: pip install -e '.[embeddings]' and repeat with SentenceTransformerEmbedder; the synonym pair")
    print("should score much higher. Then re-run `m02 eval` with it (KnowledgeBase(embedder=...)).")


if __name__ == "__main__":
    main()
