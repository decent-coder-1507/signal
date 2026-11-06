"""Routine steps for RADAR (§10.1): score, insights, cluster_merge, retrain_preferences, source_health."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from signal_core.db.models import Source
from signal_core.radar.cluster import merge_pass
from signal_core.radar.pipeline import process
from signal_core.radar.preference import retrain
from signal_core.routines.engine import StepContext, step


@step("score")
async def step_score(ctx: StepContext) -> dict[str, Any]:
    """Enrich pending items, cluster, score. (Insights run in their own step so cost shows separately.)"""
    return await process(ctx.session, ctx.now, ctx.run.id, insights=False)


@step("insights")
async def step_insights(ctx: StepContext) -> dict[str, Any]:
    out = await process(ctx.session, ctx.now, ctx.run.id, insights=True)
    return {k: out[k] for k in ("insights", "titled", "uncited_dropped", "insight_cap") if k in out}


@step("cluster_merge")
async def step_merge(ctx: StepContext) -> dict[str, Any]:
    return {"merged": await merge_pass(ctx.session, ctx.now, ctx.run.id)}


@step("retrain_preferences")
async def step_retrain(ctx: StepContext) -> dict[str, Any]:
    pm = await retrain(ctx.session)
    return {
        "version": pm.version if pm else None,
        "examples": (pm.metrics or {}).get("examples") if pm else 0,
    }


@step("source_health")
async def step_source_health(ctx: StepContext) -> dict[str, Any]:
    flagged = [
        s.name
        for s in (await ctx.session.execute(select(Source))).scalars()
        if (s.health or {}).get("flagged")
    ]
    return {"flagged": flagged}
