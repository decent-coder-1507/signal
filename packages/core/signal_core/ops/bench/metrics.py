"""Pure metric functions for the real-data benchmark (ADR-026)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PRF:
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int

    def as_dict(self) -> dict[str, float]:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


def prf(pred: Sequence[bool], gold: Sequence[bool]) -> PRF:
    tp = sum(1 for p, g in zip(pred, gold, strict=True) if p and g)
    fp = sum(1 for p, g in zip(pred, gold, strict=True) if p and not g)
    fn = sum(1 for p, g in zip(pred, gold, strict=True) if g and not p)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return PRF(p, r, f, tp, fp, fn)


def dcg(gains: Sequence[float], k: int) -> float:
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains[:k]))


def ndcg_at_k(scores: Sequence[float], gains: Sequence[float], k: int) -> float:
    """NDCG@k of a ranking by `scores` (desc; ties broken by original order) against graded `gains`."""
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    ideal = dcg(sorted(gains, reverse=True), k)
    return dcg([gains[i] for i in order], k) / ideal if ideal > 0 else 0.0


def precision_at_k(scores: Sequence[float], relevant: Sequence[bool], k: int) -> float:
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:k]
    return sum(1 for i in order if relevant[i]) / max(1, min(k, len(order)))


def recall_at_k(ranked_ids: Sequence[str], target: str, k: int) -> float:
    return 1.0 if target in list(ranked_ids)[:k] else 0.0


def reciprocal_rank(ranked_ids: Sequence[str], target: str) -> float:
    ids = list(ranked_ids)
    return 1.0 / (ids.index(target) + 1) if target in ids else 0.0


def roc_auc(scores: Sequence[float], positive: Sequence[bool]) -> float:
    """Probability that a random positive outscores a random negative (ties count half)."""
    pos = [s for s, y in zip(scores, positive, strict=True) if y]
    neg = [s for s, y in zip(scores, positive, strict=True) if not y]
    if not pos or not neg:
        return 0.0
    wins = sum((1.0 if p > n else 0.5 if p == n else 0.0) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def cohen_kappa(a: Sequence[object], b: Sequence[object]) -> float:
    n = len(a)
    if n == 0:
        return 0.0
    cats = sorted({*a, *b}, key=str)
    po = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    pe = sum((list(a).count(c) / n) * (list(b).count(c) / n) for c in cats)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    def ranks(v: Sequence[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for t in range(i, j + 1):
                r[order[t]] = (i + j) / 2
            i = j + 1
        return r

    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (vx * vy) if vx and vy else 0.0
