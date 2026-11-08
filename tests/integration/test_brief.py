"""M3 acceptance (backend): brief at configured TZ time, ≤ 7 diverse stories, catch-up, quiet day, habit, watches."""

from collections import Counter
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_api.main import create_app
from signal_core.brief.assemble import assemble
from signal_core.db.models import Brief, HabitDay, Item, Notification, Routine, StoryItem, WatchHit
from signal_core.demo import fixture_client, seed_fixture_sources
from signal_core.fixtures_corpus import labels
from signal_core.radar.jobs import ingest_all_due
from signal_core.radar.normalise import canonical_url
from signal_core.radar.pipeline import process
from signal_core.radar.watches import check_watches, create_watch

NOW = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)  # Fri 06:30 IST, before the 07:30 brief
EMAIL, PW = "owner@test.local", "correct horse battery"


async def prepare(db: AsyncSession) -> None:
    await seed_fixture_sources(db, include_broken=False)
    await db.commit()
    await ingest_all_due(NOW, fixture_client(NOW))
    await process(db, NOW)
    await db.commit()


async def story_event(db: AsyncSession, story_id: str) -> str:
    lab = {canonical_url(u): e for u, e in labels().items()}
    urls = (
        (
            await db.execute(
                select(Item.canonical_url)
                .join(StoryItem, StoryItem.item_id == Item.id)
                .where(StoryItem.story_id == story_id)
            )
        )
        .scalars()
        .all()
    )
    return Counter(lab[u] for u in urls).most_common(1)[0][0]


async def test_brief_has_at_most_7_diverse_stories_and_sections(seeded: AsyncSession) -> None:
    await prepare(seeded)
    b = await assemble(seeded, NOW + timedelta(hours=1))
    c = b.content
    assert 5 <= len(c["stories"]) <= 7 and c["kind"] == "daily"
    events = [await story_event(seeded, s["story_id"]) for s in c["stories"]]
    assert len(events) == len(set(events)), events  # diversity: never two stories about one event
    assert c["topline"] and c["post_suggestion"]["type"] == "post" and c["learn"]
    assert all(s["why_you"] and s["one_line"] and s["citations"] for s in c["stories"])
    assert all(s["score"] >= 0.55 for s in c["stories"] if not s["exploration"])
    assert c["quick_hits"] and isinstance(c["cards_due"], int)
    assert b.rendered_md.startswith("# Daily Brief")


async def test_second_brief_is_quiet_day_not_repeats(seeded: AsyncSession) -> None:
    await prepare(seeded)
    first = await assemble(seeded, NOW + timedelta(hours=1))
    first.opened_at = NOW + timedelta(hours=1)
    second = await assemble(seeded, NOW + timedelta(hours=2))
    shown = {s["story_id"] for s in first.content["stories"]}
    assert not shown & {s["story_id"] for s in second.content["stories"]}
    if not second.content["stories"]:
        assert second.content["quiet"]["message"].startswith("Quiet day")


async def test_catch_up_mode_after_two_days_away(seeded: AsyncSession) -> None:
    await prepare(seeded)
    b1 = await assemble(seeded, NOW)
    b1.opened_at = NOW
    await seeded.flush()
    later = NOW + timedelta(days=3)
    b2 = await assemble(seeded, later)
    assert b2.content["kind"] == "catchup" and b2.rendered_md.startswith("# While you were away")
    assert len(b2.content["stories"]) <= 10


async def test_brief_auto_generates_at_0730_ist(seeded: AsyncSession) -> None:
    from signal_scheduler.main import tick

    await prepare(seeded)
    for r in (await seeded.execute(select(Routine))).scalars():
        r.created_at, r.last_run_at = NOW - timedelta(days=1), NOW - timedelta(minutes=5)
    await seeded.commit()
    assert "daily_brief" not in await tick(datetime(2026, 11, 6, 1, 59, tzinfo=UTC))  # 07:29 IST
    assert (await seeded.execute(select(func.count()).select_from(Brief))).scalar_one() == 0
    assert "daily_brief" in await tick(datetime(2026, 11, 6, 2, 0, 5, tzinfo=UTC))  # 07:30 IST
    briefs = (await seeded.execute(select(Brief))).scalars().all()
    assert len(briefs) == 1 and briefs[0].kind == "daily" and briefs[0].content["stories"]


