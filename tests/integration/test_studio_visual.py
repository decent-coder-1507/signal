"""M5 acceptance: carousel 1080×1350 PNGs + PDF with contrast check; reel hook ≤ 2 s and 30–60 s; article export
valid Markdown with front-matter and working code fences; Hashnode publish only after explicit approval (mock)."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import yaml
from asgi_lifespan import LifespanManager
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_api.main import create_app
from signal_core.db.models import Story, StoryItem
from signal_core.demo import fixture_client, seed_fixture_sources
from signal_core.radar.jobs import ingest_all_due
from signal_core.radar.pipeline import process
from signal_core.render.renderer import RenderError, check_contrast, contrast
from signal_core.studio.visual import validate_markdown, validate_reel

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
EMAIL, PW = "owner@test.local", "correct horse battery"


@pytest.fixture
async def client(
    seeded: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    from signal_api.routers.auth import _attempts
    from signal_core.settings import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    _attempts.clear()
    await seed_fixture_sources(seeded, include_broken=False)
    await seeded.commit()
    await ingest_all_due(NOW, fixture_client(NOW))
    await process(seeded, NOW)
    await seeded.commit()
    app = create_app()
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=180) as c,
    ):
        r = await c.post("/auth/login", json={"email": EMAIL, "password": PW})
        c.headers["x-csrf-token"] = r.json()["csrf"]
        yield c


async def idea_for(client: httpx.AsyncClient, db: AsyncSession) -> str:
    for s in (await db.execute(select(Story).where(Story.status == "active"))).scalars():
        if "Nimbus-4" in s.title:
            n = (await db.execute(select(StoryItem).where(StoryItem.story_id == s.id))).scalars().all()
            if len(n) >= 3:
                angles = (
                    await client.post("/studio/angles", json={"seed_type": "story", "seed_id": str(s.id)})
                ).json()
                return str(next(a for a in angles if not a["needs_input"])["id"])
    raise AssertionError("no Nimbus-4 story")


async def draft(client: httpx.AsyncClient, db: AsyncSession, platform: str) -> dict:  # type: ignore[type-arg]
    idea = await idea_for(client, db)
    return (
        await client.post("/studio/drafts", json={"content_idea_id": idea, "platforms": [platform]})
    ).json()[0]


async def test_carousel_renders_pngs_and_pdf(client: httpx.AsyncClient, seeded: AsyncSession) -> None:
    d = await draft(client, seeded, "instagram_carousel")
    slides = d["current"]
    assert d["format"] == "carousel"
    assert d["current"]["factcheck"]["uncited_sentences"] == []
    assets = (await client.post(f"/studio/drafts/{d['id']}/render")).json()
    pngs = [a for a in assets if a["kind"] == "png"]
    pdf = next(a for a in assets if a["kind"] == "pdf")
    assert 6 <= len(pngs) <= 10 and all(a["meta"]["w"] == 1080 and a["meta"]["h"] == 1350 for a in pngs)
    assert all(a["meta"]["alt"] for a in pngs)
    assert pdf["meta"]["contrast"]["fg_bg"] >= 4.5 and pdf["meta"]["min_font_px"] >= 28
    png = await client.get(pngs[0]["url"])
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = int.from_bytes(png.content[16:20], "big"), int.from_bytes(png.content[20:24], "big")
    assert (w, h) == (1080, 1350)
    pdf_bytes = (await client.get(pdf["url"])).content
    from io import BytesIO

    reader = PdfReader(BytesIO(pdf_bytes))
    assert len(reader.pages) == len(pngs)
    box = reader.pages[0].mediabox
    assert round(float(box.width) / float(box.height), 3) == round(1080 / 1350, 3)
    _ = slides


async def test_inline_slide_edit_and_rerender(client: httpx.AsyncClient, seeded: AsyncSession) -> None:
    d = await draft(client, seeded, "linkedin_carousel")
    items = d["current"]["aitell"] and (await client.get(f"/studio/drafts/{d['id']}")).json()["versions"][-1]
    cur = (await client.get(f"/studio/drafts/{d['id']}")).json()["current"]
    assert items
    ed = (
        await client.put(
            f"/studio/drafts/{d['id']}",
            json={
                "slides": [
                    {"title": "Edited hook", "body": "New text", "alt": "a"},
                    *[{"title": f"S{i}", "body": "x", "alt": "a"} for i in range(5)],
                ]
            },
        )
    ).json()
    assert ed["current"]["author"] == "human" and ed["current"]["id"] != cur["id"]
    assets = (await client.post(f"/studio/drafts/{d['id']}/render")).json()
    assert sum(a["kind"] == "png" for a in assets) == 6


def test_contrast_check_rejects_low_contrast() -> None:
    assert contrast("#FFFFFF", "#111827") > 15
    with pytest.raises(RenderError):
        check_contrast({"bg": "#777777", "fg": "#888888", "muted": "#999999", "accent": "#aaaaaa"})


async def test_reel_script_timing(client: httpx.AsyncClient, seeded: AsyncSession) -> None:
    d = await draft(client, seeded, "instagram_reel")
    full = (await client.get(f"/studio/drafts/{d['id']}")).json()
    script = full["versions"][-1]
    sc = (await client.get(f"/studio/drafts/{d['id']}")).json()
    v = sc["current"]
    assert v["gate"] == [] or all("timestamps" not in g and "hook" not in g for g in v["gate"])
    from signal_core.db.models import DraftVersion

    dv = await seeded.get(DraftVersion, __import__("uuid").UUID(v["id"]))
    s = dv.script
    assert s["hook"]["t_start"] == 0 and s["hook"]["t_end"] <= 2
    total = s["beats"][-1]["t_end"]
    assert 30 <= total <= 60
    for prev, cur in zip([s["hook"], *s["beats"]], s["beats"], strict=False):
        assert cur["t_start"] == prev["t_end"]
    assert validate_reel(s, {"seconds": [30, 60], "hook_seconds_max": 2}) == []
    bad = {**s, "hook": {**s["hook"], "t_end": 3.5}}
    assert any(i["type"] == "hook" for i in validate_reel(bad, {"seconds": [30, 60], "hook_seconds_max": 2}))
    _ = script


async def test_article_export_markdown(client: httpx.AsyncClient, seeded: AsyncSession) -> None:
    d = await draft(client, seeded, "hashnode")
    r = await client.get(f"/studio/drafts/{d['id']}/export.md")
    md = r.text
    assert r.status_code == 200 and md.startswith("---\n")
    fm = yaml.safe_load(md.split("---\n", 2)[1])
    assert fm["title"] and isinstance(fm["tags"], list)
    assert md.count("```") % 2 == 0 and "```python" in md
    code = md.split("```python", 1)[1].split("```", 1)[0]
    compile(code, "<article>", "exec")  # working code fence
    refs = [ln for ln in md.splitlines() if ln.startswith("- [")]
    assert refs and all("example/" in ln for ln in refs)  # only fixture source URLs
    issues = validate_markdown(md, set(), [1200, 2500])
    assert any(i["type"] == "url" for i in issues)  # with an empty whitelist, the refs are rejected
    assert not any(i["type"] in ("front_matter", "code_fence") and i["severity"] == "error" for i in issues)


async def test_hashnode_publish_requires_explicit_approval(
    client: httpx.AsyncClient, seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signal_api.routers.studio as studio_router
    from signal_core.settings import get_settings

    calls: list[dict] = []  # type: ignore[type-arg]

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append({"auth": req.headers.get("authorization"), "input": body["variables"]["input"]})
        return httpx.Response(
            200,
            json={
                "data": {"publishPost": {"post": {"id": "p1", "slug": "s", "url": "https://blog.example/s"}}}
            },
        )

    monkeypatch.setattr(studio_router, "_hashnode_transport", httpx.MockTransport(handler))
    d = await draft(client, seeded, "hashnode")
    url = f"/studio/drafts/{d['id']}/publish-api"
    r = await client.post(url, json={"confirm": True})
    assert r.status_code == 409 and "disabled" in r.json()["detail"]  # flag off by default
    await client.put(
        "/settings", json={"flags": {"publish.hashnode_api": True}, "hashnode_publication_id": "pub123"}
    )
    monkeypatch.setattr(get_settings(), "hashnode_token", "pat-test")
    r = await client.post(url, json={"confirm": True})
    assert r.status_code == 409 and "Ready" in r.json()["detail"]  # must be approved first
    await client.post(
        f"/studio/drafts/{d['id']}/approve", json={"override_reason": "long-form reviewed by me"}
    )
    r = await client.post(url, json={"confirm": False})
    assert r.status_code == 409 and "explicit confirmation" in r.json()["detail"]
    assert calls == []  # nothing was sent before explicit approval
    r = await client.post(url, json={"confirm": True})
    assert r.status_code == 200 and r.json()["post"]["url"] == "https://blog.example/s"
    assert (
        len(calls) == 1 and calls[0]["auth"] == "pat-test" and calls[0]["input"]["publicationId"] == "pub123"
    )
    assert not calls[0]["input"]["contentMarkdown"].startswith("---")


async def test_quote_and_stat_cards(client: httpx.AsyncClient) -> None:
    for kind in ("quote_card", "stat_card"):
        a = (
            await client.post(
                "/studio/cards",
                json={
                    "kind": kind,
                    "title": "71.2%",
                    "body": "SWE-bench, self-reported",
                    "source": "Nimbus AI",
                },
            )
        ).json()
        assert (await client.get(a["url"])).content[:4] == b"\x89PNG"
