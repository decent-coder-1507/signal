"""GYM (§9): skill map, market signal, learn-next (P10), explainers (P11) → cards, FSRS reviews, quizzes, progress.

learn-next priority = importance_to_goals × market_signal_trend × durability_weight × gap(target − current) (§9.2).
Resources may only be links already in the DB (stored items) or the skill's curated resources (URL whitelist §9.8).
"""

from __future__ import annotations

import random
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.base import OWNER_ID
from signal_core.db.models import (
    Card,
    CardReview,
    Explainer,
    Item,
    MoatRadar,
    Profile,
    Quiz,
    QuizAttempt,
    Skill,
    SkillEvent,
    Story,
    StoryInsight,
)
from signal_core.gym.fsrs import CardState, review
from signal_core.llm import router as llm
from signal_core.truth import strip_unknown_citations

DURABILITY_W = {"fundamental": 1.0, "evolving": 0.8, "tool-specific": 0.6}
CHURN_FACT_DAYS = 90
TARGET_RATIO = {"fundamental": 50, "evolving": 30, "tool-specific": 20}


def _kw(name: str) -> list[str]:
    stop = {"and", "the", "of", "for", "llm", "apps", "&"}
    return [w for w in re.findall(r"[a-z0-9]{3,}", name.lower()) if w not in stop]


async def skill_tree(session: AsyncSession) -> list[dict[str, Any]]:
    skills = list((await session.execute(select(Skill))).scalars())
    by_parent: dict[uuid.UUID | None, list[Skill]] = {}
    for s in skills:
        by_parent.setdefault(s.parent_id, []).append(s)

    def node(s: Skill) -> dict[str, Any]:
        return {
            "id": str(s.id),
            "name": s.name,
            "durability": s.durability,
            "current_level": s.current_level,
            "target_level": s.target_level,
            "market_signal": round(s.market_signal, 3),
            "market_trend": round(s.market_trend, 2),
            "importance": s.importance,
            "children": [node(c) for c in sorted(by_parent.get(s.id, []), key=lambda x: x.name)],
        }

    return [node(s) for s in sorted(by_parent.get(None, []), key=lambda x: x.name)]


async def update_market_signals(session: AsyncSession, now: datetime) -> int:
    """Market signal = share of recent important stories mentioning the skill; trend = last 14 d vs the 14 d before."""
    stories = list(
        (
            await session.execute(
                select(Story.title, Story.topics, Story.last_updated, Story.final_score).where(
                    Story.last_updated >= now - timedelta(days=28), Story.final_score > 0
                )
            )
        ).all()
    )
    learn_actions = [
        a.get("skill", "") or a.get("label", "")
        for (acts,) in (
            await session.execute(
                select(StoryInsight.actions).where(StoryInsight.created_at >= now - timedelta(days=28))
            )
        ).all()
        for a in acts or []
        if a.get("type") == "learn"
    ]
    recent = [s for s in stories if s.last_updated >= now - timedelta(days=14)]
    older = [s for s in stories if s.last_updated < now - timedelta(days=14)]
    n = 0
    goals = " ".join(
        (await session.execute(select(Profile.goals).where(Profile.user_id == OWNER_ID))).scalar() or []
    )
    for sk in (await session.execute(select(Skill))).scalars():
        kws = _kw(sk.name)

        def hits(rows: list[Any], kws: list[str] = kws) -> int:
            return sum(
                1 for r in rows if any(k in (r.title + " " + " ".join(r.topics or [])).lower() for k in kws)
            )

        r_hits, o_hits = hits(recent), hits(older)
        learn_hits = sum(1 for a in learn_actions if any(k in a.lower() for k in kws))
        sk.market_signal = (r_hits + 2 * learn_hits) / max(len(recent), 1)
        sk.market_trend = (r_hits + 1) / (o_hits + 1)
        sk.importance = min(1.0, 0.4 + 0.3 * sum(1 for k in kws if k in goals.lower()))
        n += 1
    await session.flush()
    return n


def priority(sk: Skill) -> float:
    gap = max(sk.target_level - sk.current_level, 0)
    trend = min(max(sk.market_trend, 0.5), 3.0)
    signal = 0.3 + min(sk.market_signal, 1.0)
    return round(sk.importance * trend * signal * DURABILITY_W.get(sk.durability, 0.8) * gap, 4)


