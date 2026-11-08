"""Routines engine (§10.1): Routine = cron (user TZ) + steps + channels. Each execution is a Run.

Steps are registered by the engines (`@step("score")`). The scheduler finds due routines and enqueues
`run_routine`; `run_routine` executes steps in order, records outputs/log/cost in `runs`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import LLMCall, Routine, Run
from signal_core.db.session import session_scope
from signal_core.jobs import job
from signal_core.logging import get_logger

log = get_logger("routines")


@dataclass
class StepContext:
    session: AsyncSession
    routine: Routine
    run: Run
    now: datetime
    params: dict[str, Any]
    outputs: dict[str, Any] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)

    def log(self, msg: str) -> None:
        self.log_lines.append(f"{datetime.now(UTC).isoformat(timespec='seconds')} {msg}")


StepFn = Callable[[StepContext], Awaitable[Any]]
STEPS: dict[str, StepFn] = {}


def step(name: str) -> Callable[[StepFn], StepFn]:
    def deco(fn: StepFn) -> StepFn:
        STEPS[name] = fn
        return fn

    return deco


def load_step_modules() -> None:
    import importlib

    for mod in (
        "signal_core.radar.steps",
        "signal_core.radar.jobs",
        "signal_core.brief.steps",
        "signal_core.lab.steps",
        "signal_core.gym.steps",
        "signal_core.reviews.steps",
        "signal_core.ops.steps",
        "signal_core.notify.steps",
        "signal_core.analytics.steps",
    ):
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as e:
            if not e.name or not mod.startswith(e.name):
                raise


def next_fire(cron: str, tz: str, after: datetime) -> datetime:
    """Next fire time (UTC) of a cron expression interpreted in the routine's time zone."""
    local_after = after.astimezone(ZoneInfo(tz))
    nxt: datetime = croniter(cron, local_after).get_next(datetime)
    return nxt.astimezone(UTC)


def is_due(r: Routine, now: datetime) -> bool:
    if not r.enabled:
        return False
    base = r.last_run_at or (r.created_at if r.created_at else now)
    return next_fire(r.cron, r.timezone, base) <= now


async def execute(
    session: AsyncSession, routine: Routine, now: datetime | None = None, params: dict[str, Any] | None = None
) -> Run:
    load_step_modules()
    now = now or datetime.now(UTC)
    run = Run(routine_id=routine.id, name=routine.name, status="running", started_at=now)
    session.add(run)
    await session.flush()
    import structlog

    structlog.contextvars.bind_contextvars(run_id=str(run.id), routine=routine.name)
    ctx = StepContext(session, routine, run, now, {**(routine.params or {}), **(params or {})})
    status = "ok"
    for name in routine.steps:
        fn = STEPS.get(name)
        if fn is None:
            ctx.log(f"step {name}: not implemented yet, skipped")
            continue
        try:
            async with session.begin_nested():
                out = await fn(ctx)
            if out is not None:
                ctx.outputs[name] = out
            ctx.log(f"step {name}: ok")
        except Exception as e:
            status = "degraded"
            ctx.log(f"step {name}: ERROR {e.__class__.__name__}: {e}")
            log.warning("step_failed", routine=routine.name, step=name, error=str(e))
    if [c for c in routine.channels or [] if c != "app"]:
        try:
            from signal_core.notify.steps import deliver

            async with session.begin_nested():
                delivered = await deliver(ctx)
            if delivered:
                ctx.outputs["_delivered"] = delivered
                ctx.log(f"delivered: {delivered}")
        except Exception as e:
            ctx.log(f"delivery ERROR {e.__class__.__name__}: {e}")
    cost = (
        await session.execute(
            select(func.coalesce(func.sum(LLMCall.cost_usd), 0.0)).where(LLMCall.run_id == run.id)
        )
    ).scalar_one()
    run.status = status
    from signal_core.ops.metrics import ROUTINE_RUNS

    ROUTINE_RUNS.labels(routine.name, status).inc()
    run.finished_at = datetime.now(UTC) if now is None else now
    run.outputs = ctx.outputs
    run.log = "\n".join(ctx.log_lines)
    run.cost_usd = float(cost)
    routine.last_run_at = now
    routine.next_run_at = next_fire(routine.cron, routine.timezone, now)
    await session.flush()
    return run


@job("run_routine")
async def run_routine(routine_id: str, now: str | None = None, params: dict[str, Any] | None = None) -> str:
    async with session_scope() as s:
        r = await s.get(Routine, uuid.UUID(routine_id))
        if r is None:
            raise LookupError(f"routine {routine_id} not found")
        run = await execute(s, r, datetime.fromisoformat(now) if now else None, params)
        return str(run.id)


async def due_routines(session: AsyncSession, now: datetime) -> list[Routine]:
    rows = (await session.execute(select(Routine).where(Routine.enabled.is_(True)))).scalars().all()
    return [r for r in rows if is_due(r, now)]
