"""Short-term conversation memory with a token budget, plus a small key-value fact store.

Only final user/assistant turns are kept (tool chatter is dropped) - that is the cheapest form of
"summarised" history and keeps the context window predictable."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .schemas import AssistantResponse
from .tokens import count_tokens


@dataclass
class Turn:
    user: str
    assistant: str


class ConversationMemory:
    def __init__(self, max_turns: int = 6, max_tokens: int = 1500) -> None:
        self.max_tokens = max_tokens
        self.turns: deque[Turn] = deque(maxlen=max_turns)
        self.facts: dict[str, str] = {}

    def add(self, user: str, response: AssistantResponse, facts: dict[str, str] | None = None) -> None:
        self.turns.append(Turn(user=user, assistant=response.model_dump_json()))
        if facts:
            self.facts.update(facts)

    def messages(self) -> list[dict[str, str]]:
        """Newest turns first until the token budget is spent, returned in chronological order."""
        selected: list[Turn] = []
        used = 0
        for turn in reversed(self.turns):
            cost = count_tokens(turn.user) + count_tokens(turn.assistant) + 8
            if used + cost > self.max_tokens:
                break
            selected.append(turn)
            used += cost
        out: list[dict[str, str]] = []
        for turn in reversed(selected):
            out += [{"role": "user", "content": turn.user}, {"role": "assistant", "content": turn.assistant}]
        return out

    def clear(self) -> None:
        self.turns.clear()
        self.facts.clear()
