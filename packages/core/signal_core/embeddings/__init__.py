"""Embedding providers (§15.1): MockEmbeddingProvider (default in mock mode), FastEmbedProvider (local)."""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import math
import re
from typing import Any

import numpy as np

from signal_core.llm.provider import EmbeddingProvider

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-\.]*[a-z0-9]|[a-z0-9]")
STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "by",
        "at",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "its",
        "this",
        "that",
        "as",
        "into",
        "about",
        "than",
        "then",
        "but",
        "not",
        "no",
        "new",
        "now",
        "has",
        "have",
        "had",
        "will",
        "can",
        "just",
        "more",
        "most",
        "also",
    ]
)


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOP]


class MockEmbeddingProvider:
    """Deterministic hashed bag-of-words (+ bigrams) vectors, L2-normalised.

    Cosine similarity reflects lexical overlap, which is enough for deterministic dedupe/cluster tests.
    """

    name = "mock"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dim, dtype=np.float64)
        toks = tokens(text)
        feats = toks + [f"{a}_{b}" for a, b in itertools.pairwise(toks)]
        for f in feats:
            h = hashlib.blake2b(f.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if h[4] & 1 else -1.0
            v[idx] += sign * (1.0 if "_" not in f else 0.5)
        n = float(np.linalg.norm(v))
        if n == 0:
            v[0] = 1.0
            n = 1.0
        return [float(x) for x in v / n]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class FastEmbedProvider:
    name = "fastembed"

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5", dim: int = 384) -> None:
        self.dim = dim
        self.model_name = model
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding  # optional extra: signal-core[local-embeddings]

            self._model = TextEmbedding(self.model_name)
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vecs = await asyncio.to_thread(lambda: [v.tolist() for v in model.embed(texts)])
        return vecs


def cosine(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    a_, b_ = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    na, nb = float(np.linalg.norm(a_)), float(np.linalg.norm(b_))
    if na == 0 or nb == 0:
        return 0.0
    return float(a_ @ b_ / (na * nb))


def mean_vec(vs: list[list[float]]) -> list[float]:
    m = np.mean(np.asarray(vs, dtype=np.float64), axis=0)
    n = float(np.linalg.norm(m)) or 1.0
    return [float(x) for x in m / n]


_provider: EmbeddingProvider | None = None


def get_embedder() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        from signal_core.settings import get_settings

        s = get_settings()
        _provider = (
            FastEmbedProvider(dim=s.embedding_dim)
            if s.embedding_provider == "fastembed" and not s.is_mock
            else MockEmbeddingProvider(s.embedding_dim)
        )
    return _provider


def set_embedder(p: EmbeddingProvider | None) -> None:
    global _provider
    _provider = p


__all__ = [
    "FastEmbedProvider",
    "MockEmbeddingProvider",
    "cosine",
    "get_embedder",
    "math",
    "mean_vec",
    "tokens",
]
