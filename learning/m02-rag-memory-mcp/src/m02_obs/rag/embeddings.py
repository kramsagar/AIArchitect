"""Embedders. `HashingEmbedder` is a deterministic, dependency-free baseline (feature hashing of words + bigrams):
good enough to learn retrieval mechanics and to run in CI. `SentenceTransformerEmbedder` is a real dense model
(all-MiniLM-L6-v2, 384 dims, runs on CPU). Claude has no embeddings API; Voyage AI is Anthropic's recommendation."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

TOKEN = re.compile(r"[a-z0-9_]+")
STOP = set(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "why",
        "with",
    ]
)  # noqa: E501


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def tokenize(text: str) -> list[str]:
    """Lowercase words without stopwords; CamelCase alert names are split (ShopSphereHighP99)."""
    return [t for t in TOKEN.findall(CAMEL.sub(" ", text).lower()) if t not in STOP]


def _stem(t: str) -> str:
    for suf in ("ing", "es", "ed", "s"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[: -len(suf)]
    return t


class HashingEmbedder:
    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim
        self.name = f"hashing-{dim}"

    def _vec(self, text: str) -> list[float]:
        toks = [_stem(t) for t in tokenize(text)]
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False)]
        v = [0.0] * self.dim
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0  # signed hashing reduces collision bias
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class SentenceTransformerEmbedder:
    def __init__(self, model: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer  # optional: pip install -e ".[embeddings]"

        self._model = SentenceTransformer(model)
        self.dim = self._model.get_sentence_embedding_dimension()
        self.name = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()


def build_embedder(name: str = "hashing") -> Embedder:
    return HashingEmbedder() if name == "hashing" else SentenceTransformerEmbedder(name)
