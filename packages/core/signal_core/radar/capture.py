"""Capture from anywhere (§11.2): URL, pasted text, PDF. Captures skip the prefilter and get a relevance boost.

A capture is a user-directed fetch of one page (like opening it in a browser), so robots.txt is not applied
(ADR-013); the generic User-Agent is still used. Target < 5 s end to end: the page fetch has a 4 s timeout and
the item is created even if the fetch fails (text filled from what the user supplied).
"""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from typing import Literal

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import Item, Source
from signal_core.radar.ingest import IngestStats, store_entries
from signal_core.radar.normalise import canonical_url, url_hash
from signal_core.sources.base import RawEntry
from signal_core.sources.http import PoliteClient

Intent = Literal["read_later", "post", "build", "learn"]
CAPTURE_SOURCE = "Manual capture"


async def capture_source(session: AsyncSession) -> Source:
    s = (await session.execute(select(Source).where(Source.type == "capture"))).scalars().first()
    if s is None:
        s = Source(type="capture", name=CAPTURE_SOURCE, tier=2, ring="core", fetch_every=1440)
        session.add(s)
        await session.flush()
    return s


async def _existing(session: AsyncSession, url: str) -> Item | None:
    return (await session.execute(select(Item).where(Item.url_hash == url_hash(url)))).scalars().first()


async def capture_url(
    session: AsyncSession,
    url: str,
    *,
    title: str | None = None,
    note: str | None = None,
    intent: Intent | None = None,
    http: PoliteClient | None = None,
) -> Item:
    existing = await _existing(session, url)
    if existing is not None:  # already known: mark it captured (relevance boost) instead of duplicating
        existing.is_capture = True
        existing.capture_intent = intent or existing.capture_intent
        if existing.status in ("prefiltered_out", "archived"):
            existing.status = "new"
        await session.flush()
        return existing
    html, fetched_title = "", None
    client = http or PoliteClient(retries=0, timeout_s=4.0)
    if client.guard:
        from signal_core.sources.http import assert_public_url

        await assert_public_url(url)  # raises BlockedURL → 422 at the API
    try:
        r = await client.get(url, timeout=4.0)
        if r.status_code == 200 and "html" in r.headers.get("content-type", "html"):
            html = r.text
            import re

            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
            fetched_title = m.group(1).strip() if m else None
        elif r.status_code == 200 and "pdf" in r.headers.get("content-type", ""):
            html = "<p>" + pdf_text(r.content) + "</p>"
    except Exception:
        html = ""
    finally:
        if http is None:
            await client.aclose()
    src = await capture_source(session)
    entry = RawEntry(
        external_id=f"capture:{url_hash(url)[:24]}",
        url=url,
        title=title or fetched_title or canonical_url(url),
        published_at=datetime.now(UTC),
        summary=note or "",
        content_html=html,
        raw={"note": note},
    )
    stats = await store_entries(
        session, src, [entry], datetime.now(UTC), is_capture=True, capture_intent=intent
    )
    return await _item_from(session, stats, url)


async def capture_text(
    session: AsyncSession, text: str, *, title: str | None = None, intent: Intent | None = None
) -> Item:
    digest = hashlib.sha256(text.encode()).hexdigest()[:24]
    url = f"https://signal.local/note/{digest}"
    src = await capture_source(session)
    entry = RawEntry(
        external_id=f"capture-text:{digest}",
        url=url,
        title=title or text.strip().split("\n", 1)[0][:120],
        published_at=datetime.now(UTC),
        summary=text,
        content_type_hint="post",
    )
    stats = await store_entries(
        session, src, [entry], datetime.now(UTC), is_capture=True, capture_intent=intent
    )
    return await _item_from(session, stats, url)


def pdf_text(data: bytes, max_pages: int = 40) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:max_pages]).strip()


async def capture_pdf(
    session: AsyncSession, data: bytes, filename: str, *, intent: Intent | None = None
) -> Item:
    digest = hashlib.sha256(data).hexdigest()[:24]
    url = f"https://signal.local/pdf/{digest}/{filename}"
    txt = pdf_text(data)
    src = await capture_source(session)
    entry = RawEntry(
        external_id=f"capture-pdf:{digest}",
        url=url,
        title=filename.rsplit(".", 1)[0],
        published_at=datetime.now(UTC),
        summary=txt,
        content_type_hint="paper",
    )
    stats = await store_entries(
        session, src, [entry], datetime.now(UTC), is_capture=True, capture_intent=intent
    )
    return await _item_from(session, stats, url)


async def _item_from(session: AsyncSession, stats: IngestStats, url: str) -> Item:
    item = await _existing(session, url)
    if item is None:
        raise RuntimeError(f"capture failed to create an item ({stats})")
    return item
