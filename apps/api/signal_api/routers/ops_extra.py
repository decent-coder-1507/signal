"""Ops (§13, §14 Ops screen, §15.3 costs page): costs by day/task/tier/routine with projection, LLM ledger,
evals report, dead-letter jobs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, select

from signal_api.deps import DB, CurrentUser
from signal_core.config import get_config
from signal_core.db.models import EvalRun, Job, LLMCall, Routine, Run
from signal_core.llm import budget as budget_mod
from signal_core.settings import get_settings

router = APIRouter(tags=["ops"])


@router.get("/costs")
async def costs(_: CurrentUser, db: DB, period: str = "month") -> dict[str, Any]:
    now = datetime.now(UTC)
    cfg = get_config().budget
    st = await budget_mod.status(db, cfg, get_settings().timezone, now)
    since = (
        budget_mod.month_start(now, get_settings().timezone)
        if period == "month"
        else now - timedelta(days=30)
    )
    day = func.date_trunc("day", LLMCall.created_at)
    by_day = (
        await db.execute(
            select(day, func.sum(LLMCall.cost_usd))
            .where(LLMCall.created_at >= since)
            .group_by(day)
            .order_by(day)
        )
    ).all()
    by_task = (
        await db.execute(
            select(LLMCall.task, func.sum(LLMCall.cost_usd), func.count())
            .where(LLMCall.created_at >= since)
            .group_by(LLMCall.task)
            .order_by(desc(func.sum(LLMCall.cost_usd)))
        )
    ).all()
    by_tier = (
        await db.execute(
            select(LLMCall.tier, func.sum(LLMCall.cost_usd), func.count())
            .where(LLMCall.created_at >= since)
            .group_by(LLMCall.tier)
        )
    ).all()
    by_routine = (
        await db.execute(
            select(Routine.name, func.sum(Run.cost_usd))
            .join(Run, Run.routine_id == Routine.id)
            .where(Run.started_at >= since)
            .group_by(Routine.name)
        )
    ).all()
    cache = (
        await db.execute(
            select(func.count())
            .select_from(LLMCall)
            .where(LLMCall.created_at >= since, LLMCall.cache_hit.is_(True))
        )
    ).scalar_one()
    return {
        "period_start": since.isoformat(),
        "month_spent": round(st.spent_usd, 4),
        "limit": st.limit_usd,
        "soft_limit": round(st.limit_usd * cfg.soft_limit_pct / 100, 2),
        "state": st.state,
        "projected": round(st.projected_usd, 2),
        "calls_today": st.calls_today,
        "max_calls_per_day": cfg.max_calls_per_day,
        "cache_hits": int(cache),
        "note": "API-equivalent cost estimated by the Claude Runner; billed against your subscription (ADR-001).",
        "by_day": [{"date": d.date().isoformat(), "cost": round(float(c or 0), 4)} for d, c in by_day],
        "by_task": [{"task": t, "cost": round(float(c or 0), 4), "calls": n} for t, c, n in by_task],
        "by_tier": [{"tier": t, "cost": round(float(c or 0), 4), "calls": n} for t, c, n in by_tier],
        "by_routine": [{"routine": r, "cost": round(float(c or 0), 4)} for r, c in by_routine],
    }


@router.get("/llm-calls")
async def ledger(
    _: CurrentUser, db: DB, limit: int = Query(100, le=500), task: str | None = None
) -> list[dict[str, Any]]:
    q = select(LLMCall).order_by(desc(LLMCall.created_at)).limit(limit)
    if task:
        q = q.where(LLMCall.task == task)
    return [
        {
            "id": str(c.id),
            "created_at": c.created_at.isoformat(),
            "task": c.task,
            "tier": c.tier,
            "model": c.model,
            "provider": c.provider,
            "prompt_version": c.prompt_version,
            "status": c.status,
            "input_tokens": c.input_tokens,
            "output_tokens": c.output_tokens,
            "cost_usd": c.cost_usd,
            "latency_ms": c.latency_ms,
            "cache_hit": c.cache_hit,
            "error": c.error,
        }
        for c in (await db.execute(q)).scalars()
    ]


@router.get("/evals/report")
async def evals_report(_: CurrentUser, db: DB) -> dict[str, Any] | None:
    r = (await db.execute(select(EvalRun).order_by(desc(EvalRun.created_at)).limit(1))).scalars().first()
    if r is None:
        return None
    return {"id": str(r.id), "created_at": r.created_at.isoformat(), "passed": r.passed, **r.report}


@router.post("/evals/run", status_code=201)
async def evals_run(_: CurrentUser, db: DB, sample: int | None = None) -> dict[str, Any]:
    from signal_core.ops.evals import run

    r = await run(db, sample)
    return {"id": str(r.id), "created_at": r.created_at.isoformat(), "passed": r.passed, **r.report}


@router.get("/ops/jobs")
async def jobs(_: CurrentUser, db: DB, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    q = select(Job).order_by(desc(Job.updated_at)).limit(limit)
    if status:
        q = q.where(Job.status == status)
    return [
        {
            "id": str(j.id),
            "name": j.name,
            "key": j.key,
            "status": j.status,
            "attempts": j.attempts,
            "error": j.error,
            "updated_at": j.updated_at.isoformat(),
        }
        for j in (await db.execute(q)).scalars()
    ]
