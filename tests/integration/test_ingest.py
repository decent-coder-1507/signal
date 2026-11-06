"""M1 acceptance: idempotent ingest, near-dup recall, broken-source flagging, HN merge, prefilter."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import FetchLog, Item, Source
from signal_core.demo import fixture_client, seed_fixture_sources
from signal_core.fixtures_corpus import ITEMS, SYND_ITEMS
from signal_core.radar.ingest import ingest_source
from signal_core.radar.jobs import ingest_all_due
from signal_core.radar.normalise import canonical_url

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


async def _setup(db: AsyncSession) -> None:
    await seed_fixture_sources(db)
    await db.commit()


async def _count(db: AsyncSession, *where) -> int:  # type: ignore[no-untyped-def]
    return int((await db.execute(select(func.count()).select_from(Item).where(*where))).scalar_one())


async def test_ingest_is_idempotent(seeded: AsyncSession) -> None:
    await _setup(seeded)
    c = fixture_client(NOW)
    first = await ingest_all_due(NOW, c)
    n1 = await _count(seeded)
    assert n1 == len(ITEMS) + len(SYND_ITEMS)
    # Second run (sources due again later) adds 0 items.
    second = await ingest_all_due(NOW + timedelta(hours=2), fixture_client(NOW))
    assert await _count(seeded) == n1
    assert sum(r["new"] for r in second) == 0
    assert sum(r["new"] for r in first) == n1


async def test_near_duplicate_recall_and_precision(seeded: AsyncSession) -> None:
    await _setup(seeded)
    await ingest_all_due(NOW, fixture_client(NOW))
    synd_urls = {canonical_url(i.url) for i in SYND_ITEMS}
    rows = (await seeded.execute(select(Item.canonical_url, Item.status))).all()
    detected = sum(1 for u, st in rows if u in synd_urls and st == "duplicate")
    recall = detected / len(SYND_ITEMS)
    false_pos = [u for u, st in rows if u not in synd_urls and st == "duplicate"]
    assert recall >= 0.95, f"near-dup recall {recall:.2%}"
    assert false_pos == []


async def test_duplicates_point_at_their_original(seeded: AsyncSession) -> None:
    await _setup(seeded)
    await ingest_all_due(NOW, fixture_client(NOW))
    by_url = {i.canonical_url: i for i in (await seeded.execute(select(Item))).scalars()}
    for synd in SYND_ITEMS:
        dup = by_url[canonical_url(synd.url)]
        orig = by_url[canonical_url(str(synd.meta["syndicated_from"]))]
        assert dup.duplicate_of == orig.id


async def test_broken_source_flagged_after_three_failures(seeded: AsyncSession) -> None:
    await _setup(seeded)
    broken = (await seeded.execute(select(Source).where(Source.name == "Fixture: Broken feed"))).scalar_one()
    for k in range(3):
        st = await ingest_source(seeded, broken.id, fixture_client(NOW), NOW + timedelta(hours=k))
        assert st.status == "error"
        flagged = (broken.health or {}).get("flagged")
        assert (flagged is None) == (k < 2)
    assert "fix or disable" in broken.health["flagged"]
    logs = (
        await seeded.execute(
            select(func.count()).select_from(FetchLog).where(FetchLog.source_id == broken.id)
        )
    ).scalar_one()
    assert logs == 3


async def test_zero_items_for_seven_days_is_flagged(seeded: AsyncSession) -> None:
    from signal_core.radar.ingest import update_health

    s = Source(type="rss", name="quiet", url="https://q.example/feed", health={})
    update_health(s, True, 5, NOW)
    update_health(s, True, 0, NOW + timedelta(days=3))
    assert s.health["flagged"] is None
    update_health(s, True, 0, NOW + timedelta(days=8))
    assert "no new items" in s.health["flagged"]


async def test_failed_source_does_not_block_others(seeded: AsyncSession) -> None:
    await _setup(seeded)
    res = await ingest_all_due(NOW, fixture_client(NOW))
    statuses = {r["source"]: r["status"] for r in res}
    assert statuses["Fixture: Broken feed"] == "error"
    assert statuses["Fixture: Official blogs"] == "ok"


async def test_hn_signal_merges_into_official_item(seeded: AsyncSession) -> None:
    await _setup(seeded)
    await ingest_all_due(NOW, fixture_client(NOW))
    official = (
        await seeded.execute(
            select(Item).where(Item.canonical_url == "https://nimbus.example/blog/introducing-nimbus-4")
        )
    ).scalar_one()
    assert official.signal_meta["hn_points"] == 812
    low = await _count(seeded, Item.title.like("Show HN%"))
    assert low == 0  # below min_points


async def test_noise_prefiltered_and_relevant_items_pass(seeded: AsyncSession) -> None:
    await _setup(seeded)
    await ingest_all_due(NOW, fixture_client(NOW))
    rows = {i.title: i for i in (await seeded.execute(select(Item))).scalars()}
    for t in (
        "Celebrity chef opens third restaurant",
        "Crypto price prediction: analysts expect volatile week",
        "Best phone cases of the year",
    ):
        assert rows[t].status == "prefiltered_out"
    for t in (
        "Introducing Nimbus-4",
        "Agent Context Protocol 1.1 released",
        "Verifier Loops for Grounded Retrieval-Augmented Generation",
    ):
        assert rows[t].status == "new" and rows[t].prefilter_score >= 0.25
    # every non-duplicate item has an embedding (needed for clustering)
    assert await _count(seeded, Item.embedding.is_(None)) == 0


async def test_ingest_step_reports_counts(seeded: AsyncSession) -> None:
    from signal_core.routines.engine import STEPS, StepContext, load_step_modules

    await _setup(seeded)
    load_step_modules()
    from signal_core.db.models import Routine, Run

    r = Routine(name="x", cron="*/30 * * * *", steps=["ingest_due_sources"], channels=[])
    run = Run(name="x", started_at=NOW)
    out = await STEPS["ingest_due_sources"](StepContext(seeded, r, run, NOW, {}))
    assert out["new_items"] == len(ITEMS) + len(SYND_ITEMS)
    assert out["errors"] == ["Fixture: Broken feed"]
