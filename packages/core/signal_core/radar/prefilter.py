"""cheap_prefilter (§6.3 step 4): embedding similarity to interest-profile vectors + keyword allow/deny.
Items below prefilter_min are archived with zero LLM cost. Manual captures skip the prefilter."""

from __future__ import annotations

import re
from dataclasses import dataclass

from signal_core.embeddings import cosine


@dataclass
class ProfileVec:
    label: str
    ring: str
    weight: float
    vec: list[float]
    keywords: list[str]


@dataclass
class PrefilterResult:
    score: float
    best_label: str | None
    ring: str | None
    blocked: bool
    keyword_hits: list[str]


def _kw_rx(words: list[str]) -> re.Pattern[str] | None:
    words = [w for w in words if w.strip()]
    if not words:
        return None
    alts = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(r"(?<![\w-])(" + alts + r")(?:s|es)?(?![\w-])", re.I)  # tolerate plurals


def prefilter(
    item_vec: list[float],
    title: str,
    text: str,
    profile: list[ProfileVec],
    blocked_keywords: list[str],
    blocked_entities: list[str],
) -> PrefilterResult:
    hay = f"{title}\n{text[:4000]}"
    deny = _kw_rx(blocked_keywords + blocked_entities)
    if deny and deny.search(hay):
        return PrefilterResult(0.0, None, None, True, [])
    best, best_label, best_ring = 0.0, None, None
    hits: list[str] = []
    for pv in profile:
        sim = cosine(item_vec, pv.vec) * (0.6 + 0.4 * min(pv.weight, 1.0))
        rx = _kw_rx(pv.keywords)
        if rx:
            found = {m.group(0).lower() for m in rx.finditer(hay)}
            if found:
                hits.extend(sorted(found))
                in_title = bool(rx.search(title))
                kw = (0.45 if in_title else 0.32) * (0.6 + 0.4 * min(pv.weight, 1.0))
                # One generic single-word hit ("agents" in a history story) is weak evidence on its own.
                if len(found) == 1 and " " not in next(iter(found)) and "-" not in next(iter(found)):
                    kw *= 0.5
                sim = max(sim, kw)
        if sim > best:
            best, best_label, best_ring = sim, pv.label, pv.ring
    return PrefilterResult(round(min(best, 1.0), 4), best_label, best_ring, False, sorted(set(hits)))