async def test_watch_triggers_on_fixture_event(seeded: AsyncSession) -> None:
    await prepare(seeded)
    w = await create_watch(
        seeded, "Tell me about prompt injection attacks on coding agents", urgency="instant"
    )
    other = await create_watch(seeded, "New cricket league schedules", urgency="digest")
    st = await check_watches(seeded, NOW + timedelta(minutes=5))
    assert st.hits >= 1 and st.notified >= 1
    hits = (await seeded.execute(select(WatchHit).where(WatchHit.watch_id == w.id))).scalars().all()
    assert hits
    for h in hits:
        assert await story_event(seeded, h.story_id) == "injection"
    assert not (await seeded.execute(select(WatchHit).where(WatchHit.watch_id == other.id))).scalars().all()
    n = (await seeded.execute(select(Notification).where(Notification.kind == "watch"))).scalars().all()
    assert n and "injection" in n[0].payload["title"].lower()
    b = await assemble(seeded, NOW + timedelta(minutes=10))
    assert any(x["watch"].startswith("Tell me about prompt injection") for x in b.content["watches"])


@pytest.fixture
async def client(seeded: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    from signal_api.routers.auth import _attempts

    _attempts.clear()
    await prepare(seeded)
    app = create_app()
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        r = await c.post("/auth/login", json={"email": EMAIL, "password": PW})
        c.headers["x-csrf-token"] = r.json()["csrf"]
        yield c


class _PinnedDatetime(datetime):
    @classmethod
    def now(cls, tz: object = None) -> "_PinnedDatetime":  # type: ignore[override]
        return cls.fromtimestamp((NOW + timedelta(hours=1)).timestamp(), tz=UTC)


async def test_completing_triage_marks_habit_day(
    client: httpx.AsyncClient, seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fixture corpus is dated NOW; pin the briefs router's clock so it stays inside the brief window.
    import signal_api.routers.briefs as briefs_router

    monkeypatch.setattr(briefs_router, "datetime", _PinnedDatetime)
    b = (await client.post("/briefs/generate", json={"kind": "daily"})).json()
    assert b["content"]["stories"]
    latest = (await client.get("/briefs/latest")).json()
    assert latest["id"] == b["id"]
    assert (await client.post(f"/briefs/{b['id']}/open")).status_code == 200
    r = (await client.post(f"/briefs/{b['id']}/complete", json={})).json()
    assert r["habit_day"]["mode"] in ("minimum", "full") and "brief" in r["habit_day"]["steps"]
    rows = (await seeded.execute(select(HabitDay))).scalars().all()
    assert len(rows) == 1
    a = (await client.post("/habit/mark", json={"step": "action"})).json()
    assert a["mode"] == "full"  # brief + action, no cards due yet
    today = (await client.get("/today")).json()
    assert today["habit"]["today"] == "full" and today["brief"]["id"] == b["id"]
    # A newer weekly review never replaces the daily brief on Today.
    seeded.add(
        Brief(kind="weekly", period_start=NOW, period_end=NOW, content={"kind": "weekly", "sections": []})
    )
    await seeded.commit()
    assert (await client.get("/today")).json()["brief"]["id"] == b["id"]


async def test_routines_api_validates_and_runs(client: httpx.AsyncClient) -> None:
    steps = (await client.get("/routines/steps")).json()
    assert {"score", "insights", "assemble_brief", "ingest_due_sources"} <= set(steps)
    bad = await client.post("/routines", json={"name": "x", "cron": "every day", "steps": ["score"]})
    assert bad.status_code == 422
    bad2 = await client.post("/routines", json={"name": "x", "cron": "0 9 * * 3", "steps": ["teleport"]})
    assert bad2.status_code == 422
    r = (
        await client.post(
            "/routines",
            json={
                "name": "Wednesday deep dive",
                "cron": "0 9 * * 3",
                "steps": ["score", "assemble_brief"],
                "params": {"max_stories": 3},
            },
        )
    ).json()
    assert r["next_run_at"]
    run = (await client.post(f"/routines/{r['id']}/run-now")).json()
    assert run["status"] == "ok" and run["outputs"]["assemble_brief"]["stories"] <= 3
    assert any(x["id"] == run["id"] for x in (await client.get("/runs")).json())


async def test_watches_api_and_onboarding(client: httpx.AsyncClient) -> None:
    w = (
        await client.post(
            "/watches", json={"query": "prompt injection in coding agents", "urgency": "instant"}
        )
    ).json()
    assert (await client.post("/watches/check")).json()["hits"] >= 1
    assert (await client.get(f"/watches/{w['id']}/hits")).json()
    assert (await client.get("/notifications")).json()[0]["kind"] == "watch"
    me = (await client.get("/me")).json()
    assert me["onboarded"] is False
    r = await client.post(
        "/onboarding/complete",
        json={
            "role": "Senior AI Engineer at VANCO",
            "goals": ["Ship production LLM systems"],
            "stack": ["python"],
            "skills": {"RAG & retrieval": 3},
            "daily_brief_cron": "45 7 * * 1-5",
        },
    )
    assert r.status_code == 200
    assert (await client.get("/me")).json()["onboarded"] is True
    routines = {x["name"]: x for x in (await client.get("/routines")).json()}
    assert routines["daily_brief"]["cron"] == "45 7 * * 1-5"
