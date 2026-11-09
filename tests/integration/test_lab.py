"""M6 acceptance: ≤ 1 spark only above threshold; product ideas have ≥ 2 evidence links; brief zip has BRIEF.md +
CLAUDE.md; a build-log entry seeds a STUDIO draft that uses only log facts; capacity guard; kill needs a reason."""

import io
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_api.main import create_app
from signal_core.brief.assemble import assemble
from signal_core.config import get_config
from signal_core.db.models import Idea, IdeaEvidence
from signal_core.demo import fixture_client, seed_fixture_sources
from signal_core.lab.service import detect_sparks
from signal_core.llm.mock import GENERATORS
from signal_core.radar.jobs import ingest_all_due
from signal_core.radar.pipeline import process

NOW = datetime.now(UTC) - timedelta(hours=2)  # relative: endpoints use the wall clock
EMAIL, PW = "owner@test.local", "correct horse battery"


async def prepare(db: AsyncSession) -> None:
    await seed_fixture_sources(db, include_broken=False)
    await db.commit()
    await ingest_all_due(NOW, fixture_client(NOW))
    await process(db, NOW)
    await db.commit()


async def test_sparks_have_evidence_and_brief_shows_at_most_one(seeded: AsyncSession) -> None:
    await prepare(seeded)
    ideas = await detect_sparks(seeded, NOW)
    assert 1 <= len(ideas) <= 3
    for i in ideas:
        ev = (await seeded.execute(select(IdeaEvidence).where(IdeaEvidence.idea_id == i.id))).scalars().all()
        assert ev and len(ev) == len(i.evidence)
        assert 0 < i.lab_score <= 10
    b = await assemble(seeded, NOW + timedelta(minutes=30))
    spark = b.content["build_spark"]
    assert spark is not None and spark["lab_score"] >= get_config().scoring.lab_spark_threshold
    assert spark["idea_id"] == str(max(ideas, key=lambda x: x.lab_score).id)


