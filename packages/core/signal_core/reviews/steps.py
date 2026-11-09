"""Weekly & monthly reviews (§10.1): guided, finishable flows stored as a Brief (kind weekly | monthly) whose
`content.sections` are filled step by step and whose `content.flow` lists the UI steps to complete.

Weekly: week recap (top 10) → content plan for next week (per platform goals) → idea of the week + try-it → learn-next
→ quiz → metrics summary → habit stats. Monthly: state of tech (P14), Moat Radar, content learnings (P16, M9), idea
pipeline review, skill progress, profile/source tuning proposals, cost report — exportable as PDF.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.models import Brief, Draft, HabitDay, LLMCall, Publication, Source, Story, StoryInsight
from signal_core.llm import budget
from signal_core.llm import router as llm
from signal_core.llm.provider import BudgetExceeded, LLMError
from signal_core.routines.engine import StepContext, step
from signal_core.settings import get_settings

WEEKLY_FLOW = ["recap", "content_plan", "idea", "learn", "quiz", "metrics"]
MONTHLY_FLOW = ["state_of_tech", "moat", "content", "ideas", "skills", "tuning", "costs"]


async def _review_brief(ctx: StepContext, kind: str) -> Brief:
    """One review document per run; created by the first review step, reused by the rest."""
    bid = ctx.outputs.get("_review_brief_id")
    if bid:
        b = await ctx.session.get(Brief, uuid.UUID(bid))
        if b is not None:
            return b
    days = 7 if kind == "weekly" else 30
    b = Brief(
        routine_run_id=ctx.run.id,
        kind=kind,
        period_start=ctx.now - timedelta(days=days),
        period_end=ctx.now,
        content={
            "kind": kind,
            "sections": [],
            "flow": WEEKLY_FLOW if kind == "weekly" else MONTHLY_FLOW,
            "done_steps": [],
        },
    )
    ctx.session.add(b)
    await ctx.session.flush()
    ctx.outputs["_review_brief_id"] = str(b.id)
    return b


async def _add(ctx: StepContext, kind: str, section: dict[str, Any]) -> dict[str, Any]:
    b = await _review_brief(ctx, kind)
    b.content = {**b.content, "sections": [*b.content.get("sections", []), section]}
    await ctx.session.flush()
    return {"brief_id": str(b.id), "section": section["key"]}


async def top_stories(session: AsyncSession, since: datetime, n: int) -> list[Story]:
    return list(
        (
            await session.execute(
                select(Story)
                .where(Story.status == "active", Story.final_score > 0, Story.last_updated >= since)
                .order_by(desc(Story.final_score))
                .limit(n)
            )
        ).scalars()
    )


# ---------------- weekly ----------------
@step("weekly_recap")
async def weekly_recap(ctx: StepContext) -> dict[str, Any]:
    stories = await top_stories(ctx.session, ctx.now - timedelta(days=7), 10)
    items = [
        {
            "title": s.title,
            "href": f"/stories/{s.id}",
            "story_id": str(s.id),
            "sub": f"{s.durability or ''} · {s.hype_verdict or ''}".strip(" ·"),
        }
        for s in stories
    ]
    text = await _summary(ctx, "weekly", stories)
    return await _add(ctx, "weekly", {"key": "recap", "title": "Week recap", "text": text, "items": items})


@step("content_plan")
async def content_plan(ctx: StepContext) -> dict[str, Any]:
    goals = get_config().voice.goals_per_week
    start = ctx.now
    scheduled = dict(
        (
            await ctx.session.execute(
                select(Draft.platform, func.count())
                .where(
                    Draft.status == "scheduled",
                    Draft.scheduled_for >= start,
                    Draft.scheduled_for < start + timedelta(days=7),
                )
                .group_by(Draft.platform)
            )
        ).all()
    )
    stories = await top_stories(ctx.session, ctx.now - timedelta(days=7), 12)
    plan = []
    k = 0
    for platform, goal in goals.items():
        need = max(goal - int(scheduled.get(platform, 0)), 0)
        for _ in range(need):
            if k >= len(stories):
                break
            s = stories[k]
            k += 1
            plan.append(
                {
                    "platform": platform,
                    "story_id": str(s.id),
                    "title": s.title,
                    "href": f"/stories/{s.id}",
                    "sub": f"{platform}: draft from this story",
                }
            )
    evergreen = list(
        (
            await ctx.session.execute(select(Draft).where(Draft.evergreen.is_(True), Draft.status == "ready"))
        ).scalars()
    )
    return await _add(
        ctx,
        "weekly",
        {
            "key": "content_plan",
            "title": "Content plan for next week",
            "text": f"Goals: {', '.join(f'{p} {g}' for p, g in goals.items())}. Already scheduled: "
            f"{sum(scheduled.values())}. Evergreen pieces ready: {len(evergreen)}.",
            "items": plan,
            "proposals": plan,
        },
    )


@step("metrics_summary")
async def metrics_summary(ctx: StepContext) -> dict[str, Any]:
    pubs = (
        await ctx.session.execute(
            select(func.count())
            .select_from(Publication)
            .where(Publication.published_at >= ctx.now - timedelta(days=7))
        )
    ).scalar_one()
    days = list(
        (
            await ctx.session.execute(
                select(HabitDay).where(HabitDay.date >= (ctx.now - timedelta(days=7)).date())
            )
        ).scalars()
    )
    done = sum(1 for d in days if d.mode in ("full", "minimum"))
    summary: dict[str, Any] = {"posts": int(pubs), "habit_days": done}
    try:
        from signal_core.analytics.service import summary as analytics_summary

        summary["analytics"] = await analytics_summary(ctx.session, ctx.now, days=7)
    except ModuleNotFoundError:
        pass
    return await _add(
        ctx,
        "weekly",
        {
            "key": "metrics",
            "title": "Metrics & habit",
            "text": f"You published {pubs} post(s) and showed up on {done} of the last 7 days.",
            "data": summary,
        },
    )


# idea_of_week / learn_next / quiz steps already exist; turn their outputs into readable review sections.
# Every weekly flow step gets a section, even when its step produced nothing (it then says so).
def _weekly_idea_section(out: dict[str, Any] | None) -> dict[str, Any]:
    items = []
    for key, label in (("idea_of_week", "Idea of the week"), ("try_it_of_week", "Try it this week")):
        idea = (out or {}).get(key)
        if idea:
            items.append({"title": idea["title"], "sub": label, "href": f"/lab/{idea['id']}"})
    text = "" if items else "No new sparks or try-its this week. Capture one in Lab when something itches."
    return {"key": "idea_of_week", "title": "Idea & try-it of the week", "text": text, "items": items}


def _weekly_learn_section(out: dict[str, Any] | None) -> dict[str, Any]:
    skills = [str(x) for x in (out or {}).get("items", [])]
    items = [
        {"title": sk, "sub": "Open an explainer", "href": f"/gym?tab=explain&topic={quote(sk)}"}
        for sk in skills
    ]
    text = "" if items else "Nothing new to learn surfaced this week. Your skill map is in Gym."
    return {"key": "learn_next", "title": "Learn next", "text": text, "items": items}


def _weekly_quiz_section(out: dict[str, Any] | None) -> dict[str, Any]:
    n = int((out or {}).get("questions", 0))
    if n:
        return {
            "key": "quiz",
            "title": "Weekly quiz",
            "text": f"{n} question(s) from this week's cards and stories.",
            "items": [{"title": "Take the quiz", "href": "/gym?tab=quiz"}],
        }
    return {
        "key": "quiz",
        "title": "Weekly quiz",
        "text": "Not enough reviewed material for a quiz this week.",
    }


@step("weekly_sections")
async def weekly_sections(ctx: StepContext) -> dict[str, Any]:
    o = ctx.outputs
    for section in (
        _weekly_idea_section(o.get("idea_of_week")),
        _weekly_learn_section(o.get("learn_next")),
        _weekly_quiz_section(o.get("quiz")),
    ):
        await _add(ctx, "weekly", section)
    return {"ok": True}


# ---------------- monthly ----------------
@step("state_of_tech")
async def state_of_tech(ctx: StepContext) -> dict[str, Any]:
    stories = await top_stories(ctx.session, ctx.now - timedelta(days=30), 15)
    text = await _summary(ctx, "monthly", stories)
    return await _add(
        ctx,
        "monthly",
        {
            "key": "state_of_tech",
            "title": "State of tech for you",
            "text": text,
            "items": [{"title": s.title, "href": f"/stories/{s.id}"} for s in stories],
        },
    )


@step("tuning_proposals")
async def tuning_proposals(ctx: StepContext) -> dict[str, Any]:
    """Monthly profile check (§6.9): low-usefulness / flagged sources to prune; topic weights that drifted."""
    srcs = list((await ctx.session.execute(select(Source).where(Source.enabled.is_(True)))).scalars())
    prune = [
        {
            "title": s.name,
            "sub": (s.health or {}).get("flagged") or f"usefulness {s.usefulness:.2f}",
            "source_id": str(s.id),
        }
        for s in srcs
        if (s.health or {}).get("flagged")
        or (s.usefulness < 0.02 and s.last_fetched_at and s.type != "capture")
    ][:10]
    from signal_core.db.base import OWNER_ID
    from signal_core.db.models import Profile

    p = (await ctx.session.execute(select(Profile).where(Profile.user_id == OWNER_ID))).scalar_one_or_none()
    drift = [
        {"title": t["name"], "sub": f"weight {t.get('weight')} adj {t['adj']['delta']:+.0%}"}
        for ring in (p.topics if p else {}).values()
        for t in ring
        if (t.get("adj") or {}).get("delta")
    ]
    return await _add(
        ctx,
        "monthly",
        {
            "key": "tuning",
            "title": "Profile & source tuning proposals",
            "items": prune + drift,
            "prune": prune,
            "drift": drift,
        },
    )


@step("cost_report")
async def cost_report(ctx: StepContext) -> dict[str, Any]:
    since = ctx.now - timedelta(days=30)
    rows = (
        await ctx.session.execute(
            select(LLMCall.task, func.sum(LLMCall.cost_usd), func.count())
            .where(LLMCall.created_at >= since)
            .group_by(LLMCall.task)
        )
    ).all()
    total = sum(float(c or 0) for _t, c, _n in rows)
    cfg = get_config()
    limit = (await budget.status(ctx.session, cfg.budget, get_settings().timezone, ctx.now)).limit_usd
    return await _add(
        ctx,
        "monthly",
        {
            "key": "costs",
            "title": "Cost report",
            "text": f"API-equivalent LLM cost over 30 days: ${total:.2f} (budget ${limit:.0f}).",
            "items": [
                {"title": t, "sub": f"${float(c or 0):.3f} · {n} calls"}
                for t, c, n in sorted(rows, key=lambda r: -float(r[1] or 0))[:10]
            ],
        },
    )


@step("monthly_sections")
async def monthly_sections(ctx: StepContext) -> dict[str, Any]:
    for key, title in (
        ("moat_radar", "Moat Radar"),
        ("content_learnings", "Content performance & learnings"),
        ("idea_pipeline_review", "Idea pipeline review"),
        ("skill_progress", "Skill progress"),
    ):
        if key in ctx.outputs:
            await _add(ctx, "monthly", {"key": key, "title": title, "data": ctx.outputs[key]})
    return {"ok": True}


@step("quarterly_reset")
async def quarterly_reset(ctx: StepContext) -> dict[str, Any]:
    return await _add(
        ctx,
        "monthly",
        {
            "key": "quarterly",
            "title": "Quarterly reset",
            "text": "Re-set goals, re-rate your skills and prune sources this week.",
        },
    )


async def _summary(ctx: StepContext, kind: str, stories: list[Story]) -> str:
    rows = []
    for s in stories[:10]:
        ins = (
            (
                await ctx.session.execute(
                    select(StoryInsight)
                    .where(StoryInsight.story_id == s.id)
                    .order_by(desc(StoryInsight.version))
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        rows.append(
            {
                "id": str(s.id),
                "title": s.title,
                "durability": s.durability or "",
                "summary": (ins.what_happened[:240] if ins else ""),
            }
        )
    try:
        r = await llm.call(
            "review_summary",
            {"kind": kind, "stories": rows},
            session=ctx.session,
            run_id=ctx.run.id,
            tier="deep" if kind == "monthly" else "balanced",
        )
        return str(r.output.summary)
    except (LLMError, BudgetExceeded):
        return "AI summary unavailable; top stories listed below." if rows else "A quiet period."
