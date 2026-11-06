from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from signal_api.deps import DB, CurrentUser
from signal_core.db.models import FetchLog, Item, Source
from signal_core.radar.ingest import ingest_source, spec_of
from signal_core.radar.opml import import_opml
from signal_core.sources.base import AdapterNotConfigured, get_adapter
from signal_core.sources.http import PoliteClient

router = APIRouter(tags=["sources"])


def out(s: Source, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "type": s.type,
        "name": s.name,
        "url": s.url,
        "tier": s.tier,
        "ring": s.ring,
        "topics": s.topics,
        "fetch_every": s.fetch_every,
        "enabled": s.enabled,
        "params": s.params,
        "health": s.health,
        "usefulness": s.usefulness,
        "terms_note": s.terms_note,
        "last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
        **(extra or {}),
    }


@router.get("/sources")
async def list_sources(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    counts = dict((await db.execute(select(Item.source_id, func.count()).group_by(Item.source_id))).all())
    rows = (await db.execute(select(Source).order_by(Source.tier, Source.name))).scalars()
    return [out(s, {"items": counts.get(s.id, 0)}) for s in rows]


class SourceIn(BaseModel):
    type: str
    name: str = Field(min_length=1, max_length=255)
    url: str | None = None
    tier: int = Field(2, ge=1, le=3)
    ring: str = "core"
    topics: list[str] = []
    fetch_every: int = Field(60, ge=5, le=10080)
    enabled: bool = True
    params: dict[str, Any] = {}
    terms_note: str = ""


@router.post("/sources", status_code=201)
async def create_source(body: SourceIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    if (await db.execute(select(Source).where(Source.name == body.name))).scalar_one_or_none():
        raise HTTPException(409, "a source with that name exists")
    try:
        get_adapter(body.type)
    except AdapterNotConfigured as e:
        raise HTTPException(422, str(e)) from e
    s = Source(**body.model_dump())
    db.add(s)
    await db.flush()
    return out(s)


async def _get(db: DB, sid: uuid.UUID) -> Source:
    s = await db.get(Source, sid)
    if s is None:
        raise HTTPException(404, "source not found")
    return s


@router.get("/sources/{sid}")
async def get_source(sid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    return out(await _get(db, sid))


class SourcePatch(BaseModel):
    name: str | None = None
    url: str | None = None
    tier: int | None = Field(None, ge=1, le=3)
    ring: str | None = None
    topics: list[str] | None = None
    fetch_every: int | None = Field(None, ge=5, le=10080)
    enabled: bool | None = None
    params: dict[str, Any] | None = None
    terms_note: str | None = None


@router.put("/sources/{sid}")
async def update_source(sid: uuid.UUID, body: SourcePatch, _: CurrentUser, db: DB) -> dict[str, Any]:
    s = await _get(db, sid)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    if body.enabled:  # re-enabling clears the "fix or disable" flag
        s.health = {**(s.health or {}), "flagged": None, "consecutive_failures": 0}
    await db.flush()
    return out(s)


@router.delete("/sources/{sid}")
async def delete_source(sid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, bool]:
    """Sources with items are disabled rather than deleted (items keep their provenance)."""
    s = await _get(db, sid)
    n = (await db.execute(select(func.count()).select_from(Item).where(Item.source_id == s.id))).scalar_one()
    if n:
        s.enabled = False
        await db.flush()
        return {"deleted": False, "disabled": True}
    await db.delete(s)
    return {"deleted": True, "disabled": False}


@router.post("/sources/{sid}/test")
async def test_source(sid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    """Dry-run fetch: returns the first entries without storing anything."""
    s = await _get(db, sid)
    from signal_core.settings import get_settings

    if get_settings().is_mock:
        from signal_core.demo import fixture_client

        client = fixture_client()
    else:
        client = PoliteClient(retries=0)
    try:
        res = await get_adapter(s.type)(spec_of(s), client)
        return {
            "ok": True,
            "entries": len(res.entries),
            "sample": [
                {
                    "title": e.title,
                    "url": e.url,
                    "published_at": e.published_at.isoformat() if e.published_at else None,
                }
                for e in res.entries[:5]
            ],
        }
    except AdapterNotConfigured as e:
        return {"ok": False, "error": str(e), "not_configured": True}
    except Exception as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
    finally:
        await client.aclose()


@router.post("/sources/{sid}/fetch")
async def fetch_now(sid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    from signal_core.settings import get_settings

    client = None
    if get_settings().is_mock:
        from signal_core.demo import fixture_client

        client = fixture_client()
    st = await ingest_source(db, sid, client, datetime.now(UTC))
    if client is not None:
        await client.aclose()
    return {
        "status": st.status,
        "found": st.found,
        "new": st.new,
        "passed": st.passed,
        "duplicates": st.duplicates,
        "error": st.error,
    }


@router.get("/sources/{sid}/health")
async def source_health(sid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    s = await _get(db, sid)
    logs = (
        await db.execute(
            select(FetchLog).where(FetchLog.source_id == s.id).order_by(desc(FetchLog.started_at)).limit(20)
        )
    ).scalars()
    return {
        "source": out(s),
        "fetches": [
            {
                "started_at": f.started_at.isoformat(),
                "status": f.status,
                "found": f.items_found,
                "new": f.items_new,
                "latency_ms": f.latency_ms,
                "error": f.error,
            }
            for f in logs
        ],
    }


@router.post("/sources/import-opml")
async def opml(file: UploadFile, _: CurrentUser, db: DB) -> dict[str, int]:
    data = (await file.read()).decode("utf-8", "replace")
    try:
        return await import_opml(db, data)
    except Exception as e:
        raise HTTPException(400, f"could not parse OPML: {e}") from e
