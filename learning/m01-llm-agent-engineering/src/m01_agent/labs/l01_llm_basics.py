"""Lab 1 - tokens, context window, embeddings, temperature (SRE edition).

Run: python -m m01_agent.labs.l01_llm_basics"""

from __future__ import annotations

import hashlib
import math
import random

from ..tokens import count_tokens, tokenize

LOG_LINE = (
    "2026-11-11T09:41:07.212Z ERROR checkout-api pod=checkout-7f9c trace_id=4bf92f3577b34da6 "
    'msg="upstream timeout" upstream=inventory-db latency_ms=2034 pool_in_use=20/20'
)


def tokens_and_cost(rps: float = 12_400, error_ratio: float = 0.004, usd_per_m_input: float = 0.15) -> dict:
    """What does it cost to send every error log line to an LLM? (spoiler: aggregate first)."""
    per_line = count_tokens(LOG_LINE)
    lines_per_day = rps * error_ratio * 86_400
    tokens_per_day = per_line * lines_per_day
    return {
        "tokens_per_log_line": per_line,
        "error_lines_per_day": round(lines_per_day),
        "tokens_per_day": round(tokens_per_day),
        "usd_per_day_at_price": round(tokens_per_day / 1e6 * usd_per_m_input, 2),
    }


def context_budget(window: int = 128_000, reserved_output: int = 4_000) -> dict:
    """Budget the window like memory on a node: fixed parts first, the remainder is for evidence."""
    fixed = {"system+developer": 900, "tool_schemas": 600, "conversation_memory": 1_500}
    evidence = window - reserved_output - sum(fixed.values())
    return {
        **fixed,
        "reserved_output": reserved_output,
        "evidence_budget": evidence,
        "log_lines_that_fit": evidence // max(1, count_tokens(LOG_LINE)),
    }


def embed(text: str, dim: int = 256) -> list[float]:
    """Toy embedding: hashed word + character-trigram features, L2-normalised. Real models learn meaning;
    this only captures surface overlap, but the vector maths (cosine similarity) is identical."""
    vec = [0.0] * dim
    words = text.lower().split()
    feats = words + [w[i : i + 3] for w in words for i in range(max(1, len(w) - 2))]
    for f in feats:
        h = int(hashlib.md5(f.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0 if (h >> 8) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


PAST_INCIDENTS = [
    "INC-101 checkout latency spike after connection pool reduced, db pool exhausted",
    "INC-087 payments 5xx from card network provider timeouts",
    "INC-142 search p99 regression after opensearch shard rebalance",
    "INC-066 auth token validation slow due to jwks cache miss storm",
    "INC-120 inventory-db cpu saturation during nightly reindex",
]


def similar_incidents(query: str, k: int = 3) -> list[tuple[str, float]]:
    q = embed(query)
    scored = [(inc, round(cosine(q, embed(inc)), 3)) for inc in PAST_INCIDENTS]
    return sorted(scored, key=lambda x: x[1], reverse=True)[:k]


def softmax(logits: list[float], temperature: float) -> list[float]:
    if temperature <= 0:  # greedy decoding
        best = max(range(len(logits)), key=logits.__getitem__)
        return [1.0 if i == best else 0.0 for i in range(len(logits))]
    scaled = [x / temperature for x in logits]
    m = max(scaled)
    exps = [math.exp(x - m) for x in scaled]
    total = sum(exps)
    return [e / total for e in exps]


CANDIDATES = ["db pool exhausted", "bad deploy", "network partition", "noisy neighbour", "cosmic rays"]
LOGITS = [3.2, 2.6, 1.1, 0.7, -2.0]


def sample(temperature: float, n: int = 1000, seed: int = 1) -> dict[str, int]:
    rng = random.Random(seed)
    probs = softmax(LOGITS, temperature)
    counts = dict.fromkeys(CANDIDATES, 0)
    for _ in range(n):
        counts[rng.choices(CANDIDATES, probs)[0]] += 1
    return counts


def main() -> None:
    print("== 1. Tokens ==")
    print(tokenize(LOG_LINE)[:24], "...")
    print(tokens_and_cost())
    print("\n== 2. Context window budget (128K) ==")
    print(context_budget())
    print("\n== 3. Embeddings: which past incident is closest? ==")
    for inc, score in similar_incidents("checkout api slow, connection pool at 20/20, upstream timeout"):
        print(f"  {score:+.3f}  {inc}")
    print("\n== 4. Temperature: sampling the 'root cause' token 1000 times ==")
    for t in (0.0, 0.2, 1.0, 2.0):
        print(f"  T={t}: {sample(t)}")
    print("\nTakeaway: T=0 for RCA/tool calls (repeatable); higher T only for brainstorming hypotheses.")


if __name__ == "__main__":
    main()
