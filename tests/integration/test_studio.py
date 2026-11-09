"""M4 acceptance: angles + graded drafts < 60 s, Ready gate, ask-me → raw bank, citations, repurpose → thread."""

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_api.main import create_app
from signal_core.db.models import Publication, RawMaterial, Story, StoryItem
from signal_core.demo import fixture_client, seed_fixture_sources
from signal_core.llm.mock import GENERATORS
from signal_core.radar.jobs import ingest_all_due
from signal_core.radar.pipeline import process

NOW = datetime.now(UTC) - timedelta(hours=2)  # relative: endpoints use the wall clock
EMAIL, PW = "owner@test.local", "correct horse battery"


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
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=120) as c,
    ):
        r = await c.post("/auth/login", json={"email": EMAIL, "password": PW})
        c.headers["x-csrf-token"] = r.json()["csrf"]
        yield c


async def nimbus_story(db: AsyncSession) -> Story:
    rows = (await db.execute(select(Story).where(Story.status == "active"))).scalars().all()
    for s in rows:
        n = (await db.execute(select(StoryItem).where(StoryItem.story_id == s.id))).scalars().all()
        if "Nimbus-4" in s.title and len(n) >= 3:
            return s
    raise AssertionError("fixture Nimbus-4 story missing")


async def test_story_to_graded_drafts_under_60s(client: httpx.AsyncClient, seeded: AsyncSession) -> None:
    story = await nimbus_story(seeded)
    t0 = time.monotonic()
    angles = (
        await client.post("/studio/angles", json={"seed_type": "story", "seed_id": str(story.id)})
    ).json()
    assert len(angles) >= 3 and len({a["angle_type"] for a in angles}) == len(angles)
    practitioner = next(a for a in angles if not a["needs_input"])
    drafts = (
        await client.post(
            "/studio/drafts", json={"content_idea_id": practitioner["id"], "platforms": ["linkedin", "x"]}
        )
    ).json()
    elapsed = time.monotonic() - t0
    assert elapsed < 60, elapsed
    li = next(d for d in drafts if d["platform"] == "linkedin")
    cur = li["current"]
    assert cur["grade"]["total"] > 0 and set(cur["grade"]["scores"]) >= {"Hook", "Rhythm", "Ending"}
    assert cur["aitell"]["counters"]["words"] > 0
    full = (await client.get(f"/studio/drafts/{li['id']}")).json()
    assert {v["label"] for v in full["versions"]} >= {"A", "B"}  # story-led + short question-led
    # Every sentence that states a fact has a resolvable citation.
    assert cur["factcheck"]["uncited_sentences"] == [] and cur["factcheck"]["unknown_source_ids"] == []
    assert cur["claims"] and all(c["source_ids"] for c in cur["claims"])
    assert li["post_within_24h"] is True  # news-reactive


