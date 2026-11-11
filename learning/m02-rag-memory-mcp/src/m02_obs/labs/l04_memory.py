"""Lab 4 - memory tiers: session window + summary, long-term facts with TTL, episodic recall, redaction.

python -m m02_obs.labs.l04_memory
"""

from m02_obs.memory import LongTermMemory, SessionMemory


def main() -> None:
    s = SessionMemory(max_turns=2)
    chat = [
        ("is checkout ok?", "Yes. All green."),
        ("and payments?", "Healthy. p95 31 ms."),
        ("what changed today?", "Nothing. No active faults."),
        ("why is search slow?", "It is not. p95 48 ms."),
    ]
    for q, a in chat:
        s.add(q, a)
    print("session messages sent to the LLM (fixed size, however long the chat):")
    for m in s.messages():
        print(f"  {m['role']:9} {m['content'][:90]!r}")

    ltm = LongTermMemory()  # in-memory SQLite; the CLI uses ~/.m02/memory.db
    ltm.remember("payments_timeout", "2s budget, not idempotent - never blind-retry")
    ltm.remember("oncall_note", "contact bob@example.com, password=hunter2")  # redacted on write
    print("\nfacts:", ltm.facts())

    ltm.record_episode("why is checkout slow?", "payments provider slow", "payment-provider.authorize p95 1.9s",
                       ["payments-service"])  # fmt: skip
    ltm.record_episode("orders failing with 503", "payments down after deploy", "bad payments deploy",
                       ["payments-service"])  # fmt: skip
    for q in ("checkout is slow again", "payments 503 errors", "is search healthy"):
        print(f"recall({q!r}):", [(e["root_cause"], e["score"]) for e in ltm.recall(q, min_score=0)])
    print("\nExercise: what min_score stops 'is search healthy' from recalling an unrelated incident?")


if __name__ == "__main__":
    main()
