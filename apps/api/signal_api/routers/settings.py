from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from signal_api.deps import DB, CurrentUser
from signal_core.db.base import OWNER_ID
from signal_core.db.models import Profile, VoiceProfile
from signal_core.services.seed import rebuild_profile_vectors
from signal_core.services.settings_store import all_settings, set_setting

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def get_settings_(_: CurrentUser, db: DB) -> dict[str, Any]:
    return await all_settings(db)


@router.put("/settings")
async def put_settings(body: dict[str, Any], _: CurrentUser, db: DB) -> dict[str, Any]:
    for k, v in body.items():
        if k == "flags" and isinstance(v, dict):
            current = (await all_settings(db))["flags"]
            v = {**current, **{fk: bool(fv) for fk, fv in v.items()}}
        await set_setting(db, k, v)
    return await all_settings(db)


def _profile_out(p: Profile) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "role": p.role,
        "goals": p.goals,
        "stack": p.stack,
        "topics": p.topics,
        "blocked_entities": p.blocked_entities,
        "blocked_keywords": p.blocked_keywords,
        "vanco_context": p.vanco_context,
        "version": p.version,
    }


@router.get("/profile")
async def get_profile(_: CurrentUser, db: DB) -> dict[str, Any]:
    p = (await db.execute(select(Profile).where(Profile.user_id == OWNER_ID))).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "profile not seeded; run `scripts/dev.py seed`")
    return _profile_out(p)


class ProfileIn(BaseModel):
    role: str | None = None
    goals: list[str] | None = None
    stack: list[str] | None = None
    topics: dict[str, Any] | None = None
    blocked_entities: list[str] | None = None
    blocked_keywords: list[str] | None = None
    vanco_context: str | None = None


@router.put("/profile")
async def put_profile(body: ProfileIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    p = (await db.execute(select(Profile).where(Profile.user_id == OWNER_ID))).scalar_one()
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    p.version += 1
    await db.flush()
    await rebuild_profile_vectors(db, p)
    return _profile_out(p)


def _voice_out(v: VoiceProfile) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "version": v.version,
        "rules": v.rules,
        "banned_phrases": v.banned_phrases,
        "emoji_set": v.emoji_set,
        "platform_overrides": v.platform_overrides,
        "active": v.active,
        "note": v.note,
    }


@router.get("/voice")
async def get_voice(_: CurrentUser, db: DB) -> dict[str, Any]:
    v = (await db.execute(select(VoiceProfile).where(VoiceProfile.active.is_(True)))).scalar_one_or_none()
    if v is None:
        raise HTTPException(404, "no active voice profile")
    versions = (
        await db.execute(
            select(VoiceProfile.version, VoiceProfile.note, VoiceProfile.created_at).order_by(
                VoiceProfile.version
            )
        )
    ).all()
    return {
        **_voice_out(v),
        "history": [{"version": a, "note": b, "created_at": c.isoformat()} for a, b, c in versions],
    }


class VoiceIn(BaseModel):
    rules: dict[str, Any] | None = None
    banned_phrases: list[str] | None = None
    emoji_set: list[str] | None = None
    platform_overrides: dict[str, Any] | None = None
    note: str = "edited in settings"


@router.put("/voice")
async def put_voice(body: VoiceIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    """Every change creates a new voice version (§7.4)."""
    from signal_core.studio.voice import new_voice_version

    v = await new_voice_version(db, **body.model_dump())
    return _voice_out(v)
