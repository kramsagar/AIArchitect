"""Agent memory in three tiers.

- Working memory: the current run's messages (owned by the agent loop).
- Session memory (short-term): last N turns of this conversation, older turns folded into a rolling summary so the
  context stays inside a fixed budget no matter how long the chat runs.
- Long-term memory (SQLite, survives restarts): semantic facts ("payments timeout is 2s") and episodic memory (past
  investigations with their root cause), recalled by embedding similarity. Text is redacted before it is stored:
  memory is a data store with retention, so it gets the same PII/secret rules as logs.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .rag.embeddings import Embedder, HashingEmbedder

REDACTIONS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "[REDACTED_KEY]"),
    (re.compile(r"(?i)(password|passwd|secret|token|authorization)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[REDACTED_PAN]"),
]


def redact(text: str) -> str:
    for pattern, repl in REDACTIONS:
        text = pattern.sub(repl, text)
    return text


@dataclass
class Turn:
    user: str
    assistant: str


class SessionMemory:
    def __init__(self, max_turns: int = 4, max_summary_chars: int = 800) -> None:
        self.max_turns = max_turns
        self.max_summary_chars = max_summary_chars
        self.turns: list[Turn] = []
        self.summary = ""

    def add(self, user: str, assistant: str) -> None:
        self.turns.append(Turn(user, assistant))
        while len(self.turns) > self.max_turns:
            old = self.turns.pop(0)
            # Deterministic compaction; in production an LLM writes this summary (cheaper model, async).
            line = f"- Q: {old.user[:120]} → A: {old.assistant.split('. ')[0][:160]}"
            self.summary = (self.summary + "\n" + line).strip()[-self.max_summary_chars :]

    def messages(self) -> list[dict[str, str]]:
        msgs: list[dict[str, str]] = []
        if self.summary:
            msgs.append({"role": "user", "content": f"(Summary of earlier conversation)\n{self.summary}"})
            msgs.append({"role": "assistant", "content": "Noted."})
        for t in self.turns:
            msgs += [{"role": "user", "content": t.user}, {"role": "assistant", "content": t.assistant}]
        return msgs


SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
  scope TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, source TEXT, updated_at REAL NOT NULL,
  expires_at REAL, PRIMARY KEY (scope, key));
CREATE TABLE IF NOT EXISTS episodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, question TEXT NOT NULL, summary TEXT NOT NULL,
  root_cause TEXT, services TEXT NOT NULL, embedding TEXT NOT NULL);
"""


class LongTermMemory:
    def __init__(self, path: Path | str = ":memory:", embedder: Embedder | None = None) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.embedder = embedder or HashingEmbedder()

    # semantic memory
    def remember(self, key: str, value: str, *, scope: str = "global", source: str = "", ttl_s: float | None = None):
        now = time.time()
        self.db.execute(
            "INSERT INTO facts VALUES (?,?,?,?,?,?) ON CONFLICT(scope,key) DO UPDATE SET value=excluded.value, "
            "source=excluded.source, updated_at=excluded.updated_at, expires_at=excluded.expires_at",
            (scope, key, redact(value), source, now, now + ttl_s if ttl_s else None),
        )
        self.db.commit()

    def facts(self, scope: str = "global") -> dict[str, str]:
        rows = self.db.execute(
            "SELECT key, value FROM facts WHERE scope=? AND (expires_at IS NULL OR expires_at > ?) ORDER BY key",
            (scope, time.time()),
        )
        return dict(rows.fetchall())

    # episodic memory
    def record_episode(self, question: str, summary: str, root_cause: str | None, services: list[str]) -> int:
        q, s = redact(question), redact(summary)
        vec = self.embedder.embed([f"{q}\n{root_cause or ''}"])[0]  # summary is long and dilutes similarity
        cur = self.db.execute(
            "INSERT INTO episodes (ts, question, summary, root_cause, services, embedding) VALUES (?,?,?,?,?,?)",
            (time.time(), q, s, redact(root_cause or ""), json.dumps(services), json.dumps(vec)),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def recall(self, query: str, k: int = 2, min_score: float = 0.2) -> list[dict[str, Any]]:
        qv = self.embedder.embed([query])[0]
        scored = []
        for eid, ts, q, s, rc, svcs, emb in self.db.execute("SELECT * FROM episodes"):
            score = sum(a * b for a, b in zip(qv, json.loads(emb), strict=False))
            if score >= min_score:
                scored.append(
                    {
                        "id": eid,
                        "ts": ts,
                        "question": q,
                        "summary": s,
                        "root_cause": rc,
                        "services": json.loads(svcs),
                        "score": round(score, 3),
                    }
                )
        return sorted(scored, key=lambda e: -e["score"])[:k]

    def episodes(self) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT id, ts, question, root_cause FROM episodes ORDER BY id DESC LIMIT 50")
        return [{"id": i, "ts": ts, "question": q, "root_cause": rc} for i, ts, q, rc in rows]

    def clear(self) -> None:
        self.db.executescript("DELETE FROM facts; DELETE FROM episodes;")
        self.db.commit()
