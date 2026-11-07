"""M7 acceptance: learn-next 3 items with cited reasons; explainer generates cards; FSRS scheduling through the API;
Moat Radar monthly report renders with evidence links; quiz updates ratings; predictions scorecard."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_api.main import create_app
from signal_core.db.models import Card, Prediction, Skill, SkillEvent
from signal_core.demo import fixture_client, seed_fixture_sources
from signal_core.radar.jobs import ingest_all_due
from signal_core.radar.pipeline import process

NOW = datetime.now(UTC) - timedelta(hours=2)
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


async def test_skill_tree_and_self_rating(client: httpx.AsyncClient, seeded: AsyncSession) -> None:
    tree = (await client.get("/skills")).json()
    names = {d["name"] for d in tree}
    assert {"Software fundamentals", "AI engineering", "ML foundations"} <= names
    ai = next(d for d in tree if d["name"] == "AI engineering")
    rag = next(c for c in ai["children"] if c["name"] == "RAG & retrieval")
    r = (await client.put(f"/skills/{rag['id']}", json={"current_level": 3})).json()
    assert r["current_level"] == 3
    ev = (await seeded.execute(select(SkillEvent).where(SkillEvent.kind == "self"))).scalars().all()
    assert ev and ev[0].delta == 2


async def test_learn_next_three_items_with_cited_reasons(client: httpx.AsyncClient) -> None:
    ln = (await client.get("/gym/learn-next")).json()
    items = ln["items"]
    assert len(items) == 3
    for it in items:
        assert it["skill"] and it["why"] and it["plan"]["explainer_topic"] and it["plan"]["done_definition"]
        for e in it["evidence"]:
            assert f"[{e['id']}]" in it["why"]  # cited reasons resolve to stored stories
    assert any(it["evidence"] for it in items)
    assert ln["ignore"]


async def test_explainer_generates_cards_and_is_cached(
    client: httpx.AsyncClient, seeded: AsyncSession
) -> None:
    ex = (await client.post("/explainers", json={"topic": "RAG & retrieval", "depth": "engineer"})).json()
    assert "```python" in ex["body"] and "connects to" in ex["body"].lower()
    assert 3 <= len(ex["cards"]) <= 5
    again = (await client.post("/explainers", json={"topic": "RAG & retrieval", "depth": "engineer"})).json()
    assert again["id"] == ex["id"] and len(again["cards"]) == len(ex["cards"])  # cached, no duplicate cards
    plain = (await client.post("/explainers", json={"topic": "RAG & retrieval", "depth": "plain"})).json()
    assert plain["id"] != ex["id"]
    cards = (await seeded.execute(select(Card))).scalars().all()
    assert all(c.skill_id for c in cards)  # linked to the matching skill


async def test_card_review_follows_fsrs(client: httpx.AsyncClient) -> None:
    ex = (await client.post("/explainers", json={"topic": "Agents & tool use", "depth": "engineer"})).json()
    due = (await client.get("/cards/due")).json()
    assert len(due) >= len(ex["cards"])
    c = due[0]
    r = (await client.post(f"/cards/{c['id']}/review", json={"rating": 3})).json()
    nxt = datetime.fromisoformat(r["due_at"])
    assert (
        timedelta(days=3, hours=23) <= nxt - datetime.now(UTC) <= timedelta(days=4, hours=1)
    )  # S0(Good)=3.71 → 4 d
    assert r["reps"] == 1 and r["state"] == "review"
    for x in (await client.get("/cards/due")).json():
        last = (await client.post(f"/cards/{x['id']}/review", json={"rating": 1})).json()
    assert last["remaining_due"] == 0
    today = (await client.get("/today")).json()
    assert "cards" in today["habit"]["steps"]  # finishing due cards completes the daily cards step


async def test_quiz_adjusts_skill_levels(client: httpx.AsyncClient, seeded: AsyncSession) -> None:
    await client.post("/explainers", json={"topic": "Evals & testing of LLM apps", "depth": "engineer"})
    q = (await client.post("/quizzes?n=4")).json()
    assert q["questions"] and "answer" not in q["questions"][0]
    # look up right answers server-side for the test
    from signal_core.db.models import Quiz

    quiz = await seeded.get(Quiz, __import__("uuid").UUID(q["id"]))
    answers = [x["answer"] for x in quiz.questions]
    res = (await client.post(f"/quizzes/{q['id']}/attempt", json={"answers": answers})).json()
    assert res["score"] == 1.0
    ev = (await seeded.execute(select(SkillEvent).where(SkillEvent.kind == "quiz"))).scalars().all()
    assert ev and all(e.delta > 0 for e in ev)
    prog = (await client.get("/gym/progress")).json()
    assert prog["radar"] and set(prog["target_split"]) == {"fundamental", "evolving", "tool-specific"}
    _ = Skill


async def test_moat_radar_report_with_evidence_links(client: httpx.AsyncClient, seeded: AsyncSession) -> None:
    assert (await client.get("/moat-radar/latest")).json() is None
    r = (await client.post("/moat-radar/generate")).json()
    pts = r["commoditising"] + r["appreciating"] + r["for_you"]["know"] + r["for_you"]["learn"]
    assert pts
    for p in pts:
        assert p["evidence"]
        for e in p["evidence"]:
            link = r["evidence"][e]
            assert link["url"].startswith("https://") and link["story_url"] == f"/stories/{e}"
    assert r["scorecard"]["total"] >= 1  # new predictions recorded with revisit dates
    latest = (await client.get("/moat-radar/latest")).json()
    assert latest["id"] == r["id"]
    # A due prediction gets reviewed (right/wrong/unclear) on the next run.
    p = (await seeded.execute(select(Prediction))).scalars().first()
    assert p is not None
    p.revisit_on = datetime.now(UTC).date() - timedelta(days=1)
    await seeded.commit()
    await client.post("/moat-radar/generate")
    await seeded.refresh(p)
    assert p.outcome in ("right", "wrong", "unclear")
