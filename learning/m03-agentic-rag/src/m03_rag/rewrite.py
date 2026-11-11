"""Query transformation. On-call engineers describe *symptoms* in their own words ("purchase flow sluggish");
the docs use *system* words ("checkout latency"). Three fixes: rewrite, decompose, HyDE."""

from __future__ import annotations

from .llm import TextLLM, json_from

REWRITE_SYSTEM = (
    "[rewrite] Rewrite the SRE question into a search query for runbooks, postmortems and architecture docs. "
    "Add the technical terms an SRE would use (service names, metrics, error codes). Keep any ids or codes exactly. "
    'Reply with ONLY {"query": "..."}.'
)
DECOMPOSE_SYSTEM = (
    "[decompose] Split the question into at most 3 independent sub-questions that can each be answered from one "
    'document. If it is already a single question, return it unchanged. Reply with ONLY {"sub_questions": [...]}.'
)
HYDE_SYSTEM = (
    "[hyde] Write a short (3 sentences) hypothetical runbook paragraph that would answer the question. "
    "It is used only as a search query, so plausible wording matters more than facts."
)


def rewrite(llm: TextLLM, question: str) -> str:
    out = json_from(llm.complete(REWRITE_SYSTEM, f"QUESTION: {question}", max_tokens=200))
    return out["query"] if isinstance(out, dict) and out.get("query") else question


def decompose(llm: TextLLM, question: str) -> list[str]:
    out = json_from(llm.complete(DECOMPOSE_SYSTEM, f"QUESTION: {question}", max_tokens=300))
    subs = out.get("sub_questions") if isinstance(out, dict) else None
    return [s for s in subs if isinstance(s, str) and s.strip()][:3] if subs else [question]


def hyde(llm: TextLLM, question: str) -> str:
    """Hypothetical Document Embeddings: search with a fake *answer*; answers look like documents, questions don't."""
    return llm.complete(HYDE_SYSTEM, f"QUESTION: {question}", max_tokens=200).strip() or question
