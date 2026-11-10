"""Story scoring (§6.5) and MMR diversity re-rank.

final = Σ wᵢ·sᵢ, then penalties: duplicate-of-shown −1, blocked entity/topic −1, adjacent ring without
tech_relevance ≥ 0.6 → excluded. Every sub-score is stored in story.scores for "Why am I seeing this?".
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.base import OWNER_ID
from signal_core.db.models import Item, ItemEnrichment, Profile, ProfileVector, Source, Story, StoryItem
from signal_core.embeddings import cosine, get_embedder
from signal_core.llm import router as llm
from signal_core.llm.provider import BudgetExceeded, LLMError
from signal_core.logging import get_logger
from signal_core.radar.preference import effective_weight, learned_scores

log = get_logger("scoring")
TIER_W = {1: 1.0, 2: 0.8, 3: 0.5}
TIER_CRED = {1: 1.0, 2: 0.75, 3: 0.45}
DURABILITY = {"fundamental": 1.0, "trend": 0.6, "churn": 0.2}


def clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def scale(cos: float, lo: float, hi: float) -> float:
    return clamp((cos - lo) / (hi - lo)) if hi > lo else clamp(cos)


async def _members(
    session: AsyncSession, story_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    rows = (
        await session.execute(
            select(
                StoryItem.story_id,
                StoryItem.role,
                Item.id,
                Item.title,
                Item.signal_meta,
                Item.prefilter_score,
                Item.is_capture,
                Item.published_at,
                Source.name,
                Source.tier,
                Source.type,
                ItemEnrichment.tech_relevance,
                ItemEnrichment.summary_1line,
                ItemEnrichment.topics,
            )
            .join(Item, Item.id == StoryItem.item_id)
            .join(Source, Source.id == Item.source_id)
            .outerjoin(ItemEnrichment, ItemEnrichment.item_id == Item.id)
            .where(StoryItem.story_id.in_(story_ids))
        )
    ).all()
    out: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r.story_id, []).append(r._asdict())
    return out


def signal_strength(members: list[dict[str, Any]]) -> float:
    by_source: dict[str, int] = {}
    for m in members:
        by_source[m["name"]] = min(by_source.get(m["name"], 3), int(m["tier"]))
    base = sum(TIER_W.get(t, 0.5) for t in by_source.values())
    s = 1 - math.exp(-base / 2.0)
    meta = [m["signal_meta"] or {} for m in members]
    hn = max((float(x.get("hn_points_per_hour", 0)) for x in meta), default=0.0)
    stars = max((float(x.get("gh_stars_period", 0)) for x in meta), default=0.0)
    likes = max((float(x.get("hf_likes", 0)) + float(x.get("hf_upvotes", 0)) * 10 for x in meta), default=0.0)
    s += min(0.25, hn / 100) + min(0.15, stars / 5000) + min(0.15, likes / 10000)
    return clamp(s)


def momentum(members: list[dict[str, Any]], now: datetime, window_hours: int = 24) -> float:
    """Source-count growth (ADR-026): distinct sources reporting in the last window minus those in the window
    before, mapped to 0–1 (0.5 = flat, ≥ 0.75 = one more source than before, bounded at ±2 sources)."""
    w = timedelta(hours=window_hours)
    recent = {m["name"] for m in members if m["published_at"] and now - w < m["published_at"] <= now}
    prior = {m["name"] for m in members if m["published_at"] and now - 2 * w < m["published_at"] <= now - w}
    return clamp(0.5 + (len(recent) - len(prior)) / 4)


def credibility(members: list[dict[str, Any]]) -> float:
    best = min(int(m["tier"]) for m in members)
    c = TIER_CRED.get(best, 0.45)
    if any(m["role"] == "primary" for m in members):
        c += 0.1
    if len({m["name"] for m in members}) == 1 and best == 3:
        c *= 0.7  # single-source rumour penalty
    return clamp(c)


async def profile_vectors(
    session: AsyncSession, centroids: bool = False
) -> tuple[list[tuple[str, str, float, list[float]]], Profile | None]:
    """Profile vectors for relevance: the topic/goal/stack text vectors, or (centroids=True) the keyword-seeded
    topic centroids (ADR-026). Weights include the bounded feedback nudges."""
    p = (await session.execute(select(Profile).where(Profile.user_id == OWNER_ID))).scalar_one_or_none()
    if p is None:
        return [], None
    from signal_core.services.seed import ensure_profile_vectors

    await ensure_profile_vectors(session, p)
    eff = {t["name"]: effective_weight(t) for ring in (p.topics or {}).values() for t in ring}
    kind = ProfileVector.kind == "centroid" if centroids else ProfileVector.kind != "centroid"
    rows = (
        await session.execute(select(ProfileVector).where(ProfileVector.profile_id == p.id, kind))
    ).scalars()
    return [(r.label, r.kind, eff.get(r.label, r.weight), list(r.embedding)) for r in rows], p


async def candidate_stories(session: AsyncSession, now: datetime, window_days: int = 7) -> list[Story]:
    return list(
        (
            await session.execute(
                select(Story).where(
                    Story.status == "active", Story.last_updated >= now - timedelta(days=window_days)
                )
            )
        ).scalars()
    )


@dataclass
class ScoreContext:
    """Everything the deterministic pass needs besides the story itself (pure; the benchmark builds one too)."""

    weights: dict[str, float]
    pvs: list[tuple[str, str, float, list[float]]]  # (label, kind, effective weight, vector)
    lo: float
    hi: float
    shown: list[Story] = field(default_factory=list)
    blocked_kw: list[str] = field(default_factory=list)
    blocked_ent: list[str] = field(default_factory=list)
    adjacent_tech_min: float = 0.6
    momentum_window_hours: int = 24


def apply_scores(
    s: Story, ms: list[dict[str, Any]], ctx: ScoreContext, learned: float, now: datetime
) -> None:
    """Pass 1 for one story: sub-scores, penalties, exclusion → s.scores and s.final_score (no I/O)."""
    if not ms or s.centroid is None:
        s.final_score, s.scores = -1.0, {"excluded": "no members"}
        return
    lo, hi, w = ctx.lo, ctx.hi, ctx.weights
    sims = [(cosine(list(s.centroid), v) * min(wt, 1.5) / 1.0, lbl) for lbl, _k, wt, v in ctx.pvs]
    best_vec = max((x for x, _ in sims), default=0.0)
    rel_vec = scale(best_vec, lo, hi)
    prefilter_best = max(float(m["prefilter_score"] or 0) for m in ms)
    captured = any(m["is_capture"] for m in ms)
    relevance = clamp(0.6 * rel_vec + 0.4 * min(1.0, prefilter_best * 2) + (0.15 if captured else 0))
    others = [o for o in ctx.shown if o.id != s.id and o.centroid is not None]
    nearest_shown = max((cosine(list(s.centroid), list(o.centroid)) for o in others), default=0.0)
    novelty = clamp(1 - scale(nearest_shown, lo, hi))
    penalties: list[str] = []
    if s.last_shown_at and not (s.material_update_at and s.material_update_at > s.last_shown_at):
        penalties.append("already shown")
        novelty = 0.0
    if (
        s.followed
        and s.material_update_at
        and (not s.last_shown_at or s.material_update_at > s.last_shown_at)
    ):
        novelty = 1.0
    prev_judge = (s.scores or {}).get("judge") or {}
    sc = {
        "relevance": round(relevance, 3),
        "impact": float(prev_judge.get("impact", 0.5)),
        "signal": round(signal_strength(ms), 3),
        "novelty": round(novelty, 3),
        "credibility": round(credibility(ms), 3),
        "durability": DURABILITY.get(prev_judge.get("durability") or s.durability or "trend", 0.6),
        "actionability": float(
            max(
                prev_judge.get("content_potential", 0.4),
                prev_judge.get("build_potential", 0.3),
                prev_judge.get("learn_potential", 0.3),
            )
        ),
        "learned": round(learned, 3),
        "momentum": round(momentum(ms, now, ctx.momentum_window_hours), 3),
    }
    if prev_judge:
        sc["relevance"] = round(
            clamp(0.5 * relevance + 0.5 * float(prev_judge.get("relevance", relevance))), 3
        )
    tech = max((float(m["tech_relevance"] or 0) for m in ms), default=0.0)
    hay = (s.title + " " + " ".join(m["title"] for m in ms)).lower()
    if any(k and k in hay for k in ctx.blocked_kw) or any(
        e and e in " ".join(s.entity_names or []).lower() for e in ctx.blocked_ent
    ):
        penalties.append("blocked entity/topic")
    final = sum(w[k] * sc.get(k, 0.0) for k in w)
    final -= sum(1.0 for p in penalties)
    excluded = None
    if s.ring == "adjacent" and tech < ctx.adjacent_tech_min:
        excluded = f"adjacent ring without tech relevance ≥ {ctx.adjacent_tech_min}"
    s.scores = {
        **sc,
        "weights": w,
        "penalties": penalties,
        "excluded": excluded,
        "tech_relevance": tech,
        "matched_profile": max(sims, default=(0, None))[1],
        "judge": prev_judge or None,
        "sources": sorted({m["name"] for m in ms}),
        "computed_at": now.isoformat(),
    }
    s.final_score = round(-1.0 if excluded else final, 4)


async def score_stories(
    session: AsyncSession, now: datetime, run_id: uuid.UUID | None = None, judge: bool = True
) -> list[Story]:
    cfg = get_config().scoring
    stories = await candidate_stories(session, now)
    if not stories:
        return []
    ids = [s.id for s in stories]
    members = await _members(session, ids)
    pvs, prof = await profile_vectors(session)
    lo, hi = cfg.relevance_scale(get_embedder().name)
    cscale = cfg.relevance_centroid_scale.get(get_embedder().name)
    if cscale is not None:  # centroids rank relevance better than topic-text vectors (ADR-026)
        cents, _ = await profile_vectors(session, centroids=True)
        if cents:
            pvs, (lo, hi) = cents, cscale
    ctx = ScoreContext(
        weights=cfg.weights_for(get_embedder().name).model_dump(),
        pvs=pvs,
        lo=lo,
        hi=hi,
        shown=[
            s
            for s in stories
            if s.last_shown_at and s.last_shown_at >= now - timedelta(days=cfg.novelty_window_days)
        ],
        blocked_kw=[k.lower() for k in (prof.blocked_keywords if prof else [])],
        blocked_ent=[e.lower() for e in (prof.blocked_entities if prof else [])],
        adjacent_tech_min=cfg.adjacent_tech_relevance_min,
        momentum_window_hours=cfg.momentum_window_hours,
    )
    learned = await learned_scores(session, ids)

    # Pass 1: deterministic sub-scores
    for s in stories:
        apply_scores(s, members.get(s.id, []), ctx, learned.get(s.id, 0.5), now)
    await session.flush()

    # Pass 2: LLM judge (relevance/impact/durability/potentials) for the top-N, then rescore those.
    if judge:
        ranked = sorted((s for s in stories if s.final_score > -0.5), key=lambda s: -s.final_score)
        to_judge = [s for s in ranked[: cfg.llm_relevance_top_n] if not (s.scores or {}).get("judge")]
        if to_judge and prof is not None:
            await _judge(session, to_judge, prof, members, run_id)
            return await score_stories(session, now, run_id, judge=False)
    from signal_core.ops.metrics import STORIES

    STORIES.set(sum(1 for s in stories if s.final_score > -0.5))
    return sorted(stories, key=lambda s: -s.final_score)


async def _judge(
    session: AsyncSession,
    stories: list[Story],
    prof: Profile,
    members: dict[uuid.UUID, list[dict[str, Any]]],
    run_id: uuid.UUID | None,
) -> None:
    topics = [t["name"] for ring in (prof.topics or {}).values() for t in ring]
    pinfo = {"role": prof.role, "goals": prof.goals, "stack": prof.stack, "topics": topics}
    for s in stories:
        summaries = [m["summary_1line"] or m["title"] for m in members.get(s.id, [])][:5]
        try:
            r = await llm.call(
                "relevance_judge",
                {"profile": pinfo, "story": {"title": s.title, "summaries": summaries}},
                session=session,
                run_id=run_id,
            )
        except (LLMError, BudgetExceeded) as e:
            log.warning("judge_skipped", story=str(s.id), error=str(e))
            return  # keep deterministic scores (degraded but functional)
        s.scores = {**(s.scores or {}), "judge": r.output.model_dump()}
        s.durability = r.output.durability
    await session.flush()


def mmr(stories: list[Story], k: int, lam: float) -> list[Story]:
    """Maximal Marginal Relevance on centroids so the brief is not 6 stories about one launch."""
    pool = [s for s in stories if s.centroid is not None and s.final_score > -0.5]
    if not pool:
        return []
    top = max(s.final_score for s in pool) or 1.0
    chosen: list[Story] = []
    while pool and len(chosen) < k:

        def gain(s: Story) -> float:
            div = max((cosine(list(s.centroid), list(c.centroid)) for c in chosen), default=0.0)
            return lam * (s.final_score / top) - (1 - lam) * div

        best = max(pool, key=gain)
        chosen.append(best)
        pool.remove(best)
    return chosen
