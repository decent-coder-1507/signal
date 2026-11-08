"""M9 acceptance: Telegram metrics form stores data; analytics vs baseline; accepting learnings → new voice version;
Ask answers fixture questions with correct citations and says "not in your knowledge base"; export opens in Obsidian."""

import io
import re
import zipfile
from collections import Counter
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import yaml
from asgi_lifespan import LifespanManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_api.main import create_app
from signal_core.db.models import Item, Metric, Publication, StoryItem, VoiceProfile
from signal_core.demo import fixture_client, seed_fixture_sources
from signal_core.fixtures_corpus import labels
from signal_core.notify import telegram
from signal_core.radar.jobs import ingest_all_due
from signal_core.radar.normalise import canonical_url
from signal_core.radar.pipeline import process
from signal_core.settings import get_settings

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


async def event_of(db: AsyncSession, item_or_story_id: str) -> str | None:
    lab = {canonical_url(u): e for u, e in labels().items()}
    it = await db.get(Item, __import__("uuid").UUID(item_or_story_id))
    if it is not None:
        return lab.get(it.canonical_url)
    urls = (
        (
            await db.execute(
                select(Item.canonical_url)
                .join(StoryItem, StoryItem.item_id == Item.id)
                .where(StoryItem.story_id == __import__("uuid").UUID(item_or_story_id))
            )
        )
        .scalars()
        .all()
    )
    return Counter(lab.get(u) for u in urls).most_common(1)[0][0] if urls else None


async def test_ask_answers_with_correct_citations(client: httpx.AsyncClient, seeded: AsyncSession) -> None:
    r = (
        await client.post(
            "/ask", json={"question": "What did Nimbus AI release and what does it score on SWE-bench?"}
        )
    ).json()
    assert not r["not_in_kb"] and r["citations"]
    assert "71.2%" in r["answer"] or "Nimbus-4" in r["answer"]
    for c in r["citations"]:
        assert f"[{c['id']}]" in r["answer"]
        assert await event_of(seeded, c["id"]) in ("nimbus4", "nimbusprice")
    r2 = (
        await client.post(
            "/ask",
            json={
                "question": "How do the coding agent prompt injection attacks work?",
                "thread_id": r["thread_id"],
            },
        )
    ).json()
    assert r2["thread_id"] == r["thread_id"] and r2["citations"]
    assert {await event_of(seeded, c["id"]) for c in r2["citations"]} == {"injection"}
    thread = (await client.get(f"/chat-threads/{r['thread_id']}")).json()
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant", "user", "assistant"]


async def test_ask_says_not_in_knowledge_base(client: httpx.AsyncClient) -> None:
    r = (
        await client.post(
            "/ask", json={"question": "What did the Martian parliament decide about tea tariffs?"}
        )
    ).json()
    assert r["not_in_kb"] and "Not in your knowledge base" in r["answer"] and r["citations"] == []
    assert r.get("offer_watch")


async def test_ask_time_filter_slash_and_stream(client: httpx.AsyncClient) -> None:
    r = (await client.post("/ask", json={"question": "Nimbus pricing since 2030-01-01"})).json()
    assert r["not_in_kb"]  # nothing that recent
    ex = (await client.post("/ask", json={"question": "/explain speculative decoding"})).json()
    assert ex["mode"] == "explain" and ex["cards"] >= 3
    async with client.stream("POST", "/ask", json={"question": "What is Tessera 1.0?", "stream": True}) as s:
        body = "".join([chunk async for chunk in s.aiter_text()])
    assert "event: token" in body and "event: done" in body
    a = (await client.post("/ask", json={"question": "What is Tessera 1.0?"})).json()
    for target in ("note", "card", "idea"):
        t = await client.post(f"/ask/messages/{a['message_id']}/turn-into", json={"target": target})
        assert t.status_code == 201


async def test_search_and_library(client: httpx.AsyncClient) -> None:
    res = (await client.get("/search?q=open weights model")).json()
    assert res and any("Orchid" in x["title"] for x in res)
    n = (
        await client.post(
            "/notes",
            json={"text": "Verifier loops cut unsupported answers.", "kind": "highlight", "make_card": True},
        )
    ).json()
    assert n["card_id"]
    assert (await client.get("/notes")).json()[0]["kind"] == "highlight"


