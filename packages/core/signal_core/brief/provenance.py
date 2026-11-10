"""'How this brief was made' (trust panel): computed only from rows already stored — the brief content, the
routine run and its llm_calls ledger rows, fetch logs and items. Nothing here calls a model."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import Brief, FetchLog, Item, LLMCall, Run, Story
from signal_core.settings import get_settings

# An on-demand brief (POST /briefs/generate) has no routine run, so its AI calls are the un-run-tagged ledger rows
# written in the minutes before it was stored (the pipeline pass + top line).
ON_DEMAND_WINDOW = timedelta(minutes=15)
NOT_PASSED = ("new", "prefiltered_out", "duplicate")


def _uuid(v: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v))
    except (ValueError, TypeError):
        return None


async def brief_provenance(session: AsyncSession, b: Brief) -> dict[str, Any]:
    c = b.content or {}
    start, end = b.period_start, b.period_end

    # Sources: distinct feeds fetched during the brief's window.
    fetch = (
        await session.execute(
            select(
                func.count(func.distinct(FetchLog.source_id)),
                func.count(),
                func.count().filter(FetchLog.status == "error"),
            ).where(FetchLog.started_at >= start, FetchLog.started_at <= end)
        )
    ).one()

    # Items: published (or, when undated, fetched) inside the window; captures and duplicates don't count.
    when = func.coalesce(Item.published_at, Item.fetched_at)
    in_window = and_(when >= start, when <= end, Item.is_capture.is_(False))
    items = (
        await session.execute(
            select(
                func.count().filter(Item.status != "duplicate"),
                func.count().filter(Item.status.notin_(NOT_PASSED)),
            ).where(in_window)
        )
    ).one()

    # Stories: assembly records its pool; older briefs fall back to today's view of the same window.
    stats = c.get("stats") or {}
    considered = stats.get("stories_considered")
    if considered is None:
        considered = (
            await session.execute(
                select(func.count())
                .select_from(Story)
                .where(Story.last_updated >= start, Story.last_updated <= end, Story.ring != "wide")
            )
        ).scalar_one()

    # AI calls for this brief's run (ledger rows tagged with the routine run id).
    run = await session.get(Run, b.routine_run_id) if b.routine_run_id else None
    if run is not None:
        scope = "run"
        cond = LLMCall.run_id == run.id
    else:
        scope = "window"
        cond = and_(
            LLMCall.run_id.is_(None),
            LLMCall.created_at >= b.created_at - ON_DEMAND_WINDOW,
            LLMCall.created_at <= b.created_at + timedelta(seconds=5),
        )
    calls = (
        await session.execute(
            select(LLMCall.model, LLMCall.task, LLMCall.status, LLMCall.cache_hit, LLMCall.cost_usd).where(
                cond
            )
        )
    ).all()
    models: dict[str, int] = {}
    tasks: dict[str, int] = {}
    for model, task, _status, _hit, _cost in calls:
        models[model] = models.get(model, 0) + 1
        tasks[task] = tasks.get(task, 0) + 1

    # Citations: every source id on a story card, verified = still resolves to a stored item.
    cited = [cit.get("id") for s in c.get("stories", []) for cit in s.get("citations", [])]
    ids = {u for u in (_uuid(x) for x in cited) if u is not None}
    verified_ids: set[uuid.UUID] = set()
    if ids:
        verified_ids = set((await session.execute(select(Item.id).where(Item.id.in_(ids)))).scalars())
    verified = sum(1 for x in cited if _uuid(x) in verified_ids)

    return {
        "brief_id": str(b.id),
        "kind": b.kind,
        "generated_at": (c.get("generated_at") or b.created_at.isoformat()),
        "timezone": get_settings().timezone,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "sources": {"scanned": int(fetch[0]), "fetches": int(fetch[1]), "errors": int(fetch[2])},
        "items": {"in_window": int(items[0]), "passed_prefilter": int(items[1])},
        "stories": {
            "considered": int(considered),
            "eligible": stats.get("stories_eligible"),
            "shown": len(c.get("stories", [])),
            "quick_hits": len(c.get("quick_hits", [])),
        },
        "ai": {
            "scope": scope,
            "calls": len(calls),
            "cached": sum(1 for x in calls if x[3] or x[2] == "cached"),
            "failed": sum(1 for x in calls if x[2] in ("error", "invalid", "budget_blocked")),
            "cost_usd": round(sum(float(x[4] or 0) for x in calls), 4),
            "models": [{"model": m, "calls": n} for m, n in sorted(models.items(), key=lambda kv: -kv[1])],
            "tasks": [{"task": t, "calls": n} for t, n in sorted(tasks.items(), key=lambda kv: -kv[1])],
        },
        "citations": {"total": len(cited), "verified": verified},
        "degraded": bool(b.degraded),
        "run": {"id": str(run.id), "name": run.name, "status": run.status} if run is not None else None,
    }
