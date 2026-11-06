"""Demo/fixture data loader for mock mode and e2e (`seed --demo`). Grows with each milestone."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import Source
from signal_core.db.session import session_scope
from signal_core.fixtures_corpus import FIXTURE_SOURCES, FixtureTransport, build
from signal_core.sources.http import PoliteClient


async def seed_fixture_sources(session: AsyncSession, include_broken: bool = True) -> list[Source]:
    existing = {s.name: s for s in (await session.execute(select(Source))).scalars()}
    out = []
    for fs in FIXTURE_SOURCES:
        if fs["key"] == "broken" and not include_broken:
            continue
        s = existing.get(str(fs["name"]))
        if s is None:
            params = {k: v for k, v in fs.items() if k not in ("type", "name", "url", "tier", "ring", "key")}
            s = Source(
                type=str(fs["type"]),
                name=str(fs["name"]),
                url=str(fs["url"]) if fs.get("url") else None,
                tier=int(str(fs.get("tier", 2))),
                ring=str(fs.get("ring", "core")),
                fetch_every=30,
                params={**params, "fixture": True, "fixture_key": fs["key"]},
                terms_note="mock-mode fixture source",
            )
            session.add(s)
        out.append(s)
    await session.flush()
    return out


def fixture_client(base: datetime | None = None) -> PoliteClient:
    return PoliteClient(
        transport=FixtureTransport(build(base or datetime.now(UTC))),
        per_host_interval_s=0,
        retries=0,
        backoff_s=0,
    )


async def load_demo(now: datetime | None = None) -> dict[str, Any]:
    from signal_core.radar.jobs import ingest_all_due

    now = now or datetime.now(UTC)
    async with session_scope() as s:
        await seed_fixture_sources(s, include_broken=False)
    client = fixture_client(now)
    try:
        results = await ingest_all_due(now, client)
    finally:
        await client.aclose()
    out: dict[str, Any] = {"ingest": {"sources": len(results), "new": sum(r["new"] for r in results)}}
    try:  # later milestones extend the demo pipeline (enrich → cluster → score → brief …)
        from signal_core.demo_pipeline import run_demo_pipeline

        out.update(await run_demo_pipeline(now))
    except ModuleNotFoundError as e:
        if e.name != "signal_core.demo_pipeline":
            raise
    return out
