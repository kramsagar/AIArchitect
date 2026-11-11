"""A tiny text-completion interface for the RAG helpers (rewrite, grade, rerank, answer).
`ClaudeText` calls the Messages API; `MockText` is deterministic so tests and CI need no key."""

from __future__ import annotations

import json
import os
import re
from typing import Protocol


class TextLLM(Protocol):
    calls: int

    def complete(self, system: str, user: str, max_tokens: int = 600) -> str: ...


class ClaudeText:
    def __init__(self, model: str | None = None, client=None) -> None:
        import anthropic

        self.model = model or os.getenv("AGENT_MODEL", "claude-haiku-5-5")
        self.client = client or anthropic.Anthropic(max_retries=2, timeout=60)
        self.calls = 0
        self.tokens = 0

    def complete(self, system: str, user: str, max_tokens: int = 600) -> str:
        self.calls += 1
        resp = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}]
        )
        self.tokens += resp.usage.input_tokens + resp.usage.output_tokens
        return "".join(b.text for b in resp.content if b.type == "text")  # skip thinking blocks


SYNONYMS = {  # what a model "knows" that a keyword index does not
    "sluggish": "slow latency", "spins": "slow latency", "lag": "latency", "laggy": "slow latency",
    "purchase": "checkout order", "buy": "checkout", "card": "payments", "processor": "payments provider",
    "db": "postgres database", "connections": "connection pool",
    "vanish": "evicted redis", "disappear": "evicted redis",
    "5xx": "errors error budget", "outage": "down errors", "budget": "error budget slo", "page": "alert",
}  # fmt: skip


def json_from(text: str):
    """Models sometimes wrap JSON in prose or ``` fences; take the first JSON value."""
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    return json.loads(m.group(1)) if m else None


class MockText:
    """Rule-based stand-in for an LLM. It understands the prompt *kind* by a tag in the system prompt."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, user: str, max_tokens: int = 600) -> str:
        self.calls += 1
        q = user.split("QUESTION:", 1)[-1].split("\n", 1)[0].strip()
        words = re.findall(r"[a-z0-9-]+", q.lower())
        if "[rewrite]" in system:
            extra = [SYNONYMS[w] for w in words if w in SYNONYMS]
            return json.dumps({"query": " ".join([q, *extra])})
        if "[hyde]" in system:
            extra = " ".join(SYNONYMS.get(w, w) for w in words)
            return f"Runbook: {extra}. Check Grafana, Jaeger traces and Splunk logs; compare with past postmortems."
        if "[decompose]" in system:
            parts = [p.strip() for p in re.split(r"\band\b|\?|;", q) if len(p.strip()) > 8]
            return json.dumps({"sub_questions": parts[:3] or [q]})
        if "[grade]" in system:
            ids = re.findall(r"<doc id=\"([^\"]+)\">(.*?)</doc>", user, re.S)
            terms = {t for w in words for t in (SYNONYMS.get(w, w)).split() if len(t) > 3}
            need = max(1, min(2, len(terms) // 2))
            return json.dumps({i: len(terms & set(re.findall(r"[a-z0-9-]+", body.lower()))) >= need for i, body in ids})
        return json.dumps({"answer": "mock", "citations": []})
