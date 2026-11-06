"""Briefs, habit, watches, routines/runs, notifications, onboarding (§13, M3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from croniter import croniter
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from signal_api.deps import DB, CurrentUser
from signal_core.brief import habit
from signal_core.brief.assemble import assemble
from signal_core.db.models import (
    Brief,
    Card,
    Notification,
    Profile,
    Routine,
    Run,
    Skill,
    Source,
    Story,
    User,
    Watch,
    WatchHit,
)
from signal_core.radar.watches import check_watches, create_watch
from signal_core.routines.engine import execute, next_fire
from signal_core.services.seed import rebuild_profile_vectors

router = APIRouter(tags=["briefs"])


def brief_out(b: Brief) -> dict[str, Any]:
    return {
        "id": str(b.id),
        "kind": b.kind,
        "period_start": b.period_start.isoformat(),
        "period_end": b.period_end.isoformat(),
        "content": b.content,
        "degraded": b.degraded,
        "opened_at": b.opened_at.isoformat() if b.opened_at else None,
        "completed_at": b.completed_at.isoformat() if b.completed_at else None,
        "created_at": b.created_at.isoformat(),
    }


@router.get("/briefs/latest")
async def latest(_: CurrentUser, db: DB, kind: str = "daily") -> dict[str, Any] | None:
    kinds = ["daily", "catchup", "weekend"] if kind == "daily" else [kind]
    b = (
        (
            await db.execute(
                select(Brief).where(Brief.kind.in_(kinds)).order_by(desc(Brief.created_at)).limit(1)
            )
        )
        .scalars()
        .first()
    )
    return brief_out(b) if b else None


@router.get("/briefs")
async def list_briefs(_: CurrentUser, db: DB, limit: int = Query(20, le=100)) -> list[dict[str, Any]]:
    rows = (await db.execute(select(Brief).order_by(desc(Brief.created_at)).limit(limit))).scalars()
    return [
        {k: v for k, v in brief_out(b).items() if k != "content"}
        | {"stories": len(b.content.get("stories", []))}
        for b in rows
    ]


@router.get("/briefs/{bid}")
async def get_brief(bid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    b = await db.get(Brief, bid)
    if b is None:
        raise HTTPException(404, "brief not found")
    return brief_out(b)


@router.post("/briefs/{bid}/open")
async def open_brief(bid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    b = await db.get(Brief, bid)
    if b is None:
        raise HTTPException(404, "brief not found")
    if b.opened_at is None:
        b.opened_at = datetime.now(UTC)
    return {"opened_at": b.opened_at.isoformat()}


class CompleteIn(BaseModel):
    minimum: bool = False  # "2-minute mode": top 3 one-liners (+ 3 cards) still counts


@router.post("/briefs/{bid}/complete")
async def complete(bid: uuid.UUID, body: CompleteIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    b = await db.get(Brief, bid)
    if b is None:
        raise HTTPException(404, "brief not found")
    now = datetime.now(UTC)
    b.completed_at = b.completed_at or now
    b.opened_at = b.opened_at or now
    due = (await db.execute(select(func.count()).select_from(Card).where(Card.due_at <= now))).scalar_one()
    day = await habit.mark(db, now, "minimum" if body.minimum else "brief", int(due))
    return {
        "completed_at": b.completed_at.isoformat(),
        "habit_day": {"date": day.date.isoformat(), "mode": day.mode, "steps": day.steps},
    }


class GenerateIn(BaseModel):
    kind: Literal["daily", "weekend", "custom"] = "daily"
    params: dict[str, Any] = {}


@router.post("/briefs/generate", status_code=201)
async def generate(body: GenerateIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    from signal_core.radar.pipeline import process

    now = datetime.now(UTC)
    await process(db, now)
    await check_watches(db, now)
    b = await assemble(db, now, body.kind, body.params)
    return brief_out(b)


# ---------------- habit / today ----------------
class HabitIn(BaseModel):
    step: Literal["brief", "action", "cards", "minimum"]


@router.post("/habit/mark")
async def habit_mark(body: HabitIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    now = datetime.now(UTC)
    due = (await db.execute(select(func.count()).select_from(Card).where(Card.due_at <= now))).scalar_one()
    day = await habit.mark(db, now, body.step, int(due))
    return {"date": day.date.isoformat(), "mode": day.mode, "steps": day.steps}


@router.post("/habit/freeze")
async def habit_freeze(_: CurrentUser, db: DB) -> dict[str, Any]:
    ok = await habit.use_freeze(db, habit.local_day(datetime.now(UTC)))
    return {"ok": ok, **(await habit.streak(db, habit.local_day(datetime.now(UTC))))}


@router.get("/today")
async def today(_: CurrentUser, db: DB) -> dict[str, Any]:
    now = datetime.now(UTC)
    d = habit.local_day(now)
    day = await habit.get_day(db, d)
    b = (await db.execute(select(Brief).order_by(desc(Brief.created_at)).limit(1))).scalars().first()
    due = (await db.execute(select(func.count()).select_from(Card).where(Card.due_at <= now))).scalar_one()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    outputs: dict[str, int] = {}
    for label, model, col in (
        ("posts", "Publication", "published_at"),
        ("pocs", "Idea", "updated_at"),
        ("cards", "CardReview", "reviewed_at"),
    ):
        from signal_core.db import models as m

        mdl = getattr(m, model)
        q = select(func.count()).select_from(mdl).where(getattr(mdl, col) >= month_start)
        if model == "Idea":
            q = q.where(mdl.status.in_(["shipped", "shared"]))
        outputs[label] = int((await db.execute(q)).scalar_one())
    unread = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.channel == "app", Notification.read_at.is_(None))
        )
    ).scalar_one()
    return {
        "date": d.isoformat(),
        "habit": {"mode": day.mode, "steps": day.steps, **(await habit.streak(db, d))},
        "brief": brief_out(b) if b else None,
        "cards_due": int(due),
        "this_month": outputs,
        "unread_notifications": int(unread),
    }


# ---------------- watches ----------------
class WatchIn(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    urgency: Literal["instant", "digest"] = "digest"
    filters: dict[str, list[str]] = {}
    expires_at: datetime | None = None


def watch_out(w: Watch, hits: int = 0) -> dict[str, Any]:
    return {
        "id": str(w.id),
        "query": w.query,
        "urgency": w.urgency,
        "enabled": w.enabled,
        "filters": {k: v for k, v in (w.filters or {}).items() if not k.startswith("_")},
        "expires_at": w.expires_at.isoformat() if w.expires_at else None,
        "last_triggered": w.last_triggered.isoformat() if w.last_triggered else None,
        "hits": hits,
    }


@router.get("/watches")
async def list_watches(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    counts = dict(
        (await db.execute(select(WatchHit.watch_id, func.count()).group_by(WatchHit.watch_id))).all()
    )
    return [
        watch_out(w, counts.get(w.id, 0))
        for w in (await db.execute(select(Watch).order_by(desc(Watch.created_at)))).scalars()
    ]


@router.post("/watches", status_code=201)
async def add_watch(body: WatchIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    w = await create_watch(db, body.query, body.urgency, body.filters, body.expires_at)
    return watch_out(w)


class WatchPatch(BaseModel):
    enabled: bool | None = None
    urgency: Literal["instant", "digest"] | None = None
    expires_at: datetime | None = None


@router.put("/watches/{wid}")
async def patch_watch(wid: uuid.UUID, body: WatchPatch, _: CurrentUser, db: DB) -> dict[str, Any]:
    w = await db.get(Watch, wid)
    if w is None:
        raise HTTPException(404, "watch not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(w, k, v)
    return watch_out(w)


@router.delete("/watches/{wid}")
async def delete_watch(wid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, bool]:
    w = await db.get(Watch, wid)
    if w is None:
        raise HTTPException(404, "watch not found")
    await db.delete(w)
    return {"deleted": True}


@router.get("/watches/{wid}/hits")
async def watch_hits(wid: uuid.UUID, _: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(WatchHit, Story)
            .join(Story, Story.id == WatchHit.story_id)
            .where(WatchHit.watch_id == wid)
            .order_by(desc(WatchHit.created_at))
        )
    ).all()
    return [
        {
            "story_id": str(s.id),
            "title": s.title,
            "explanation": h.explanation,
            "created_at": h.created_at.isoformat(),
        }
        for h, s in rows
    ]


@router.post("/watches/check")
async def run_watch_check(_: CurrentUser, db: DB) -> dict[str, int]:
    st = await check_watches(db, datetime.now(UTC))
    return {"checked": st.checked, "hits": st.hits, "notified": st.notified}


# ---------------- notifications (in-app) ----------------
@router.get("/notifications")
async def notifications(_: CurrentUser, db: DB, limit: int = 30) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(Notification)
            .where(Notification.channel == "app")
            .order_by(desc(Notification.created_at))
            .limit(limit)
        )
    ).scalars()
    return [
        {
            "id": str(n.id),
            "kind": n.kind,
            "payload": n.payload,
            "created_at": n.created_at.isoformat(),
            "read": n.read_at is not None,
        }
        for n in rows
    ]


@router.post("/notifications/read-all")
async def read_all(_: CurrentUser, db: DB) -> dict[str, bool]:
    for n in (await db.execute(select(Notification).where(Notification.read_at.is_(None)))).scalars():
        n.read_at = datetime.now(UTC)
    return {"ok": True}


# ---------------- routines / runs ----------------
def routine_out(r: Routine) -> dict[str, Any]:
    nxt = next_fire(r.cron, r.timezone, datetime.now(UTC)) if r.enabled else None
    return {
        "id": str(r.id),
        "name": r.name,
        "cron": r.cron,
        "timezone": r.timezone,
        "steps": r.steps,
        "channels": r.channels,
        "enabled": r.enabled,
        "params": r.params,
        "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
        "next_run_at": nxt.isoformat() if nxt else None,
    }


@router.get("/routines")
async def list_routines(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    return [routine_out(r) for r in (await db.execute(select(Routine).order_by(Routine.name))).scalars()]


class RoutineIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    cron: str
    steps: list[str] = Field(min_length=1)
    channels: list[Literal["app", "telegram", "email", "push"]] = ["app"]
    params: dict[str, Any] = {}
    enabled: bool = True


def _check(body: RoutineIn | RoutinePatch) -> None:
    from signal_core.routines.engine import STEPS, load_step_modules

    load_step_modules()
    if body.cron is not None and not croniter.is_valid(body.cron):
        raise HTTPException(422, f"invalid cron expression: {body.cron!r}")
    unknown = [s for s in (body.steps or []) if s not in STEPS]
    if unknown:
        raise HTTPException(422, f"unknown steps: {unknown}. Available: {sorted(STEPS)}")


@router.post("/routines", status_code=201)
async def create_routine(body: RoutineIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    _check(body)
    r = Routine(**body.model_dump(), timezone=user.timezone)
    db.add(r)
    await db.flush()
    return routine_out(r)


class RoutinePatch(BaseModel):
    cron: str | None = None
    steps: list[str] | None = None
    channels: list[str] | None = None
    params: dict[str, Any] | None = None
    enabled: bool | None = None


@router.put("/routines/{rid}")
async def update_routine(rid: uuid.UUID, body: RoutinePatch, _: CurrentUser, db: DB) -> dict[str, Any]:
    _check(body)
    r = await db.get(Routine, rid)
    if r is None:
        raise HTTPException(404, "routine not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(r, k, v)
    return routine_out(r)


@router.delete("/routines/{rid}")
async def delete_routine(rid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, bool]:
    r = await db.get(Routine, rid)
    if r is None:
        raise HTTPException(404, "routine not found")
    await db.delete(r)
    return {"deleted": True}


@router.post("/routines/{rid}/run-now")
async def run_now(rid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    r = await db.get(Routine, rid)
    if r is None:
        raise HTTPException(404, "routine not found")
    run = await execute(db, r, datetime.now(UTC))
    return run_out(run)


@router.get("/routines/steps")
async def available_steps(_: CurrentUser) -> list[str]:
    from signal_core.routines.engine import STEPS, load_step_modules

    load_step_modules()
    return sorted(STEPS)


def run_out(r: Run) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "name": r.name,
        "status": r.status,
        "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "cost_usd": r.cost_usd,
        "outputs": r.outputs,
        "log": r.log,
    }


@router.get("/runs")
async def list_runs(_: CurrentUser, db: DB, limit: int = Query(50, le=200)) -> list[dict[str, Any]]:
    return [
        run_out(r)
        for r in (await db.execute(select(Run).order_by(desc(Run.started_at)).limit(limit))).scalars()
    ]


@router.get("/runs/{rid}")
async def get_run(rid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    r = await db.get(Run, rid)
    if r is None:
        raise HTTPException(404, "run not found")
    return run_out(r)


# ---------------- onboarding wizard (§14) ----------------
class OnboardingIn(BaseModel):
    role: str
    goals: list[str] = Field(min_length=1)
    stack: list[str] = []
    topics: dict[str, Any] | None = None
    skills: dict[str, int] = {}  # skill name → self-rating 0–5
    sources_enabled: dict[str, bool] = {}  # source id → enabled
    daily_brief_cron: str | None = None
    budget_monthly_usd: float | None = None


@router.post("/onboarding/complete")
async def onboarding(body: OnboardingIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    from signal_core.db.base import OWNER_ID
    from signal_core.services.settings_store import set_setting

    p = (await db.execute(select(Profile).where(Profile.user_id == OWNER_ID))).scalar_one()
    p.role, p.goals, p.stack = body.role, body.goals, body.stack
    if body.topics:
        p.topics = body.topics
    p.version += 1
    await db.flush()
    await rebuild_profile_vectors(db, p)
    for name, level in body.skills.items():
        sk = (await db.execute(select(Skill).where(Skill.name == name))).scalar_one_or_none()
        if sk is not None:
            sk.current_level = max(0, min(5, level))
    for sid, on in body.sources_enabled.items():
        s = await db.get(Source, uuid.UUID(sid))
        if s is not None:
            s.enabled = on
    if body.daily_brief_cron:
        if not croniter.is_valid(body.daily_brief_cron):
            raise HTTPException(422, "invalid cron")
        r = (await db.execute(select(Routine).where(Routine.name == "daily_brief"))).scalar_one_or_none()
        if r is not None:
            r.cron = body.daily_brief_cron
    if body.budget_monthly_usd:
        await set_setting(db, "budget_monthly_usd", body.budget_monthly_usd)
    u = await db.get(User, user.id)
    assert u is not None
    u.onboarded_at = datetime.now(UTC)
    return {"ok": True, "profile_version": p.version}