async def learn_next(session: AsyncSession, now: datetime, run_id: uuid.UUID | None = None) -> dict[str, Any]:
    await update_market_signals(session, now)
    leaves = [s for s in (await session.execute(select(Skill).where(Skill.parent_id.is_not(None)))).scalars()]
    ranked = sorted(leaves, key=priority, reverse=True)[:8]
    stories = list(
        (
            await session.execute(
                select(Story)
                .where(
                    Story.final_score > 0,
                    Story.status == "active",
                    Story.last_updated >= now - timedelta(days=21),
                )
                .order_by(desc(Story.final_score))
                .limit(25)
            )
        ).scalars()
    )
    resources = await _resources(session, ranked)
    radar = (
        (await session.execute(select(MoatRadar).order_by(desc(MoatRadar.created_at)).limit(1)))
        .scalars()
        .first()
    )
    moat_learn = [
        p["claim"] for p in ((radar.content or {}).get("for_you", {}).get("learn", []) if radar else [])
    ]
    cfg = get_config().profile.owner
    r = await llm.call(
        "learn_next",
        {
            "owner": cfg.name,
            "role": cfg.role,
            "goals": cfg.goals,
            "candidates": [
                {
                    "name": s.name,
                    "durability": s.durability,
                    "current": s.current_level,
                    "target": s.target_level,
                    "signal": round(s.market_signal, 2),
                    "priority": priority(s),
                }
                for s in ranked
            ],
            "stories": [{"id": str(s.id), "title": s.title, "durability": s.durability} for s in stories],
            "resources": [{"id": x["id"], "title": x["title"]} for x in resources],
            "moat": moat_learn,
        },
        session=session,
        run_id=run_id,
    )
    names = {s.name: s for s in ranked}
    sids = {str(s.id): s for s in stories}
    res_by = {x["id"]: x for x in resources}
    items = []
    for it in r.output.items:
        if it.skill not in names:  # only candidates; never an invented skill
            continue
        evidence = [e for e in it.evidence if e in sids]
        items.append(
            {
                "skill": it.skill,
                "skill_id": str(names[it.skill].id),
                "priority": priority(names[it.skill]),
                "why": strip_unknown_citations(it.why, set(sids)),
                "evidence": [{"id": e, "title": sids[e].title} for e in evidence],
                "ignore_instead": it.ignore_instead,
                "plan": {
                    **it.plan.model_dump(),
                    "resources": [res_by[x] for x in it.plan.resources if x in res_by],
                },
            }
        )
    return {
        "items": items[:3],
        "ignore": r.output.ignore,
        "prompt_version": r.prompt_version,
        "model": r.model,
    }


