"""FSRS-4.5 spaced-repetition scheduler (§9.4), implemented from the published FSRS-4.5 formulas
(open-spaced-repetition/fsrs4anki wiki, "The Algorithm"), default weights, desired retention 0.9.

Ratings: 1 Again, 2 Hard, 3 Good, 4 Easy.
  R(t, S)  = (1 + FACTOR·t/S)^DECAY, DECAY = −0.5, FACTOR = 19/81  (so R(S, S) = 0.9)
  I(r, S)  = S / FACTOR · (r^(1/DECAY) − 1)                         (= S when r = 0.9)
  S0(G)    = w[G−1]
  D0(G)    = w4 − (G−3)·w5, clamped to [1, 10]
  D'       = w7·D0(3) + (1−w7)·(D − w6·(G−3))                        (mean reversion), clamped to [1, 10]
  S'_recall= S·(1 + e^w8·(11−D)·S^(−w9)·(e^(w10·(1−R)) − 1)·hard·easy), hard = w15 if G=2, easy = w16 if G=4
  S'_forget= w11·D^(−w12)·((S+1)^w13 − 1)·e^(w14·(1−R))
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

W = [
    0.4872,
    1.4003,
    3.7145,
    13.8206,
    5.1618,
    1.2298,
    0.8975,
    0.031,
    1.6474,
    0.1367,
    1.0461,
    2.1072,
    0.0793,
    0.3246,
    1.587,
    0.2272,
    2.8755,
]
DECAY = -0.5
FACTOR = 19 / 81
RETENTION = 0.9
MAX_INTERVAL_DAYS = 36500


@dataclass
class CardState:
    stability: float = 0.0
    difficulty: float = 0.0
    reps: int = 0
    lapses: int = 0
    last_review: str | None = None  # ISO timestamp
    state: str = "new"  # new | review | relearning

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> CardState:
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})


def _clamp_d(d: float) -> float:
    return min(10.0, max(1.0, d))


def init_stability(g: int) -> float:
    return max(W[g - 1], 0.1)


def init_difficulty(g: int) -> float:
    return _clamp_d(W[4] - (g - 3) * W[5])


def retrievability(elapsed_days: float, stability: float) -> float:
    if stability <= 0:
        return 0.0
    return float((1 + FACTOR * elapsed_days / stability) ** DECAY)


def next_interval(stability: float, retention: float = RETENTION) -> int:
    i = stability / FACTOR * (retention ** (1 / DECAY) - 1)
    return int(min(MAX_INTERVAL_DAYS, max(1, round(i))))


def next_difficulty(d: float, g: int) -> float:
    return _clamp_d(W[7] * init_difficulty(3) + (1 - W[7]) * (d - W[6] * (g - 3)))


def stability_after_recall(d: float, s: float, r: float, g: int) -> float:
    hard = W[15] if g == 2 else 1.0
    easy = W[16] if g == 4 else 1.0
    return float(s * (1 + math.exp(W[8]) * (11 - d) * s ** (-W[9]) * (math.exp(W[10] * (1 - r)) - 1) * hard * easy))


def stability_after_forget(d: float, s: float, r: float) -> float:
    return float(min(s, W[11] * d ** (-W[12]) * ((s + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r))))


def review(state: CardState, rating: int, now: datetime) -> tuple[CardState, datetime]:
    """Apply one review; returns the new state and the next due time."""
    if rating not in (1, 2, 3, 4):
        raise ValueError("rating must be 1 (Again), 2 (Hard), 3 (Good) or 4 (Easy)")
    s = CardState(**asdict(state))
    if s.state == "new" or s.stability <= 0:
        s.stability, s.difficulty = init_stability(rating), init_difficulty(rating)
    else:
        last = datetime.fromisoformat(s.last_review) if s.last_review else now
        elapsed = max((now - last).total_seconds() / 86400, 0.0)
        r = retrievability(elapsed, s.stability)
        if rating == 1:
            s.stability = stability_after_forget(s.difficulty, s.stability, r)
            s.lapses += 1
        else:
            s.stability = stability_after_recall(s.difficulty, s.stability, r, rating)
        s.difficulty = next_difficulty(s.difficulty, rating)
    s.reps += 1
    s.state = "relearning" if rating == 1 else "review"
    s.last_review = now.isoformat()
    days = 1 if rating == 1 else next_interval(s.stability)
    return s, now + timedelta(days=days)
