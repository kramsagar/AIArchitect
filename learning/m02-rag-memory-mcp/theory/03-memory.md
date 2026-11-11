# 03 · Memory: working, session, long-term, episodic

| Tier | Lifetime | Here | Production |
|---|---|---|---|
| Working | one run | the message list in `Investigator.run` | same; bounded by tool-result caps |
| Session (short-term) | one conversation | `SessionMemory`: last N turns + rolling summary | Redis with TTL, keyed by session id |
| Semantic / long-term facts | until changed | `LongTermMemory.remember` (SQLite, TTL optional) | Postgres table, owned and versioned |
| Episodic | months | `record_episode` / `recall` (past investigations, embedded) | pgvector table; retention policy |

## Why not "just keep the whole chat"?
Cost and latency grow linearly with history; quality *drops* when old, irrelevant turns crowd the context ("lost in the
middle"). A fixed budget (N turns + a summary of ≤ 800 chars) keeps every request the same size at turn 5 or 500.

## Episodic memory for SRE
Incidents repeat. After an investigation with a cause, the agent stores question, summary, root cause and services.
Next time, `recall` finds similar episodes and injects them as **hints to verify, not facts** ("last time: payment
provider latency"). The grounding check treats `episode:<id>` as a citable source only if it was really recalled.

## Memory is a data store: govern it
- **Redact before writing** (`memory.redact`: API keys, passwords, emails, card numbers). A summary of a log line can
  leak a secret into a table with a 1-year retention.
- **Scope** facts (global / team / user / tenant) and filter by scope on read.
- **TTL** for facts that go stale ("payments is degraded" must expire).
- **Poisoning:** anything written from tool output is untrusted; never let memory override system policy.
- **Right to forget:** `m02 memory --clear`; in production, per-subject deletion.

## Check yourself
1. Which tier holds "we are in an incident right now", and what TTL would you give it?
2. How would an attacker poison episodic memory through a log line, and what limits the damage?