async def _resources(session: AsyncSession, skills: list[Skill]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in skills:
        for res in s.resources or []:
            if res.get("url", "").startswith("http"):
                out.append({"id": f"res:{len(out)}", "title": res.get("title", s.name), "url": res["url"]})
    q = (
        select(Item)
        .where(Item.content_type.in_(["paper", "repo", "article"]), Item.status == "enriched")
        .limit(200)
    )
    for it in (await session.execute(q)).scalars():
        if any(k in it.title.lower() for s in skills for k in _kw(s.name)):
            out.append({"id": str(it.id), "title": it.title, "url": it.canonical_url})
    return out[:30]


async def explainer(
    session: AsyncSession, topic: str, depth: str, story_id: uuid.UUID | None = None, force: bool = False
) -> tuple[Explainer, list[Card]]:
    if depth not in ("plain", "engineer", "deep"):
        raise ValueError("depth must be plain | engineer | deep")
    topic = topic.strip()[:255]
    cached = (
        await session.execute(select(Explainer).where(Explainer.topic == topic, Explainer.depth == depth))
    ).scalar_one_or_none()
    if cached and not force:
        cards = list(
            (
                await session.execute(
                    select(Card).where(Card.source_type == "explainer", Card.source_id == cached.id)
                )
            ).scalars()
        )
        return cached, cards
    sources: list[dict[str, Any]] = []
    if story_id:
        from signal_core.radar.insight import story_items

        sources = [
            {"id": str(it.id), "title": it.title, "text": " ".join((it.text or "").split()[:200])}
            for _si, it, _src, _e in (await story_items(session, story_id))[:3]
        ]
    known = [s.name for s in (await session.execute(select(Skill).where(Skill.current_level >= 3))).scalars()]
    role = get_config().profile.owner.role
    r = await llm.call(
        "explainer",
        {"topic": topic, "depth": depth, "role": role, "known": known, "sources": sources},
        session=session,
        user_initiated=True,
    )
    allowed = {s["id"] for s in sources}
    skill = await match_skill(session, topic)
    body = strip_unknown_citations(r.output.body_md, allowed)
    if cached:
        cached.body, cached.citations = body, [c for c in r.output.citations if c in allowed]
        ex = cached
    else:
        ex = Explainer(
            topic=topic,
            depth=depth,
            body=body,
            citations=[c for c in r.output.citations if c in allowed],
            skill_ids=[str(skill.id)] if skill else [],
            prompt_version=r.prompt_version,
            model=r.model,
        )
        session.add(ex)
    await session.flush()
    now = datetime.now(UTC)
    durability = skill.durability if skill else "evolving"
    cards = []
    for c in r.output.cards:
        card = Card(
            skill_id=skill.id if skill else None,
            source_type="explainer",
            source_id=ex.id,
            type=c.type,
            front=c.front,
            back=c.back,
            durability="fundamental" if durability == "fundamental" else durability,
            expires_at=now + timedelta(days=CHURN_FACT_DAYS) if durability == "tool-specific" else None,
            fsrs_state=CardState().to_dict(),
            due_at=now,
        )
        session.add(card)
        cards.append(card)
    await session.flush()
    return ex, cards


async def match_skill(session: AsyncSession, topic: str) -> Skill | None:
    kws = set(_kw(topic))
    best, score = None, 0
    for s in (await session.execute(select(Skill))).scalars():
        sc = len(kws & set(_kw(s.name)))
        if sc > score:
            best, score = s, sc
    return best


async def due_cards(session: AsyncSession, now: datetime, limit: int = 50) -> list[Card]:
    return list(
        (
            await session.execute(
                select(Card)
                .where(Card.due_at <= now, (Card.expires_at.is_(None)) | (Card.expires_at > now))
                .order_by(Card.due_at)
                .limit(limit)
            )
        ).scalars()
    )


async def review_card(
    session: AsyncSession, card: Card, rating: int, now: datetime, elapsed_ms: int = 0
) -> Card:
    state, due = review(CardState.from_dict(card.fsrs_state), rating, now)
    card.fsrs_state, card.due_at = state.to_dict(), due
    session.add(CardReview(card_id=card.id, rating=rating, reviewed_at=now, elapsed_ms=elapsed_ms))
    if card.skill_id:
        session.add(
            SkillEvent(
                skill_id=card.skill_id,
                kind="card_retention",
                delta=0.0 if rating > 1 else -0.0,
                note=f"rating {rating}",
            )
        )
    await session.flush()
    return card


async def build_quiz(session: AsyncSession, n: int = 10, seed: int | None = None) -> Quiz:
    cards = list((await session.execute(select(Card))).scalars())
    rng = random.Random(seed)
    rng.shuffle(cards)
    picked = cards[:n]
    qs = []
    for c in picked:
        distractors = [x.back for x in cards if x.id != c.id and x.type == c.type][:3]
        options = [c.back, *distractors]
        rng.shuffle(options)
        qs.append(
            {
                "card_id": str(c.id),
                "skill_id": str(c.skill_id) if c.skill_id else None,
                "question": c.front,
                "options": options if len(options) > 1 else [],
                "answer": c.back,
            }
        )
    q = Quiz(title=f"Weekly quiz {datetime.now(UTC).date().isoformat()}", questions=qs)
    session.add(q)
    await session.flush()
    return q


async def grade_quiz(session: AsyncSession, quiz: Quiz, answers: list[str]) -> QuizAttempt:
    correct = 0
    per_skill: dict[str, list[int]] = {}
    for q, a in zip(quiz.questions, answers, strict=False):
        ok = a.strip().lower() == q["answer"].strip().lower()
        correct += ok
        if q.get("skill_id"):
            per_skill.setdefault(q["skill_id"], []).append(int(ok))
    score = correct / max(len(quiz.questions), 1)
    att = QuizAttempt(quiz_id=quiz.id, answers=answers, score=round(score, 3))
    session.add(att)
    for sid, res in per_skill.items():  # quiz results move self-ratings a little (§9.4)
        sk = await session.get(Skill, uuid.UUID(sid))
        if sk is None:
            continue
        delta = 0.25 if sum(res) / len(res) >= 0.8 else (-0.25 if sum(res) / len(res) < 0.4 else 0.0)
        if delta:
            sk.current_level = round(min(5.0, max(0.0, sk.current_level + delta)), 2)
            session.add(SkillEvent(skill_id=sk.id, kind="quiz", delta=delta, note=f"quiz {quiz.id}"))
    await session.flush()
    return att


async def progress(session: AsyncSession, now: datetime) -> dict[str, Any]:
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    tree = await skill_tree(session)
    radar = [
        {
            "domain": d["name"],
            "current": round(sum(c["current_level"] for c in d["children"]) / max(len(d["children"]), 1), 2),
            "target": round(sum(c["target_level"] for c in d["children"]) / max(len(d["children"]), 1), 2),
        }
        for d in tree
    ]
    reviews = list(
        (
            await session.execute(
                select(CardReview.rating, CardReview.reviewed_at).where(
                    CardReview.reviewed_at >= now - timedelta(days=30)
                )
            )
        ).all()
    )
    retention = sum(1 for r, _ in reviews if r >= 3) / len(reviews) if reviews else None
    days = sorted({r.reviewed_at.date() for r in reviews}, reverse=True)
    streak, d = 0, now.date()
    while d in days:
        streak += 1
        d -= timedelta(days=1)
    mix = dict(
        (
            await session.execute(
                select(Card.durability, func.count())
                .join(CardReview, CardReview.card_id == Card.id)
                .where(CardReview.reviewed_at >= month)
                .group_by(Card.durability)
            )
        ).all()
    )
    total = sum(mix.values()) or 1
    ratio = {k: round(100 * mix.get(k, 0) / total) for k in TARGET_RATIO}
    concepts = (
        await session.execute(
            select(func.count()).select_from(Explainer).where(Explainer.created_at >= month)
        )
    ).scalar_one()
    return {
        "radar": radar,
        "cards_reviewed_30d": len(reviews),
        "retention": retention,
        "learning_streak": streak,
        "concepts_this_month": int(concepts),
        "time_split": ratio,
        "target_split": TARGET_RATIO,
        "due_now": len(await due_cards(session, now)),
    }