async def test_no_spark_below_threshold(seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await prepare(seeded)
    await detect_sparks(seeded, NOW)
    monkeypatch.setattr(get_config().scoring, "lab_spark_threshold", 9.9)
    b = await assemble(seeded, NOW + timedelta(minutes=30))
    assert b.content["build_spark"] is None


async def test_product_ideas_need_two_independent_signals(
    seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signal_core.llm.mock_generators import spark_detect

    def products(inputs):  # type: ignore[no-untyped-def]
        out = spark_detect(inputs)
        s = inputs["stories"]
        base = out["ideas"][0]
        one = {
            **base,
            "type": "product",
            "title": "One-signal product",
            "evidence": [{"ref": s[0]["id"], "why": "x"}],
        }
        two = {
            **base,
            "type": "product",
            "title": "Two-signal product",
            "evidence": [
                {"ref": s[0]["id"], "why": "x"},
                {"ref": s[1]["id"], "why": "y"},
                {"ref": "not-a-real-id", "why": "hallucinated"},
            ],
        }
        return {"ideas": [one, two]}

    monkeypatch.setitem(GENERATORS, "spark_detect", products)
    await prepare(seeded)
    ideas = {i.title: i for i in await detect_sparks(seeded, NOW)}
    assert ideas["One-signal product"].type == "experiment"  # downgraded
    assert ideas["Two-signal product"].type == "product"
    assert len(ideas["Two-signal product"].evidence) == 2  # the hallucinated ref was dropped


@pytest.fixture
async def client(seeded: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    from signal_api.routers.auth import _attempts

    _attempts.clear()
    await prepare(seeded)
    app = create_app()
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=120) as c,
    ):
        r = await c.post("/auth/login", json={"email": EMAIL, "password": PW})
        c.headers["x-csrf-token"] = r.json()["csrf"]
        yield c


async def test_build_brief_zip(client: httpx.AsyncClient) -> None:
    ideas = (await client.post("/lab/sparks/detect")).json()
    iid = ideas[0]["id"]
    page = (await client.get(f"/ideas/{iid}")).json()
    assert page["evidence_links"] and all(e["url"].startswith("https://") for e in page["evidence_links"])
    b = (await client.post(f"/ideas/{iid}/brief")).json()
    assert {"BRIEF.md", "CLAUDE.md"} <= set(b["files"])
    r = await client.get(f"/ideas/{iid}/brief.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert any(n.endswith("/BRIEF.md") for n in names) and any(n.endswith("/CLAUDE.md") for n in names)
    brief = (
        zipfile.ZipFile(io.BytesIO(r.content)).read(next(n for n in names if n.endswith("BRIEF.md"))).decode()
    )
    for section in ("## Goal", "## Acceptance criteria", "## Milestones", "## Test plan", "## Evidence"):
        assert section in brief
    assert page["evidence_links"][0]["url"] in brief


async def test_build_log_seeds_draft_with_only_log_facts(client: httpx.AsyncClient) -> None:
    idea = (
        await client.post(
            "/ideas",
            json={
                "type": "poc",
                "title": "Tiny MCP server for internal docs",
                "one_liner": "Expose docs to an agent",
            },
        )
    ).json()
    await client.post(
        f"/ideas/{idea['id']}/logs", json={"text": "Day 1: built the server in 212 lines of Python."}
    )
    await client.post(
        f"/ideas/{idea['id']}/logs",
        json={"text": "Day 2: streaming broke with large files; fixed by chunking at 64 KB."},
    )
    angles = (
        await client.post("/studio/angles", json={"seed_type": "build_log", "seed_id": idea["id"]})
    ).json()
    a = next(x for x in angles if not x["needs_input"])
    d = (
        await client.post("/studio/drafts", json={"content_idea_id": a["id"], "platforms": ["linkedin"]})
    ).json()[0]
    cur = d["current"]
    ids = {sid for c in cur["claims"] for sid in c["source_ids"]}
    assert ids == {f"log:{idea['id']}"}  # the build log is the only source of facts
    assert cur["factcheck"]["unsupported"] == [] and cur["factcheck"]["uncited_sentences"] == []
    assert "212 lines" in cur["body"] or "64 KB" in cur["body"]


async def test_status_flow_kill_reason_and_capacity_guard(client: httpx.AsyncClient) -> None:
    mk = [(await client.post("/ideas", json={"type": "poc", "title": f"Idea {k}"})).json() for k in range(3)]
    assert (await client.post(f"/ideas/{mk[0]['id']}/status", json={"status": "killed"})).status_code == 422
    r = await client.post(
        f"/ideas/{mk[0]['id']}/status", json={"status": "killed", "kill_reason": "prior art too strong"}
    )
    assert r.json()["status"] == "killed"
    for i in mk[1:]:
        assert (await client.post(f"/ideas/{i['id']}/status", json={"status": "building"})).status_code == 200
    third = (await client.post("/ideas", json={"type": "poc", "title": "Third"})).json()
    r = await client.post(f"/ideas/{third['id']}/status", json={"status": "building"})
    assert r.status_code == 422 and "capacity guard" in r.json()["detail"]
    sparks = (await client.post("/lab/sparks/detect")).json()
    assert sparks and all(s["type"] == "practical" for s in sparks)  # only practicals while 2+ are building


async def test_prior_art_is_listed(seeded: AsyncSession) -> None:
    await prepare(seeded)
    ideas = await detect_sparks(seeded, NOW)
    with_pa = [i for i in ideas if i.prior_art]
    assert with_pa and all(pa["url"].startswith("https://") for i in with_pa for pa in i.prior_art)
    _ = Idea


async def test_build_action_turns_a_story_into_a_lab_idea(client: httpx.AsyncClient) -> None:
    sid = (await client.get("/stories?limit=1")).json()["items"][0]["id"]
    ideas = (await client.post(f"/stories/{sid}/build")).json()
    assert ideas and all(i["status"] == "shortlisted" for i in ideas)
    detail = (await client.get(f"/ideas/{ideas[0]['id']}")).json()
    assert detail["evidence"]  # grounded in the story, never invented
    assert (await client.post("/stories/00000000-0000-7000-8000-000000000000/build")).status_code == 404
