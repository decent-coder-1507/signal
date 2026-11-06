"""OPML import (§13 POST /sources/import-opml)."""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as DET
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import Source


@dataclass
class OpmlFeed:
    title: str
    url: str
    category: str | None


def parse_opml(xml: str) -> list[OpmlFeed]:
    root = DET.fromstring(xml, forbid_dtd=True)  # defusedxml: no DTDs, entities or external refs
    out: list[OpmlFeed] = []

    def walk(node: Element, cat: str | None) -> None:
        for o in node.findall("outline"):
            url = o.get("xmlUrl")
            label = o.get("title") or o.get("text") or url or ""
            if url:
                out.append(OpmlFeed(label.strip(), url.strip(), cat))
            else:
                walk(o, label or cat)

    body = root.find("body")
    if body is None:
        raise ValueError("not an OPML document (no <body>)")
    walk(body, None)
    return out


async def import_opml(session: AsyncSession, xml: str, tier: int = 2, ring: str = "core") -> dict[str, int]:
    feeds = parse_opml(xml)
    existing_urls = {s.url for s in (await session.execute(select(Source))).scalars()}
    existing_names = {s.name for s in (await session.execute(select(Source))).scalars()}
    added = 0
    for f in feeds:
        if f.url in existing_urls:
            continue
        name = f.title or f.url
        while name in existing_names:
            name += " (OPML)"
        session.add(
            Source(
                type="rss",
                name=name,
                url=f.url,
                tier=tier,
                ring=ring,
                fetch_every=120,
                topics=[f.category] if f.category else [],
                terms_note="imported from OPML",
            )
        )
        existing_urls.add(f.url)
        existing_names.add(name)
        added += 1
    await session.flush()
    return {"found": len(feeds), "added": added}
