"""Voice profile versioning (§7.4): every change creates a new version; drafts record which produced them."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import VoiceProfile


async def active_voice(session: AsyncSession) -> VoiceProfile | None:
    return (
        await session.execute(select(VoiceProfile).where(VoiceProfile.active.is_(True)))
    ).scalar_one_or_none()


async def new_voice_version(
    session: AsyncSession,
    *,
    rules: dict[str, Any] | None = None,
    banned_phrases: list[str] | None = None,
    emoji_set: list[str] | None = None,
    platform_overrides: dict[str, Any] | None = None,
    note: str = "",
) -> VoiceProfile:
    cur = await active_voice(session)
    next_v = ((await session.execute(select(func.max(VoiceProfile.version)))).scalar() or 0) + 1
    v = VoiceProfile(
        version=next_v,
        rules={**(cur.rules if cur else {}), **(rules or {})},
        banned_phrases=banned_phrases if banned_phrases is not None else (cur.banned_phrases if cur else []),
        emoji_set=emoji_set if emoji_set is not None else (cur.emoji_set if cur else []),
        platform_overrides={**(cur.platform_overrides if cur else {}), **(platform_overrides or {})},
        active=True,
        note=note,
    )
    await session.execute(update(VoiceProfile).values(active=False))
    session.add(v)
    await session.flush()
    return v
