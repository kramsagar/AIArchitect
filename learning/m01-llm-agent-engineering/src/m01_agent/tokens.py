"""Token counting. Uses tiktoken when installed, otherwise the ~4 characters/token rule of thumb."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _encoder() -> Any | None:
    try:
        import tiktoken

        return tiktoken.get_encoding("o200k_base")
    except Exception:  # not installed, or the BPE file cannot be downloaded (offline)
        return None


def count_tokens(text: str) -> int:
    enc = _encoder()
    if enc is not None:
        return len(enc.encode(text))
    return max(1, round(len(text) / 4)) if text else 0


def tokenize(text: str) -> list[str]:
    """Token pieces for teaching purposes (real BPE pieces when tiktoken is available)."""
    enc = _encoder()
    if enc is not None:
        return [enc.decode([t]) for t in enc.encode(text)]
    pieces: list[str] = []
    for word in text.split(" "):
        pieces.extend(word[i : i + 4] for i in range(0, len(word), 4))
    return pieces


def count_message_tokens(messages: list[dict[str, Any]]) -> int:
    # ~4 tokens of per-message overhead (role, separators) on top of the content.
    total = 0
    for m in messages:
        content = m.get("content") or ""
        total += 4 + count_tokens(content if isinstance(content, str) else json.dumps(content))
        if m.get("tool_calls"):
            total += count_tokens(json.dumps(m["tool_calls"]))
    return total
