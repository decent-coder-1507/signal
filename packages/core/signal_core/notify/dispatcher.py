"""Notification dispatcher (§10.2): quiet hours + max notifications per day for push channels (telegram, email,
push). In-app notifications are never capped. During quiet hours messages are queued and flushed afterwards; over
the daily cap they are suppressed (still visible in-app). Never shame-based copy — callers own the wording."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.models import Notification
from signal_core.logging import get_logger
from signal_core.services.settings_store import flag, get_setting
from signal_core.settings import get_settings

log = get_logger("notify")
PUSH_CHANNELS = ("telegram", "email", "push")


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


async def in_quiet_hours(session: AsyncSession, now: datetime) -> bool:
    qh = await get_setting(session, "quiet_hours") or list(get_config().routines.notifications.quiet_hours)
    start, end = _hm(qh[0]), _hm(qh[1])
    local = now.astimezone(ZoneInfo(get_settings().timezone)).time()
    return (local >= start or local < end) if start > end else (start <= local < end)


async def sent_today(session: AsyncSession, now: datetime) -> int:
    local = now.astimezone(ZoneInfo(get_settings().timezone))
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.channel.in_(PUSH_CHANNELS),
                    Notification.status == "sent",
                    Notification.sent_at >= day_start,
                )
            )
        ).scalar_one()
    )


async def daily_cap(session: AsyncSession) -> int:
    v = await get_setting(session, "notifications_max_per_day")
    return int(v if v is not None else get_config().routines.notifications.max_per_day)


async def channel_enabled(session: AsyncSession, channel: str) -> bool:
    s = get_settings()
    if channel == "app":
        return True
    if channel == "telegram":
        return await flag(session, "channel.telegram") and bool(s.telegram_bot_token and s.telegram_chat_id)
    if channel == "email":
        return await flag(session, "channel.email") and (bool(s.smtp_url) or s.is_mock)
    if channel == "push":
        return await flag(session, "channel.push")
    return False


async def dispatch(
    session: AsyncSession,
    channel: str,
    kind: str,
    payload: dict[str, Any],
    now: datetime | None = None,
    urgent: bool = False,
) -> Notification:
    """Record and (if allowed) send. Returns the Notification row with its final status."""
    now = now or datetime.now(UTC)
    n = Notification(channel=channel, kind=kind, payload=payload, status="queued")
    session.add(n)
    await session.flush()
    if channel == "app":
        n.status, n.sent_at = "sent", now
        return n
    if not await channel_enabled(session, channel):
        n.status = "suppressed"
        n.payload = {**payload, "_reason": "channel disabled"}
        return n
    if not urgent and await in_quiet_hours(session, now):
        n.payload = {**payload, "_reason": "quiet hours", "_queued_at": now.isoformat()}
        return n  # stays queued; flushed after quiet hours
    if await sent_today(session, now) >= await daily_cap(session):
        n.status = "suppressed"
        n.payload = {**payload, "_reason": "daily notification cap reached"}
        session.add(Notification(channel="app", kind=kind, payload=payload, status="sent", sent_at=now))
        return n
    await _send(session, n, now)
    return n


async def _send(session: AsyncSession, n: Notification, now: datetime) -> None:
    try:
        if n.channel == "telegram":
            from signal_core.notify.telegram import send_notification

            await send_notification(n.kind, n.payload)
        elif n.channel == "email":
            from signal_core.notify.email import send_digest

            await send_digest(n.kind, n.payload)
        n.status, n.sent_at = "sent", now
    except Exception as e:
        n.status = "failed"
        n.payload = {**n.payload, "_error": str(e)[:300]}
        log.warning("notify_failed", channel=n.channel, error=str(e))
    await session.flush()


async def flush_queued(session: AsyncSession, now: datetime) -> int:
    """Send messages held back by quiet hours (oldest first), still honouring the daily cap."""
    if await in_quiet_hours(session, now):
        return 0
    rows = [
        n
        for n in (
            await session.execute(
                select(Notification)
                .where(Notification.status == "queued", Notification.channel.in_(PUSH_CHANNELS))
                .order_by(Notification.created_at)
            )
        ).scalars()
        if now - datetime.fromisoformat(n.payload.get("_queued_at", now.isoformat())) <= timedelta(days=1)
    ]

    sent = 0
    for n in rows:
        if await sent_today(session, now) >= await daily_cap(session):
            n.status = "suppressed"
            continue
        await _send(session, n, now)
        sent += n.status == "sent"
    return sent
