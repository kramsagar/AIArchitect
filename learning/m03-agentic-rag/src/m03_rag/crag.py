"""Corrective RAG: retrieve -> grade -> (if not enough relevant) transform the query and retrieve again ->
... -> answer from relevant chunks only, or say "insufficient evidence". Every attempt is recorded for tracing."""

from __future__ import annotations

from dataclasses import dataclass, field

from .grader import grade
from .hybrid import HybridRetriever, Retrieved
from .llm import TextLLM
from .rerank import lexical_rerank
from .rewrite import decompose, hyde, rewrite


@dataclass
class Attempt:
    strategy: str
    queries: list[str]
    retrieved: list[str]
    relevant: list[str]


@dataclass
class CragResult:
    question: str
    chunks: list[Retrieved]
    attempts: list[Attempt] = field(default_factory=list)
    sufficient: bool = False

    @property
    def ids(self) -> list[str]:
        return [r.chunk.id for r in self.chunks]


STRATEGIES = ("original", "rewrite", "decompose", "hyde")


def corrective_retrieve(
    retriever: HybridRetriever, llm: TextLLM, question: str, *, k: int = 4, min_relevant: int = 1, max_attempts: int = 3
) -> CragResult:
    result = CragResult(question, [])
    relevant: dict[str, Retrieved] = {}
    for strategy in STRATEGIES[:max_attempts]:
        if strategy == "original":
            queries = [question]
        elif strategy == "rewrite":
            queries = [rewrite(llm, question)]
        elif strategy == "decompose":
            queries = decompose(llm, question)
        else:
            queries = [hyde(llm, question)]
        candidates: dict[str, Retrieved] = {}
        for q in queries:
            for r in lexical_rerank(q, retriever.search(q, k=20), k=k):
                candidates.setdefault(r.chunk.id, r)
        fresh = [r for cid, r in candidates.items() if cid not in relevant]
        grades = grade(llm, question, fresh)  # always grade against the ORIGINAL question
        for r in fresh:
            if grades.get(r.chunk.id):
                relevant[r.chunk.id] = r
        result.attempts.append(Attempt(strategy, queries, list(candidates), [r.chunk.id for r in fresh
                                                                              if grades.get(r.chunk.id)]))  # fmt: skip
        if len(relevant) >= min_relevant:
            result.sufficient = True
            break
    result.chunks = list(relevant.values())[: k + 2]  # discovery order: scores from different queries don't compare
    return result