async def test_metrics_via_telegram_and_baseline(
    client: httpx.AsyncClient, seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    calls: list = []  # type: ignore[type-arg]
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "1:T")
    monkeypatch.setattr(get_settings(), "telegram_chat_id", "77")
    telegram.set_transport(
        httpx.MockTransport(
            lambda req: (
                calls.append(json.loads(req.content)),
                httpx.Response(200, json={"ok": True, "result": {}}),
            )[1]
        )
    )
    try:
        for i in range(10):  # his last 10 pre-SIGNAL posts (entered at onboarding)
            await client.post(
                "/analytics/baseline",
                json={
                    "platform": "linkedin",
                    "url": f"https://www.linkedin.com/posts/old-{i}",
                    "published_at": (NOW - timedelta(days=60 + i)).isoformat(),
                    "impressions": 1000 + 100 * i,
                    "reactions": 20,
                    "comments": 3,
                },
            )
        pub = Publication(
            platform="linkedin",
            url="https://www.linkedin.com/posts/new-1",
            published_at=NOW - timedelta(hours=50),
            text="x",
            variables={"hook_type": "practitioner", "length_bucket": "medium"},
        )
        seeded.add(pub)
        await seeded.commit()
        upd = {
            "update_id": 9,
            "message": {"chat": {"id": 77}, "text": f"/metrics {pub.id.hex[-8:]} 3000 90 12 4 6"},
        }
        out = await telegram.handle_update(seeded, upd)
        await seeded.commit()
        assert out["ok"] and out["horizon"] == "48h"
        m = (await seeded.execute(select(Metric).where(Metric.publication_id == pub.id))).scalar_one()
        assert (m.impressions, m.reactions, m.comments, m.reposts, m.saves, m.source) == (
            3000,
            90,
            12,
            4,
            6,
            "manual",
        )
        assert "Saved 48h metrics" in calls[-1]["text"]
    finally:
        telegram.set_transport(None)
    s = (await client.get("/analytics/summary")).json()
    li = s["by_platform"]["linkedin"]
    assert li["baseline"]["posts"] == 10 and li["baseline"]["impressions"] == 1450
    assert li["vs_baseline_impressions"] == round(3000 / 1450, 2)
    assert s["breakdowns"]["hook_type"]["practitioner"]["caution"] is True  # sample-size caution


async def test_accepting_learnings_creates_voice_version(
    client: httpx.AsyncClient, seeded: AsyncSession
) -> None:
    v_before = (await client.get("/voice")).json()["version"]
    prop = (await client.post("/analytics/learnings")).json()
    assert prop["findings"] and prop["status"] == "proposed"
    r = (await client.post(f"/analytics/learnings/{prop['id']}/accept")).json()
    assert r["voice_version"] == v_before + 1
    active = (await seeded.execute(select(VoiceProfile).where(VoiceProfile.active.is_(True)))).scalar_one()
    assert active.version == v_before + 1 and "monthly learnings" in active.note
    assert (await client.post(f"/analytics/learnings/{prop['id']}/accept")).status_code == 409


async def test_csv_import(client: httpx.AsyncClient, seeded: AsyncSession) -> None:
    csv_data = (
        "Post URL,Impressions,Reactions,Comments,Reposts\nhttps://www.linkedin.com/posts/csv-1,1200,30,4,1\n"
    )
    r = (
        await client.post("/metrics/import-csv", files={"file": ("export.csv", csv_data, "text/csv")})
    ).json()
    assert r == {"matched": 0, "created": 1}
    assert (await client.get("/export/metrics.csv")).text.count("csv-1") == 1


async def test_export_opens_cleanly_in_obsidian(client: httpx.AsyncClient) -> None:
    await client.post("/raw-materials", json={"kind": "story", "text": "Private: our client churn number"})
    await client.post("/notes", json={"text": "A note to self"})
    z = zipfile.ZipFile(io.BytesIO((await client.get("/export/markdown.zip")).content))
    names = z.namelist()
    assert any(n.startswith("SIGNAL/Stories/") for n in names) and "SIGNAL/SIGNAL index.md" in names
    assert not any("Private/" in n for n in names)  # sensitive raw material excluded by default
    stems = {n.rsplit("/", 1)[-1][:-3] for n in names if n.endswith(".md")}
    for n in names:
        content = z.read(n).decode()
        assert content.startswith("---\n")
        fm = yaml.safe_load(content.split("---\n", 2)[1])
        assert isinstance(fm, dict) and fm.get("type")
        for link in re.findall(r"\[\[([^\]]+)\]\]", content):
            assert link in stems, (n, link)  # every wiki-link resolves
        assert not re.search(r"\[[0-9a-f-]{36}\]", content)  # raw uuids replaced by footnotes
    private = zipfile.ZipFile(
        io.BytesIO((await client.get("/export/markdown.zip?include_private=true")).content)
    )
    assert any("Private/" in n for n in private.namelist())
    dump = (await client.get("/export/json")).json()
    assert (
        "items" in dump["tables"] and "users" not in dump["tables"] and "raw_materials" not in dump["tables"]
    )
    assert all("password_hash" not in r for t in dump["tables"].values() for r in t)