async def test_banned_phrase_or_unsupported_claim_blocks_ready(
    client: httpx.AsyncClient, seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signal_core.llm.mock_generators import writer

    def sloppy(inputs):  # type: ignore[no-untyped-def]
        out = writer(inputs)
        sid = inputs["sources"][0]["id"]
        out["versions"][0]["body"] = (
            "Here's the thing: this is a game-changer.\n\nNimbus-4 costs $1 per million "
            "tokens and beats every model.\n\nWhat do you think?"
        )
        out["versions"] = out["versions"][:1]
        out["claims"] = [
            {"sentence": "Nimbus-4 costs $1 per million tokens and beats every model.", "source_ids": [sid]}
        ]
        return out

    monkeypatch.setitem(GENERATORS, "writer", sloppy)
    story = await nimbus_story(seeded)
    angles = (
        await client.post("/studio/angles", json={"seed_type": "story", "seed_id": str(story.id)})
    ).json()
    idea = next(a for a in angles if not a["needs_input"])
    d = (
        await client.post("/studio/drafts", json={"content_idea_id": idea["id"], "platforms": ["linkedin"]})
    ).json()[0]
    gate = d["current"]["gate"]
    assert any("Banned phrase" in g for g in gate) and any("Unsupported claim" in g for g in gate)
    r = await client.post(f"/studio/drafts/{d['id']}/approve", json={})
    assert r.status_code == 409 and r.json()["detail"]["reasons"]
    r2 = await client.post(
        f"/studio/drafts/{d['id']}/approve", json={"override_reason": "I checked the number myself"}
    )
    assert r2.status_code == 200 and r2.json()["status"] == "ready"
    assert r2.json()["override"]["reason"] == "I checked the number myself"


async def test_ask_me_answers_saved_to_raw_bank(client: httpx.AsyncClient, seeded: AsyncSession) -> None:
    story = await nimbus_story(seeded)
    angles = (
        await client.post("/studio/angles", json={"seed_type": "story", "seed_id": str(story.id)})
    ).json()
    personal = next(a for a in angles if a["needs_input"])
    d = (
        await client.post(
            "/studio/drafts", json={"content_idea_id": personal["id"], "platforms": ["linkedin"]}
        )
    ).json()[0]
    assert d["pending_questions"] and d["current"] is None
    q = d["pending_questions"][0]["question"]
    answer = "Last month our team cut RAG latency by 40% after moving retrieval to Postgres"
    r = (await client.post(f"/studio/drafts/{d['id']}/answer", json={"answers": {q: answer}})).json()
    rows = (await seeded.execute(select(RawMaterial).where(RawMaterial.origin == "ask_me"))).scalars().all()
    assert [x.text for x in rows] == [answer]
    claims = r["current"]["claims"]
    assert any(cid == f"r:{rows[0].id}" for c in claims for cid in c["source_ids"])
    assert answer.split(" after")[0] in r["current"]["body"]
    assert r["current"]["factcheck"]["uncited_sentences"] == []


async def test_skipping_questions_means_no_personal_claims(
    client: httpx.AsyncClient, seeded: AsyncSession
) -> None:
    story = await nimbus_story(seeded)
    angles = (
        await client.post("/studio/angles", json={"seed_type": "story", "seed_id": str(story.id)})
    ).json()
    personal = next(a for a in angles if a["needs_input"])
    d = (
        await client.post(
            "/studio/drafts", json={"content_idea_id": personal["id"], "platforms": ["linkedin"]}
        )
    ).json()[0]
    r = (await client.post(f"/studio/drafts/{d['id']}/answer", json={"skip": True})).json()
    assert not any(cid.startswith("r:") for c in r["current"]["claims"] for cid in c["source_ids"])


async def test_repurpose_linkedin_to_x_thread_and_publish(
    client: httpx.AsyncClient, seeded: AsyncSession
) -> None:
    story = await nimbus_story(seeded)
    angles = (
        await client.post("/studio/angles", json={"seed_type": "story", "seed_id": str(story.id)})
    ).json()
    idea = next(a for a in angles if not a["needs_input"])
    li = (
        await client.post("/studio/drafts", json={"content_idea_id": idea["id"], "platforms": ["linkedin"]})
    ).json()[0]
    th = (await client.post(f"/studio/drafts/{li['id']}/repurpose", json={"platform": "x_thread"})).json()
    posts = th["current"]["thread"]
    assert th["parent_draft_id"] == li["id"] and th["format"] == "thread"
    assert 4 <= len(posts) <= 10 and all(len(p) <= 280 for p in posts)
    li_sources = {s for c in li["current"]["claims"] for s in c["source_ids"]}
    th_sources = {s for c in th["current"]["claims"] for s in c["source_ids"]}
    assert th_sources and th_sources <= li_sources  # same facts, native format
    assert th["current"]["body"] != li["current"]["body"]
    # Approve → publish-assist → mark published
    ap = await client.post(f"/studio/drafts/{li['id']}/approve", json={})
    assert ap.status_code == 200, ap.json()
    pa = (await client.get(f"/studio/drafts/{li['id']}/publish-assist")).json()
    assert pa["text"] and pa["composer_url"].startswith("https://www.linkedin.com/")
    r = await client.post(
        f"/studio/drafts/{li['id']}/published", json={"url": "https://www.linkedin.com/posts/x-1"}
    )
    assert r.status_code == 200 and r.json()["draft"]["status"] == "published"
    pub = (await seeded.execute(select(Publication))).scalars().one()
    assert pub.variables["format"] == "post" and pub.embedding is not None
    board = (await client.get("/studio/board")).json()
    assert any(x["id"] == li["id"] for x in board["published"])


async def test_human_edit_reenters_gate(client: httpx.AsyncClient, seeded: AsyncSession) -> None:
    story = await nimbus_story(seeded)
    angles = (
        await client.post("/studio/angles", json={"seed_type": "story", "seed_id": str(story.id)})
    ).json()
    idea = next(a for a in angles if not a["needs_input"])
    d = (
        await client.post("/studio/drafts", json={"content_idea_id": idea["id"], "platforms": ["linkedin"]})
    ).json()[0]
    assert (await client.post(f"/studio/drafts/{d['id']}/approve", json={})).status_code == 200
    e = (
        await client.put(
            f"/studio/drafts/{d['id']}", json={"body": d["current"]["body"] + "\n\nLet that sink in."}
        )
    ).json()
    assert e["status"] == "drafting" and e["current"]["author"] == "human"
    assert any("Let that sink in" in g for g in e["current"]["gate"])


async def test_raw_bank_reference_posts_series_calendar(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/raw-materials", json={"kind": "number", "text": "We serve 40 clients from one Postgres"}
    )
    assert r.status_code == 201
    for i in range(5):
        x = (
            await client.post(
                "/reference-posts", json={"text": f"Old post number {i} about shipping things fast."}
            )
        ).json()
    assert x["voice_calibrated"] is True
    s = await client.post(
        "/series", json={"name": "Build Log Friday", "platform": "linkedin", "cadence": "0 9 * * 5"}
    )
    assert s.status_code == 201
    cal = (await client.get("/calendar")).json()
    assert cal["goals"]["linkedin"]["goal"] == 3 and cal["series"][0]["name"] == "Build Log Friday"
