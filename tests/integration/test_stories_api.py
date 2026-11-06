from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy.ext.asyncio import AsyncSession

from signal_api.main import create_app
from signal_core.demo import fixture_client, seed_fixture_sources
from signal_core.radar.jobs import ingest_all_due
from signal_core.radar.pipeline import process

EMAIL, PW = "owner@test.local", "correct horse battery"
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
async def client(seeded: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    from signal_api.routers.auth import _attempts

    _attempts.clear()
    await seed_fixture_sources(seeded, include_broken=False)
    await seeded.commit()
    await ingest_all_due(NOW, fixture_client(NOW))
    await process(seeded, NOW)
    await seeded.commit()
    app = create_app()
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        r = await c.post("/auth/login", json={"email": EMAIL, "password": PW})
        c.headers["x-csrf-token"] = r.json()["csrf"]
        yield c


async def test_list_paginates_and_filters(client: httpx.AsyncClient) -> None:
    page1 = (await client.get("/stories?limit=5")).json()
    assert len(page1["items"]) == 5 and page1["next_cursor"]
    page2 = (await client.get(f"/stories?limit=5&cursor={page1['next_cursor']}")).json()
    assert not {s["id"] for s in page1["items"]} & {s["id"] for s in page2["items"]}
    scores = [s["final_score"] for s in page1["items"] + page2["items"]]
    assert scores == sorted(scores, reverse=True)
    adj = (await client.get("/stories?ring=adjacent&include_excluded=true")).json()["items"]
    assert adj and all(s["ring"] == "adjacent" for s in adj)


async def test_story_page_has_timeline_insight_citations_and_why(client: httpx.AsyncClient) -> None:
    top = (await client.get("/stories?limit=20")).json()["items"]
    multi = next(s for s in top if len(s["sources"]) >= 3)
    page = (await client.get(f"/stories/{multi['id']}")).json()
    assert page["insight"]["what_happened"] and page["insight"]["citations"]
    tl = page["timeline"]
    assert len(tl) >= 3 and tl[0]["label"] == "first reported"
    assert {c["id"] for c in page["insight"]["citations"]} >= {t["item_id"] for t in tl}
    assert set(page["why"]["sub_scores"]) == {
        "relevance",
        "impact",
        "signal",
        "novelty",
        "credibility",
        "durability",
        "actionability",
        "learned",
    }


async def test_follow_regenerate_and_feedback(client: httpx.AsyncClient) -> None:
    sid = (await client.get("/stories?limit=1")).json()["items"][0]["id"]
    assert (await client.post(f"/stories/{sid}/follow")).json() == {"followed": True}
    v1 = (await client.get(f"/stories/{sid}")).json()["insight"]["version"]
    v2 = (await client.post(f"/stories/{sid}/regenerate-insight")).json()["insight"]["version"]
    assert v2 == v1 + 1
    r = (
        await client.post("/feedback", json={"target_type": "story", "target_id": sid, "kind": "more"})
    ).json()
    assert r["ok"] and r["topic_nudges"]  # bounded nudge on the story's topics
    w = await client.post(
        "/feedback",
        json={
            "target_type": "story",
            "target_id": sid,
            "kind": "wrong",
            "context": {"note": "number is off"},
        },
    )
    assert w.status_code == 201
    bad = await client.post("/feedback", json={"target_type": "story", "target_id": sid, "kind": "meh"})
    assert bad.status_code == 422


async def test_topic_nudges_are_bounded(client: httpx.AsyncClient) -> None:
    sid = (await client.get("/stories?limit=1")).json()["items"][0]["id"]
    for _ in range(12):
        r = (
            await client.post("/feedback", json={"target_type": "story", "target_id": sid, "kind": "more"})
        ).json()
    assert all(abs(v) <= 0.2 + 1e-9 for v in r["topic_nudges"].values())
    assert max(r["topic_nudges"].values()) == pytest.approx(0.2)
