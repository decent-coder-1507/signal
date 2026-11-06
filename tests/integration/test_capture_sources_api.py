import io
import time
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from asgi_lifespan import LifespanManager
from pypdf import PdfWriter
from sqlalchemy.ext.asyncio import AsyncSession

from signal_api.main import create_app

EMAIL, PW = "owner@test.local", "correct horse battery"


@pytest.fixture
async def client(seeded: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    from signal_api.routers.auth import _attempts

    _attempts.clear()
    app = create_app()
    async with LifespanManager(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/auth/login", json={"email": EMAIL, "password": PW})
            c.headers["x-csrf-token"] = r.json()["csrf"]
            yield c


PAGE = (
    """<html><head><title>Tiny agents in practice</title></head><body><article>
<h1>Tiny agents in practice</h1>"""
    + "<p>Agents call tools in a loop and check results before answering. </p>" * 40
    + "</article></body></html>"
)


async def test_capture_url_creates_item_fast(client: httpx.AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as m:
        m.route(host="test").pass_through()
        m.get("https://blog.example/tiny-agents?utm_source=tw").mock(
            return_value=httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})
        )
        t0 = time.monotonic()
        r = await client.post(
            "/capture", data={"url": "https://blog.example/tiny-agents?utm_source=tw", "intent": "post"}
        )
        elapsed = time.monotonic() - t0
    assert r.status_code == 201, r.text
    item = r.json()
    assert elapsed < 5.0
    assert item["title"] == "Tiny agents in practice" and item["url"] == "https://blog.example/tiny-agents"
    assert item["is_capture"] and item["capture_intent"] == "post" and item["prefilter_score"] == 1.0
    assert "call tools in a loop" in item["text"]
    # Capturing the same URL again returns the same item (no duplicate).
    with respx.mock(assert_all_called=False) as m:
        m.route(host="test").pass_through()
        r2 = await client.post("/capture", data={"url": "https://blog.example/tiny-agents"})
    assert r2.json()["id"] == item["id"]


async def test_capture_survives_unreachable_page(client: httpx.AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as m:
        m.route(host="test").pass_through()
        m.get("https://down.example/x").mock(side_effect=httpx.ConnectError("down"))
        r = await client.post("/capture", data={"url": "https://down.example/x", "title": "Saved anyway"})
    assert r.status_code == 201 and r.json()["title"] == "Saved anyway"


async def test_capture_text_and_pdf(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/capture", data={"text": "Idea: evals for RAG\nStart with 50 real questions.", "intent": "build"}
    )
    assert r.status_code == 201 and r.json()["title"] == "Idea: evals for RAG"
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    r = await client.post("/capture", files={"file": ("paper.pdf", buf.getvalue(), "application/pdf")})
    assert r.status_code == 201 and r.json()["content_type"] == "paper"
    bad = await client.post("/capture", files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert bad.status_code == 415


async def test_capture_with_api_token(client: httpx.AsyncClient) -> None:
    token = (await client.post("/auth/api-token", json={"password": PW})).json()["token"]
    client.cookies.clear()
    r = await client.post(
        "/capture",
        data={"text": "bookmarklet note"},
        headers={"authorization": f"Bearer {token}", "x-csrf-token": ""},
    )
    assert r.status_code == 201


async def test_sources_crud_test_fetch_and_health(client: httpx.AsyncClient) -> None:
    from signal_core.db.session import session_scope
    from signal_core.demo import seed_fixture_sources

    async with session_scope() as s:
        await seed_fixture_sources(s)
    sources = (await client.get("/sources")).json()
    assert len(sources) >= 40  # starter pack + fixtures
    fx = next(s for s in sources if s["name"] == "Fixture: Official blogs")
    t = (await client.post(f"/sources/{fx['id']}/test")).json()
    assert t["ok"] and t["entries"] > 0 and t["sample"][0]["title"]
    f = (await client.post(f"/sources/{fx['id']}/fetch")).json()
    assert f["status"] == "ok" and f["new"] > 0
    h = (await client.get(f"/sources/{fx['id']}/health")).json()
    assert h["fetches"][0]["status"] == "ok"
    # create / update / delete
    r = await client.post(
        "/sources", json={"type": "rss", "name": "My feed", "url": "https://my.example/feed"}
    )
    assert r.status_code == 201
    sid = r.json()["id"]
    assert (await client.put(f"/sources/{sid}", json={"tier": 1})).json()["tier"] == 1
    assert (await client.delete(f"/sources/{sid}")).json()["deleted"] is True
    assert (await client.post("/sources", json={"type": "nope", "name": "x"})).status_code == 422


async def test_opml_import(client: httpx.AsyncClient) -> None:
    opml = """<?xml version="1.0"?><opml version="2.0"><body>
      <outline text="AI"><outline text="Feed A" xmlUrl="https://a.example/rss"/>
      <outline text="Feed B" xmlUrl="https://b.example/rss"/></outline>
      <outline text="Simon" xmlUrl="https://simonwillison.net/atom/everything/"/></body></opml>"""
    r = await client.post("/sources/import-opml", files={"file": ("subs.opml", opml.encode(), "text/xml")})
    assert r.json() == {"found": 3, "added": 2}  # Simon Willison already in the starter pack
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><opml><body/></opml>'
    assert (
        await client.post("/sources/import-opml", files={"file": ("x.opml", bomb.encode(), "text/xml")})
    ).status_code == 400
