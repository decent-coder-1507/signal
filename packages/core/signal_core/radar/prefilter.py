"""cheap_prefilter (§6.3 step 4): embedding similarity to interest-profile vectors + keyword allow/deny.
Items below prefilter_min are archived with zero LLM cost. Manual captures skip the prefilter.

Two scores (ADR-026):
- legacy: max over profile vectors of max(cosine × weight factor, keyword score). Kept for embedders without a
  hybrid scale (mock mode stays byte-for-byte deterministic).
- hybrid: w·scale(cosine to keyword-seeded topic centroids) + (1−w)·min(1, 2·keyword score). The centroids are the
  mean embedding of recent items that clearly match a topic's keywords, so they live in the same space as article
  embeddings; one embedding of "topic: kw1, kw2 …" does not (on the real-data benchmark it ranked items worse than
  the keywords alone).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from signal_core.config.schemas import ScoringCfg
from signal_core.embeddings import cosine, mean_vec

CENTROID = "centroid"


@dataclass
class ProfileVec:
    label: str
    ring: str
    weight: float
    vec: list[float]
    keywords: list[str]
    kind: str = "topic"  # topic | goal | stack | centroid


@dataclass
class PrefilterResult:
    score: float
    best_label: str | None
    ring: str | None
    blocked: bool
    keyword_hits: list[str]


@lru_cache(maxsize=256)
def _kw_rx_cached(words: tuple[str, ...]) -> re.Pattern[str] | None:
    ws = [w for w in words if w.strip()]
    if not ws:
        return None
    alts = "|".join(re.escape(w) for w in sorted(ws, key=len, reverse=True))
    return re.compile(r"(?<![\w-])(" + alts + r")(?:s|es)?(?![\w-])", re.I)  # tolerate plurals


def _kw_rx(words: list[str]) -> re.Pattern[str] | None:
    return _kw_rx_cached(tuple(words))


def weight_factor(weight: float) -> float:
    return 0.6 + 0.4 * min(weight, 1.0)


def keyword_score(title: str, hay: str, pv: ProfileVec) -> tuple[float, set[str]]:
    rx = _kw_rx(pv.keywords)
    if rx is None:
        return 0.0, set()
    found = {m.group(0).lower() for m in rx.finditer(hay)}
    if not found:
        return 0.0, set()
    kw = (0.45 if rx.search(title) else 0.32) * weight_factor(pv.weight)
    # One generic single-word hit ("agents" in a history story) is weak evidence on its own.
    only = next(iter(found))
    if len(found) == 1 and " " not in only and "-" not in only:
        kw *= 0.5
    return kw, found


def scale(cos: float, lo: float, hi: float) -> float:
    return max(0.0, min(1.0, (cos - lo) / (hi - lo))) if hi > lo else max(0.0, min(1.0, cos))


def prefilter(
    item_vec: list[float],
    title: str,
    text: str,
    profile: list[ProfileVec],
    blocked_keywords: list[str],
    blocked_entities: list[str],
    cfg: ScoringCfg | None = None,
    embedder: str | None = None,
) -> PrefilterResult:
    hay = f"{title}\n{text[:4000]}"
    deny = _kw_rx(blocked_keywords + blocked_entities)
    if deny and deny.search(hay):
        return PrefilterResult(0.0, None, None, True, [])
    hy = cfg.prefilter_hybrid if cfg is not None else None
    if hy is not None and embedder in hy.cosine_scale:
        return _hybrid(item_vec, title, hay, profile, hy.embedding_weight, *hy.cosine_scale[embedder])
    best, best_label, best_ring = 0.0, None, None
    hits: list[str] = []
    for pv in profile:
        if pv.kind == CENTROID:
            continue
        sim = cosine(item_vec, pv.vec) * weight_factor(pv.weight)
        kw, found = keyword_score(title, hay, pv)
        if found:
            hits.extend(sorted(found))
            sim = max(sim, kw)
        if sim > best:
            best, best_label, best_ring = sim, pv.label, pv.ring
    return PrefilterResult(round(min(best, 1.0), 4), best_label, best_ring, False, sorted(set(hits)))


def _hybrid(
    item_vec: list[float], title: str, hay: str, profile: list[ProfileVec], w: float, lo: float, hi: float
) -> PrefilterResult:
    centroids = [pv for pv in profile if pv.kind == CENTROID]
    emb_vecs = centroids or [pv for pv in profile if pv.kind == "topic"]
    emb_best, emb_pv = 0.0, None
    for pv in emb_vecs:
        sim = cosine(item_vec, pv.vec) * weight_factor(pv.weight)
        if sim > emb_best:
            emb_best, emb_pv = sim, pv
    kw_best, kw_pv = 0.0, None
    hits: set[str] = set()
    for pv in profile:
        if pv.kind != "topic":
            continue
        kw, found = keyword_score(title, hay, pv)
        hits |= found
        if kw > kw_best:
            kw_best, kw_pv = kw, pv
    emb_part = w * scale(emb_best, lo, hi)
    kw_part = (1 - w) * min(1.0, 2 * kw_best)
    lead = kw_pv if kw_part > emb_part else emb_pv
    score = emb_part + kw_part
    return PrefilterResult(
        round(min(score, 1.0), 4),
        lead.label if lead else None,
        lead.ring if lead else None,
        False,
        sorted(hits),
    )


def keyword_centroids(
    rows: Iterable[tuple[str, str, list[float]]],
    topics: list[tuple[str, str, float, list[str]]],
    min_items: int = 20,
) -> dict[str, list[float]]:
    """Topic centroids seeded by keywords: the mean embedding of items whose title + text name ≥ 2 distinct keywords
    of the topic (falling back to items with a keyword in the title when that set is small). No labels needed.

    rows: (title, text, embedding); topics: (name, ring, weight, keywords). Topics with fewer than `min_items`
    matches get no centroid (the prefilter then falls back to the topic-text vectors)."""
    data = list(rows)
    out: dict[str, list[float]] = {}
    for name, _ring, _w, kws in topics:
        rx = _kw_rx(kws)
        if rx is None:
            continue
        multi = [
            v for t, x, v in data if len({m.group(0).lower() for m in rx.finditer(f"{t} {x[:4000]}")}) >= 2
        ]
        sel = multi if len(multi) >= min_items else [v for t, _x, v in data if rx.search(t)]
        if len(sel) >= min_items:
            out[name] = mean_vec(sel)
    return out
