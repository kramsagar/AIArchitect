"""Step 8 - memory beyond one chat. Concepts: long-term FACTS (SQLite, with TTL) and EPISODIC memory
(past investigations, recalled by similarity), plus redaction before anything is stored.

Run:  python steps/step08_memory.py
"""

import json
import re
import sqlite3
import time

from step06_vector_search import cosine, embed

REDACT = [
    (re.compile(r"sk-[A-Za-z0-9_-]{10,}"), "[REDACTED_KEY]"),
    (re.compile(r"(?i)password\s*[=:]\s*\S+"), "password=[REDACTED]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[REDACTED_EMAIL]"),
]


def redact(text: str) -> str:
    for pattern, repl in REDACT:
        text = pattern.sub(repl, text)
    return text


class LongTermMemory:
    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS facts (key TEXT PRIMARY KEY, value TEXT, expires REAL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS episodes (question TEXT, root_cause TEXT, vec TEXT, at REAL)")

    def remember(self, key: str, value: str, ttl_s: float | None = None) -> None:
        expires = time.time() + ttl_s if ttl_s else None
        self.db.execute("INSERT OR REPLACE INTO facts VALUES (?, ?, ?)", (key, redact(value), expires))

    def facts(self) -> dict:
        rows = self.db.execute("SELECT key, value FROM facts WHERE expires IS NULL OR expires > ?", (time.time(),))
        return dict(rows.fetchall())

    def record_episode(self, question: str, root_cause: str) -> None:
        vec = json.dumps(embed(f"{question}\n{root_cause}"))  # embed what you will search by
        self.db.execute(
            "INSERT INTO episodes VALUES (?, ?, ?, ?)", (redact(question), redact(root_cause), vec, time.time())
        )

    def recall(self, question: str, k: int = 2, min_score: float = 0.2) -> list[dict]:
        q = embed(question)
        rows = self.db.execute("SELECT question, root_cause, vec FROM episodes").fetchall()
        scored = [{"question": r[0], "root_cause": r[1], "score": round(cosine(q, json.loads(r[2])), 3)} for r in rows]
        return sorted((s for s in scored if s["score"] >= min_score), key=lambda s: -s["score"])[:k]


def main() -> None:
    m = LongTermMemory()  # ":memory:" for the demo; use a file path (e.g. ~/.m02/memory.db) to persist
    m.remember("payments_timeout", "2s; charges are NOT idempotent - never blind-retry")
    m.remember("oncall", "bob@example.com password=hunter2")
    m.remember("freeze", "release freeze active", ttl_s=0.01)
    time.sleep(0.02)
    print("facts (redacted, expired one gone):", m.facts())
    m.record_episode("why is checkout slow?", "payments provider latency (payment-provider.authorize p95 1.9s)")
    m.record_episode("orders failing with 503", "payments-service down after a bad deploy")
    for q in ("checkout is slow again", "payments 503 errors", "is search healthy?"):
        print(f"recall({q!r}) ->", m.recall(q))


if __name__ == "__main__":
    main()
