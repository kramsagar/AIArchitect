"""Lab 3 - prompt engineering vs context engineering: assemble the best incident context under a token budget.

Run: python -m m01_agent.labs.l03_context_engineering"""

from __future__ import annotations

from dataclasses import dataclass

from ..tokens import count_tokens
from .l01_llm_basics import cosine, embed


@dataclass
class Item:
    kind: str  # alert | deploy | runbook | log | metric | chat
    text: str
    priority: int  # 0 = must include, higher = optional
    age_min: float = 0.0


CANDIDATES = [
    Item("alert", "PAGE checkout-api p99 620ms > SLO 300ms for 10m; burn rate 8.4x", 0, 2),
    Item("deploy", "checkout-api v2.31.0 rolled out 25m ago: DB pool size 50 -> 20", 1, 25),
    Item("metric", "inventory-db connections 20/20 in use from checkout-api; queue wait p95 480ms", 1, 1),
    Item("runbook", "Runbook checkout-latency: check DB pool saturation, recent deploys, inventory-db health", 2),
    Item("runbook", "Runbook payments-5xx: check PSP status page and fraud-scoring latency", 2),
    Item("log", "ERROR checkout-api upstream timeout inventory-db latency_ms=2034 pool_in_use=20/20", 3, 1),
    Item("log", "INFO checkout-api cart updated user=8812 items=3", 5, 1),
    Item("chat", "on-call: 'is this the same as last week's search regression?'", 4, 5),
    Item("metric", "search-api p99 70ms within SLO", 5, 1),
]


def build_context(question: str, items: list[Item], budget_tokens: int) -> tuple[list[Item], list[Item]]:
    """Rank by (priority, -relevance, recency); always keep priority 0; fill until the budget is spent."""
    q = embed(question)
    ranked = sorted(items, key=lambda it: (it.priority, -cosine(q, embed(it.text)), it.age_min))
    chosen, dropped, used = [], [], 0
    for it in ranked:
        cost = count_tokens(it.text) + 4
        if it.priority == 0 or used + cost <= budget_tokens:
            chosen.append(it)
            used += cost
        else:
            dropped.append(it)
    return chosen, dropped


def render(chosen: list[Item]) -> str:
    sections: dict[str, list[str]] = {}
    for it in chosen:
        sections.setdefault(it.kind, []).append(f"- {it.text}")
    return "\n".join(f"## {k}\n" + "\n".join(v) for k, v in sections.items())


def main() -> None:
    question = "Why is checkout-api slow right now?"
    for budget in (60, 140):
        chosen, dropped = build_context(question, CANDIDATES, budget)
        print(f"\n===== budget {budget} tokens: {len(chosen)} kept, {len(dropped)} dropped =====")
        print(render(chosen))
        print("dropped:", [f"{d.kind}:{d.text[:30]}" for d in dropped])
    print(
        "\nPrompt engineering = how you phrase the ask. Context engineering = WHAT the model sees: selection,\n"
        "ordering, compression and budget. In production the second one decides answer quality."
    )


if __name__ == "__main__":
    main()
