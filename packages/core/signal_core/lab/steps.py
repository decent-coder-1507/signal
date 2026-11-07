"""LAB routine steps: lab_spark (daily) and idea_pipeline_review (monthly: flag stale ideas to kill explicitly)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select

from signal_core.db.models import Idea
from signal_core.lab.service import detect_sparks
from signal_core.routines.engine import StepContext, step


@step("lab_spark")
async def step_spark(ctx: StepContext) -> dict[str, Any]:
    ideas = await detect_sparks(ctx.session, ctx.now, ctx.run.id)
    return {"sparks": len(ideas), "best": max((i.lab_score for i in ideas), default=None)}


@step("idea_of_week")
async def step_idea_of_week(ctx: StepContext) -> dict[str, Any]:
    ideas = list(
        (
            await ctx.session.execute(
                select(Idea)
                .where(
                    Idea.created_at >= ctx.now - timedelta(days=7), Idea.status.in_(["spark", "shortlisted"])
                )
                .order_by(Idea.lab_score.desc())
            )
        ).scalars()
    )
    best = next((i for i in ideas if i.type != "practical"), None)
    tryit = next((i for i in ideas if i.type == "practical"), None)
    return {
        "idea_of_week": {"id": str(best.id), "title": best.title} if best else None,
        "try_it_of_week": {"id": str(tryit.id), "title": tryit.title} if tryit else None,
    }


@step("idea_pipeline_review")
async def step_pipeline_review(ctx: StepContext) -> dict[str, Any]:
    stale = list(
        (
            await ctx.session.execute(
                select(Idea).where(
                    Idea.status.in_(["spark", "shortlisted", "validating"]),
                    Idea.updated_at < ctx.now - timedelta(days=30),
                )
            )
        ).scalars()
    )
    return {"stale_to_review": [{"id": str(i.id), "title": i.title, "status": i.status} for i in stale]}
