"""Habit mechanics (§10.2): daily progress (brief triaged → 1 action → cards), minimum-viable day, streaks with
freezes (2/month by default), never shame-based."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.models import HabitDay
from signal_core.settings import get_settings

STEPS = ("brief", "action", "cards")


def local_day(now: datetime) -> date:
    return now.astimezone(ZoneInfo(get_settings().timezone)).date()


async def get_day(session: AsyncSession, d: date) -> HabitDay:
    row = (await session.execute(select(HabitDay).where(HabitDay.date == d))).scalar_one_or_none()
    if row is None:
        row = HabitDay(date=d, mode="missed", steps={})
        session.add(row)
        await session.flush()
    return row


def compute_mode(steps: dict[str, Any], cards_due: int) -> str:
    cards_ok = bool(steps.get("cards")) or cards_due == 0
    if steps.get("brief") and steps.get("action") and cards_ok:
        return "full"
    if steps.get("brief") or steps.get("minimum"):
        return "minimum"  # 2-minute mode still counts (§10.2)
    return "missed"


async def mark(session: AsyncSession, now: datetime, step: str, cards_due: int = 0) -> HabitDay:
    day = await get_day(session, local_day(now))
    steps = dict(day.steps or {})
    steps[step] = now.isoformat()
    day.steps = steps
    if day.mode != "freeze":
        day.mode = compute_mode(steps, cards_due)
    await session.flush()
    return day


async def use_freeze(session: AsyncSession, d: date) -> bool:
    cfg = get_config().routines.habit
    month_start = d.replace(day=1)
    used = (
        await session.execute(
            select(func.count())
            .select_from(HabitDay)
            .where(HabitDay.mode == "freeze", HabitDay.date >= month_start, HabitDay.date <= d)
        )
    ).scalar_one()
    if used >= cfg.streak_freezes_per_month:
        return False
    day = await get_day(session, d)
    if day.mode in ("full", "minimum"):
        return False
    day.mode = "freeze"
    await session.flush()
    return True


async def streak(session: AsyncSession, today: date) -> dict[str, Any]:
    rows = {
        r.date: r.mode
        for r in (
            await session.execute(select(HabitDay).where(HabitDay.date >= today - timedelta(days=400)))
        ).scalars()
    }
    n, d = 0, today
    if rows.get(d) in (None, "missed"):  # today not done yet: streak counts up to yesterday
        d -= timedelta(days=1)
    while rows.get(d) in ("full", "minimum", "freeze"):
        n += 1
        d -= timedelta(days=1)
    month = today.replace(day=1)
    freezes_used = sum(1 for k, v in rows.items() if v == "freeze" and k >= month)
    return {
        "streak": n,
        "today": rows.get(today, "missed"),
        "freezes_left": max(0, get_config().routines.habit.streak_freezes_per_month - freezes_used),
    }
