"""Feedback → personalisation (§6.9).

(a) Learned-preference model: L2-regularised logistic regression on sparse features (topics, entities, sources,
    content types, ring), retrained nightly and after feedback. Pure numpy; no extra dependency.
(b) Per-topic weight nudges, bounded to ±feedback_max_weight_shift_per_month (default 20%) per calendar month.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.base import OWNER_ID
from signal_core.db.models import (
    Feedback,
    Item,
    ItemEnrichment,
    PreferenceModel,
    Profile,
    Source,
    Story,
    StoryItem,
)

LABELS: dict[str, float] = {
    "useful": 1.0,
    "more": 1.0,
    "used": 1.0,
    "saved": 1.0,
    "opened": 0.65,
    "not_for_me": 0.0,
    "less": 0.0,
    "known": 0.35,
    "wrong": 0.2,
}
NUDGE: dict[str, float] = {"more": 0.04, "useful": 0.02, "used": 0.02, "less": -0.04, "not_for_me": -0.03}
MIN_EXAMPLES = 6


async def story_features(session: AsyncSession, story_ids: list[uuid.UUID]) -> dict[uuid.UUID, set[str]]:
    rows = (
        await session.execute(
            select(
                StoryItem.story_id,
                Source.name,
                Item.content_type,
                ItemEnrichment.topics,
                ItemEnrichment.entities,
                ItemEnrichment.ring,
            )
            .join(Item, Item.id == StoryItem.item_id)
            .join(Source, Source.id == Item.source_id)
            .outerjoin(ItemEnrichment, ItemEnrichment.item_id == Item.id)
            .where(StoryItem.story_id.in_(story_ids))
        )
    ).all()
    feats: dict[uuid.UUID, set[str]] = defaultdict(set)
    for sid, src, ctype, topics, ents, ring in rows:
        f = feats[sid]
        f.add(f"src:{src}")
        f.add(f"type:{ctype}")
        if ring:
            f.add(f"ring:{ring}")
        for t in topics or []:
            f.add(f"topic:{t}")
        for k, names in (ents or {}).items():
            for n in names[:5]:
                f.add(f"ent:{k}:{n.lower()}")
    return feats


def train(
    X: list[set[str]], y: list[float], l2: float = 0.1, epochs: int = 300, lr: float = 0.5
) -> tuple[dict[str, float], float]:
    vocab = sorted({f for row in X for f in row})
    idx = {f: i for i, f in enumerate(vocab)}
    M = np.zeros((len(X), len(vocab)))
    for r, row in enumerate(X):
        for f in row:
            M[r, idx[f]] = 1.0
    Y = np.asarray(y, dtype=float)
    w = np.zeros(len(vocab))
    b = 0.0
    n = max(len(X), 1)
    for _ in range(epochs):
        p = 1 / (1 + np.exp(-(M @ w + b)))
        g = p - Y
        w -= lr * (M.T @ g / n + l2 * w)
        b -= lr * float(g.mean())
    return {f: float(w[i]) for f, i in idx.items() if abs(w[i]) > 1e-4}, b


def predict(weights: dict[str, float], bias: float, feats: set[str]) -> float:
    z = bias + sum(weights.get(f, 0.0) for f in feats)
    return 1 / (1 + math.exp(-max(min(z, 30), -30)))


async def retrain(session: AsyncSession) -> PreferenceModel | None:
    fb = (
        await session.execute(
            select(Feedback.target_id, Feedback.kind)
            .where(Feedback.target_type == "story", Feedback.kind.in_(list(LABELS)))
            .order_by(Feedback.created_at)
        )
    ).all()
    latest: dict[uuid.UUID, float] = {}
    for tid, kind in fb:  # last explicit judgement per story wins
        latest[tid] = LABELS[kind]
    if len(latest) < MIN_EXAMPLES:
        return None
    feats = await story_features(session, list(latest))
    ids = [i for i in latest if feats.get(i)]
    weights, bias = train([feats[i] for i in ids], [latest[i] for i in ids])
    ver = ((await session.execute(select(func.max(PreferenceModel.version)))).scalar() or 0) + 1
    pm = PreferenceModel(
        version=ver,
        features=sorted(weights),
        weights={"w": weights, "b": bias},
        metrics={"examples": len(ids), "positives": sum(1 for i in ids if latest[i] >= 0.5)},
    )
    session.add(pm)
    await session.flush()
    return pm


async def latest_model(session: AsyncSession) -> PreferenceModel | None:
    return (
        (await session.execute(select(PreferenceModel).order_by(PreferenceModel.version.desc()).limit(1)))
        .scalars()
        .first()
    )


async def learned_scores(session: AsyncSession, story_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
    pm = await latest_model(session)
    if pm is None:
        return {s: 0.5 for s in story_ids}
    feats = await story_features(session, story_ids)
    w, b = pm.weights.get("w", {}), float(pm.weights.get("b", 0.0))
    return {s: predict(w, b, feats.get(s, set())) for s in story_ids}


async def nudge_topics(session: AsyncSession, story: Story, kind: str, now: datetime) -> dict[str, Any]:
    """Bounded per-topic weight nudge. Profile.topics[ring][i].adj = {month, delta}; |delta| ≤ max shift."""
    step = NUDGE.get(kind)
    if not step or not story.topics:
        return {}
    cap = get_config().scoring.feedback_max_weight_shift_per_month
    month = now.strftime("%Y-%m")
    p = (await session.execute(select(Profile).where(Profile.user_id == OWNER_ID))).scalar_one_or_none()
    if p is None:
        return {}
    topics = {ring: [dict(t) for t in lst] for ring, lst in (p.topics or {}).items()}
    changed: dict[str, float] = {}
    for lst in topics.values():
        for t in lst:
            if t["name"] in story.topics:
                adj = t.get("adj") or {}
                if adj.get("month") != month and adj.get("delta"):
                    # Fold last month's bounded drift into the base weight, then start a fresh monthly budget.
                    t["weight"] = round(
                        min(2.0, max(0.0, float(t.get("weight", 1.0)) * (1 + adj["delta"]))), 4
                    )
                delta = adj.get("delta", 0.0) if adj.get("month") == month else 0.0
                delta = max(-cap, min(cap, delta + step))
                t["adj"] = {"month": month, "delta": round(delta, 4)}
                changed[t["name"]] = t["adj"]["delta"]
    p.topics = topics
    await session.flush()
    return changed


def effective_weight(topic: dict[str, Any]) -> float:
    adj = (topic.get("adj") or {}).get("delta", 0.0)
    return float(topic.get("weight", 1.0)) * (1 + float(adj))
