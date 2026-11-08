"""Ops routine steps (nightly maintenance §10.1): backup, evals_sample, cache cleanup, scheduler heartbeat check."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete

from signal_core.db.models import LLMCache
from signal_core.routines.engine import StepContext, step


@step("backup")
async def step_backup(ctx: StepContext) -> dict[str, Any]:
    from signal_core.ops.backup import backup

    r = await asyncio.to_thread(backup, ctx.now)
    return {"dump": r.dump.name, "size_bytes": r.size_bytes, "pruned": len(r.pruned)}


@step("evals_sample")
async def step_evals(ctx: StepContext) -> dict[str, Any]:
    from signal_core.ops.evals import run

    er = await run(ctx.session, sample=12)
    return {"passed": er.passed, "regressions": er.report.get("regressions", [])}


@step("cache_cleanup")
async def step_cache(ctx: StepContext) -> dict[str, Any]:
    res = await ctx.session.execute(delete(LLMCache).where(LLMCache.expires_at < datetime.now(UTC)))
    return {"deleted": getattr(res, "rowcount", 0) or 0}


@step("scheduler_health")
async def step_sched(ctx: StepContext) -> dict[str, Any]:
    """Alert (in-app + Telegram) if the scheduler heartbeat is stale or a daily brief window was missed (§16.4)."""
    from sqlalchemy import func, select

    from signal_core.db.models import Brief
    from signal_core.notify.dispatcher import dispatch
    from signal_core.services.settings_store import get_setting

    hb = await get_setting(ctx.session, "scheduler_heartbeat", None)
    stale = hb is None or datetime.fromisoformat(hb) < ctx.now - timedelta(minutes=10)
    last_brief = (
        await ctx.session.execute(
            select(func.max(Brief.created_at)).where(Brief.kind.in_(["daily", "weekend", "catchup"]))
        )
    ).scalar()
    missed = last_brief is None or last_brief < ctx.now - timedelta(hours=30)
    if stale or missed:
        msg = (
            "SIGNAL scheduler heartbeat is stale."
            if stale
            else "No brief was generated in the last 30 hours."
        )
        await dispatch(ctx.session, "telegram", "alert", {"text": msg}, ctx.now, urgent=True)
        await dispatch(ctx.session, "app", "alert", {"text": msg}, ctx.now)
    return {"heartbeat_stale": stale, "brief_missed": missed}
