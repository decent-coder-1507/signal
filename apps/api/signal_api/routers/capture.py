"""Capture (§11.2) and item lookup. Works with the session cookie or the API token (bookmarklet, bot)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Form, HTTPException, UploadFile

from signal_api.deps import DB, CurrentUser
from signal_core.db.models import Item, Source
from signal_core.radar.capture import capture_pdf, capture_text, capture_url
from signal_core.radar.ingest import screen_new_items

router = APIRouter(tags=["capture"])
Intent = Literal["read_later", "post", "build", "learn"]
MAX_PDF = 20 * 1024 * 1024


def item_out(i: Item, source: Source | None = None) -> dict[str, Any]:
    return {
        "id": str(i.id),
        "title": i.title,
        "url": i.canonical_url,
        "source": source.name if source else None,
        "source_tier": source.tier if source else None,
        "published_at": i.published_at.isoformat() if i.published_at else None,
        "content_type": i.content_type,
        "status": i.status,
        "word_count": i.word_count,
        "is_capture": i.is_capture,
        "capture_intent": i.capture_intent,
        "prefilter_score": i.prefilter_score,
        "signal_meta": i.signal_meta,
        "duplicate_of": str(i.duplicate_of) if i.duplicate_of else None,
        "text": i.text[:20000],
    }


@router.post("/capture", status_code=201)
async def capture(
    _: CurrentUser,
    db: DB,
    url: str | None = Form(None),
    text: str | None = Form(None),
    title: str | None = Form(None),
    note: str | None = Form(None),
    intent: Intent | None = Form(None),
    file: UploadFile | None = None,
) -> dict[str, Any]:
    """Multipart form: one of url | text | file (PDF). Captured items skip the prefilter."""
    from datetime import UTC, datetime

    if file is not None:
        data = await file.read()
        if len(data) > MAX_PDF:
            raise HTTPException(413, "PDF larger than 20 MB")
        if not data.startswith(b"%PDF"):
            raise HTTPException(415, "only PDF uploads are supported")
        item = await capture_pdf(db, data, file.filename or "upload.pdf", intent=intent)
    elif url:
        if not url.startswith(("http://", "https://")):
            raise HTTPException(422, "url must be http(s)")
        from signal_core.sources.http import BlockedURL

        try:
            item = await capture_url(db, url, title=title, note=note, intent=intent)
        except BlockedURL as e:
            raise HTTPException(422, str(e)) from e
    elif text and text.strip():
        item = await capture_text(db, text, title=title, intent=intent)
    else:
        raise HTTPException(422, "send url, text or a PDF file")
    await screen_new_items(db, datetime.now(UTC))
    src = await db.get(Source, item.source_id)
    return item_out(item, src)


@router.get("/items/{iid}")
async def get_item(iid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    i = await db.get(Item, iid)
    if i is None:
        raise HTTPException(404, "item not found")
    return item_out(i, await db.get(Source, i.source_id))
