"""Daily Brief assembly (§6.8) incl. catch-up mode (§6.8) and the quiet-day rule (N1).

Composition: top line · 5–7 top stories (MMR-diverse, ≥ min_score, UPDATE badge for developing stories) ·
one post suggestion · one build spark (LAB, if any above threshold) · one learn item · quick hits ·
watches triggered · cards due · quiet-day evergreen deep-dive when nothing clears the bar.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.models import Brief, Card, Story, StoryInsight, Watch, WatchHit
from signal_core.llm import router as llm
from signal_core.llm.provider import BudgetExceeded, LLMError
from signal_core.radar.insight import degraded_insight, latest_insight
from signal_core.radar.scoring import mmr
from signal_core.truth import first_sentence


async def last_opened_brief(session: AsyncSession) -> Brief | None:
    return (
        (
            await session.execute(
                select(Brief).where(Brief.opened_at.is_not(None)).order_by(desc(Brief.opened_at)).limit(1)
            )
        )
        .scalars()
        .first()
    )


async def decide_kind(session: AsyncSession, now: datetime, requested: str) -> tuple[str, datetime]:
    """Catch-up mode: no brief opened for ≥ catchup_after_days → one 'While you were away' brief over the gap."""
    cfg = get_config().profile.brief
    any_brief = (await session.execute(select(func.count()).select_from(Brief))).scalar_one()
    last = await last_opened_brief(session)
    if requested in ("daily", "weekend") and any_brief:
        last_seen = last.opened_at if last and last.opened_at else None
        if last_seen is None:
            first = (await session.execute(select(func.min(Brief.created_at)))).scalar_one()
            last_seen = first
        if last_seen and now - last_seen >= timedelta(days=cfg.catchup_after_days):
            return "catchup", last_seen
    return requested, now - timedelta(hours=36 if requested == "daily" else 60)


def _card(s: Story, ins: StoryInsight | None, update: bool, exploration: bool = False) -> dict[str, Any]:
    first = first_sentence(ins.what_happened) if ins else s.title
    post = next((a for a in (ins.actions if ins else []) if a.get("type") == "post"), None)
    return {
        "story_id": str(s.id),
        "title": s.title,
        "one_line": first,
        "ring": s.ring,
        "score": s.final_score,
        "why_you": ins.why_you if ins else None,
        "hype_verdict": ins.hype_verdict if ins else s.hype_verdict,
        "durability": ins.durability if ins else s.durability,
        "update": update,
        "what_changed": s.what_changed if update else None,
        "actions": ins.actions if ins else [],
        "post_action": post,
        "uncertainty": ins.uncertainty_labels if ins else [],
        "exploration": exploration,
        "citations": [
            {"id": c["id"], "url": c["url"], "source": c["source"], "title": c.get("title", "")}
            for c in (ins.citations if ins else [])
        ][:6],
        "degraded": bool(ins and ins.degraded),
    }


async def assemble(
    session: AsyncSession,
    now: datetime,
    kind: str = "daily",
    params: dict[str, Any] | None = None,
    run_id: uuid.UUID | None = None,
) -> Brief:
    cfg = get_config()
    params = params or {}
    kind, since = await decide_kind(session, now, kind)
    max_stories = int(params.get("max_stories", cfg.profile.brief.max_stories))
    if kind == "catchup":
        max_stories = cfg.profile.brief.catchup_max_stories
    min_score = float(params.get("min_score", cfg.profile.brief.min_score))

    pool = list(
        (
            await session.execute(
                select(Story)
                .where(
                    Story.status == "active",
                    Story.last_updated >= since,
                    Story.final_score > -0.5,
                    Story.ring != "wide",  # wide lens: separate feed, never mixed into the core brief (§6.1)
                )
                .order_by(desc(Story.final_score))
            )
        ).scalars()
    )

    def is_update(s: Story) -> bool:
        return bool(s.last_shown_at and s.material_update_at and s.material_update_at > s.last_shown_at)

    eligible = [s for s in pool if s.final_score >= min_score and (not s.last_shown_at or is_update(s))]
    top = mmr(eligible, max_stories, cfg.scoring.mmr_lambda)
    exploration: Story | None = None
    if cfg.scoring.exploration_slot and len(top) >= 5:
        # 10% "outside your usual" slot (filter-bubble guard, §20.1): best story on a topic not already covered.
        covered = {t for s in top for t in (s.topics or [])}
        exploration = next(
            (
                s
                for s in pool
                if s not in top
                and not s.last_shown_at
                and s.final_score >= min_score * 0.8
                and not (set(s.topics or []) & covered)
            ),
            None,
        )
        if exploration is not None:
            top = [*top[: max_stories - 1], exploration]

    degraded = False
    cards = []
    for s in top:
        ins = await latest_insight(session, s.id)
        if ins is None:
            ins = await degraded_insight(session, s)
            degraded = True
        cards.append(_card(s, ins, is_update(s), s is exploration))

    rest = [s for s in pool if s not in top and not s.last_shown_at][: cfg.profile.brief.quick_hits]
    quick = []
    for s in rest:
        ins = await latest_insight(session, s.id)
        quick.append(
            {
                "story_id": str(s.id),
                "title": s.title,
                "ring": s.ring,
                "one_line": (first_sentence(ins.what_happened) if ins else s.title),
            }
        )

    titles = [c["title"] for c in cards]
    topline = None
    try:
        r = await llm.call("brief_topline", {"titles": titles}, session=session, run_id=run_id)
        topline = r.output.topline
    except (LLMError, BudgetExceeded):
        degraded = True
        topline = (titles[0] + (f" (+{len(titles) - 1} more)" if len(titles) > 1 else "")) if titles else None

    post_suggestion = None
    for c in cards:
        if c["post_action"]:
            post_suggestion = {"story_id": c["story_id"], "title": c["title"], **c["post_action"]}
            break
    learn = None
    for c in cards:
        a = next((x for x in c["actions"] if x.get("type") == "learn"), None)
        if a:
            learn = {
                "story_id": c["story_id"],
                "skill": a.get("skill") or a.get("label"),
                "label": a.get("label"),
            }
            break
    spark = await _build_spark(session, since)

    hits = (
        await session.execute(
            select(WatchHit, Watch, Story)
            .join(Watch, Watch.id == WatchHit.watch_id)
            .join(Story, Story.id == WatchHit.story_id)
            .where(WatchHit.in_brief_id.is_(None))
        )
    ).all()
    watches = [
        {
            "watch": w.query,
            "story_id": str(s.id),
            "title": s.title,
            "explanation": h.explanation,
            "urgency": w.urgency,
        }
        for h, w, s in hits
    ]
    cards_due = (
        await session.execute(select(func.count()).select_from(Card).where(Card.due_at <= now))
    ).scalar_one()

    quiet = None
    if not cards:
        deep = (
            (
                await session.execute(
                    select(Story)
                    .where(Story.durability == "fundamental", Story.status == "active")
                    .order_by(desc(Story.final_score))
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        quiet = {
            "message": "Quiet day. Nothing important for you. Here is one evergreen deep-dive instead.",
            "deep_dive": {"story_id": str(deep.id), "title": deep.title} if deep else None,
        }

    content = {
        "kind": kind,
        "topline": topline,
        "stories": cards,
        "post_suggestion": post_suggestion,
        "build_spark": spark,
        "learn": learn,
        "quick_hits": quick,
        "watches": watches,
        "cards_due": int(cards_due),
        "quiet": quiet,
        "degraded": degraded,
        "since": since.isoformat(),
        "generated_at": now.isoformat(),
    }
    brief = Brief(
        routine_run_id=run_id,
        kind=kind,
        period_start=since,
        period_end=now,
        content=content,
        rendered_md=render_md(content),
        degraded=degraded,
    )
    session.add(brief)
    await session.flush()
    for s in top:
        s.last_shown_at = now
    for h, _w, _s in hits:
        h.in_brief_id = brief.id
    await session.flush()
    return brief


async def _build_spark(session: AsyncSession, since: datetime) -> dict[str, Any] | None:
    """≤ 1 LAB spark, only above lab_spark_threshold (§8.6). Ideas exist from M6."""
    from signal_core.db.models import Idea

    thr = get_config().scoring.lab_spark_threshold
    idea = (
        (
            await session.execute(
                select(Idea)
                .where(Idea.status == "spark", Idea.lab_score >= thr, Idea.created_at >= since)
                .order_by(desc(Idea.lab_score))
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if idea is None:
        return None
    return {
        "idea_id": str(idea.id),
        "title": idea.title,
        "one_liner": idea.one_liner,
        "type": idea.type,
        "lab_score": idea.lab_score,
    }


def render_md(c: dict[str, Any]) -> str:
    title = {"catchup": "While you were away", "daily": "Daily Brief", "weekend": "Weekend Brief"}.get(
        c["kind"], c["kind"].title()
    )
    lines = [f"# {title}", ""]
    if c.get("topline"):
        lines += [f"**{c['topline']}**", ""]
    if c.get("quiet"):
        lines += [c["quiet"]["message"], ""]
    for i, s in enumerate(c["stories"], 1):
        badges = " · ".join(
            b
            for b in [
                s["ring"].title(),
                "UPDATE" if s["update"] else "",
                (s.get("hype_verdict") or "").replace("_", " "),
                s.get("durability") or "",
            ]
            if b
        )
        lines += [f"## {i}. {s['title']}", f"_{badges}_", "", s["one_line"], ""]
        if s.get("why_you"):
            lines += [f"**Why it matters to you:** {s['why_you']}", ""]
    if c.get("quick_hits"):
        lines += ["## Quick hits", *[f"- {q['title']}" for q in c["quick_hits"]], ""]
    if c.get("watches"):
        lines += ["## Watches triggered", *[f"- {w['watch']}: {w['title']}" for w in c["watches"]], ""]
    lines.append(f"Cards due: {c['cards_due']}")
    return "\n".join(lines)
