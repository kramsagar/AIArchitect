# 5. Corrective RAG and self-RAG: grade, then retry or refuse

`crag.corrective_retrieve` is a small state machine:

```
original -> retrieve+rerank -> grade(original question)
   enough relevant? -- yes --> done (sufficient=True)
        | no
   rewrite -> retrieve -> grade -> enough? -> done
        | no
   decompose -> retrieve each -> grade -> enough? -> done
        | no
   (hyde) ... -> give up: sufficient=False, chunks=[] -> the agent says "insufficient evidence"
```
- **Grader** (`grader.py`): an LLM judges each chunk as relevant or not, and returns JSON. If the grader output is broken, it **fails open** (keeps the
  chunks) and the trace shows it. Choose fail-open or fail-closed deliberately: refusing is safer for runbooks that drive actions.
- **Every attempt is recorded** (`Attempt.strategy / queries / retrieved / relevant`). That's your trace for debugging, and the
  source of eval data ("which questions need a rewrite?").
- **Bounded:** `max_attempts` caps both latency and cost. With Claude Haiku each attempt is about 1–2 s.

**Self-RAG** adds critique *after* generation: is each claim supported by a cited chunk? This module does the deterministic part.
`agent._ground` drops citations the tools never returned, lowers confidence, and flags `insufficient_evidence` when no
citations remain. An LLM "is this claim supported?" check is a Module 6 (evaluation) topic.

Verified live: asking "how do I rotate the TLS certificate on the edge proxy?" led Claude to search twice, find no runbook, and
answer with `insufficient_evidence: true` instead of inventing a procedure.
