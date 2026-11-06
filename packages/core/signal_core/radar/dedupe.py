"""Deduplication (§6.3 step 3): exact (canonical URL hash, external id, text hash) and near-duplicate
(64-bit SimHash over word 3-shingles, or embedding cosine ≥ threshold within a time window)."""

from __future__ import annotations

import hashlib
import re

_WORD = re.compile(r"[a-z0-9]+")
MASK64 = (1 << 64) - 1


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def simhash(text: str, shingle: int = 3) -> int:
    """64-bit SimHash. Returned as a signed int64 so it fits a Postgres BIGINT."""
    words = _words(text)
    feats = (
        [" ".join(words[i : i + shingle]) for i in range(max(len(words) - shingle + 1, 1))] if words else []
    )
    if not feats:
        return 0
    v = [0] * 64
    for f in feats:
        h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if v[i] > 0:
            out |= 1 << i
    return out - (1 << 64) if out >= (1 << 63) else out


def hamming(a: int, b: int) -> int:
    return ((a & MASK64) ^ (b & MASK64)).bit_count()


def is_near_dup_simhash(a: int, b: int, max_distance: int) -> bool:
    return hamming(a, b) <= max_distance


def dedupe_text(title: str, text: str) -> str:
    """Text used for SimHash: title + body, so short-summary feeds still dedupe sensibly."""
    return f"{title}\n{text}"[:20000]


CONTAINMENT_MIN = 0.90  # rewrites of one event top out ~0.84 on the fixture set; true copies ~1.0


def shingles(text: str, k: int = 3) -> set[str]:
    w = _words(text)
    return {" ".join(w[i : i + k]) for i in range(max(len(w) - k + 1, 0))}


def containment(a: set[str], b: set[str]) -> float:
    """|A∩B| / min(|A|,|B|): robust for short texts where one copy adds a boilerplate line."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))
