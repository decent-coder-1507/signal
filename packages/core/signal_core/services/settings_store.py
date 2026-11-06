"""Key/value settings and feature flags (§5.4: feature flags in settings table for every engine/adapter)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.base import OWNER_ID
from signal_core.db.models import Setting

DEFAULT_FLAGS: dict[str, bool] = {
    "engine.radar": True,
    "engine.studio": True,
    "engine.lab": True,
    "engine.gym": True,
    "adapter.reddit": False,
    "adapter.x": False,
    "adapter.producthunt": False,
    "adapter.email_in": False,
    "adapter.youtube_transcripts": False,
    "channel.telegram": False,
    "channel.email": False,
    "channel.push": False,
    "publish.hashnode_api": False,
    "publish.x_api": False,
    "publish.linkedin_api": False,
    "publish.instagram_api": False,
    "lab.github_repo_create": False,
    "ai.image_generation": False,
    "ask.web_search": False,
}

DEFAULTS: dict[str, Any] = {
    "flags": DEFAULT_FLAGS,
    "brand_kit": {
        "handle": "@srijoy",
        "name": "Srijoy Paul",
        "primary": "#111827",
        "accent": "#F59E0B",
        "background": "#FFFFFF",
        "font_heading": "Inter",
        "font_body": "Inter",
        "avatar_url": None,
        "logo_url": None,
        "use_vanco_logo": False,
    },
    "quiet_hours": ["22:30", "07:00"],
    "notifications_max_per_day": 4,
    "budget_monthly_usd": 30,
    "voice_calibrated": False,
}


async def get_setting(session: AsyncSession, key: str, default: Any = None) -> Any:
    row = (
        await session.execute(select(Setting).where(Setting.user_id == OWNER_ID, Setting.key == key))
    ).scalar_one_or_none()
    if row is None:
        return DEFAULTS.get(key, default) if default is None else default
    return row.value


async def set_setting(session: AsyncSession, key: str, value: Any) -> None:
    row = (
        await session.execute(select(Setting).where(Setting.user_id == OWNER_ID, Setting.key == key))
    ).scalar_one_or_none()
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    await session.flush()


async def all_settings(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.execute(select(Setting).where(Setting.user_id == OWNER_ID))).scalars().all()
    merged = dict(DEFAULTS)
    merged.update({r.key: r.value for r in rows})
    merged["flags"] = {**DEFAULT_FLAGS, **(merged.get("flags") or {})}
    return merged


async def flag(session: AsyncSession, name: str) -> bool:
    flags = await get_setting(session, "flags") or {}
    return bool({**DEFAULT_FLAGS, **flags}.get(name, False))
