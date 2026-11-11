# 4. Query transformation: rewrite, decompose, HyDE

All three use an LLM *before* retrieval (`rewrite.py`). Each costs one model call, so use them conditionally.

- **Rewrite:** turn symptom words into system words, keeping ids exactly. "purchase flow sluggish" becomes "checkout latency payments slow".
- **Decompose:** split a multi-part question into up to 3 sub-questions. Retrieve for each one and merge the results.
- **HyDE (Hypothetical Document Embeddings):** ask the model to write a *fake answer* and search with that. An answer looks
  more like a document than a question does. The fake text is never shown to the user, only used as a query.

Risks:
- **Drift.** The rewrite changes the meaning. Mitigation: always *grade* against the **original** question (`crag.py` does this).
- **Invented ids.** A HyDE passage may contain fake error codes. That is harmless for search, but it must never reach the answer.
- **Cost.** Every transformation is an LLM call, so cache it by normalised question (production) and skip it when the first retrieval is graded good.
