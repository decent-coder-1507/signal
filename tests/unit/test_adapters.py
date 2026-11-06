"""HTTP contract tests for source adapters with recorded-style responses (respx)."""

import json
import time

import httpx
import pytest
import respx

from signal_core.sources.adapters import parse_trending
from signal_core.sources.base import AdapterNotConfigured, SourceSpec, get_adapter
from signal_core.sources.http import PoliteClient

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>
<entry><id>tag:x,2026:1</id><title>Post one</title><link href="https://blog.example/one"/>
<updated>2026-11-05T10:00:00Z</updated><summary>Summary one</summary><content type="html">&lt;p&gt;Body&lt;/p&gt;</content></entry>
<entry><id>tag:x,2026:2</id><title>Post two</title><link href="https://blog.example/two"/><updated>2026-11-04T10:00:00Z</updated></entry>
</feed>"""


def spec(t: str, url: str | None = None, **params: object) -> SourceSpec:
    return SourceSpec(id="s1", type=t, name=t, url=url, params=dict(params))


@pytest.fixture
async def client() -> PoliteClient:
    c = PoliteClient(per_host_interval_s=0, retries=1, backoff_s=0)
    yield c  # type: ignore[misc]
    await c.aclose()


@respx.mock
async def test_rss_parses_and_honours_conditional_get(client: PoliteClient) -> None:
    route = respx.get("https://blog.example/feed").mock(
        return_value=httpx.Response(200, content=ATOM, headers={"etag": '"v1"', "last-modified": "Wed"})
    )
    r = await get_adapter("rss")(spec("rss", "https://blog.example/feed"), client)
    assert [e.title for e in r.entries] == ["Post one", "Post two"]
    assert r.entries[0].published_at and r.entries[0].content_html.startswith("<p>")
    assert r.etag == '"v1"'
    route.mock(return_value=httpx.Response(304))
    s = spec("rss", "https://blog.example/feed")
    s.etag = '"v1"'
    r2 = await get_adapter("rss")(s, client)
    assert r2.not_modified and route.calls.last.request.headers["if-none-match"] == '"v1"'


@respx.mock
async def test_user_agent_is_generic(client: PoliteClient) -> None:
    route = respx.get("https://blog.example/feed").mock(return_value=httpx.Response(200, content=ATOM))
    await get_adapter("rss")(spec("rss", "https://blog.example/feed"), client)
    ua = route.calls.last.request.headers["user-agent"]
    assert ua.startswith("SIGNAL/") and "@" not in ua


@respx.mock
async def test_retries_then_succeeds_on_503(client: PoliteClient) -> None:
    route = respx.get("https://blog.example/feed").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, content=ATOM)]
    )
    r = await get_adapter("rss")(spec("rss", "https://blog.example/feed"), client)
    assert len(r.entries) == 2 and route.call_count == 2


@respx.mock
async def test_hn_filters_by_points_and_records_velocity(client: PoliteClient) -> None:
    base = "https://hacker-news.firebaseio.com/v0"
    now = int(time.time())
    respx.get(f"{base}/topstories.json").mock(return_value=httpx.Response(200, json=[1, 2, 3]))
    respx.get(f"{base}/item/1.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "type": "story",
                "title": "Big",
                "url": "https://x.example/a",
                "score": 300,
                "descendants": 50,
                "time": now - 7200,
                "by": "u",
            },
        )
    )
    respx.get(f"{base}/item/2.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "type": "story",
                "title": "Small",
                "url": "https://x.example/b",
                "score": 5,
                "time": now,
            },
        )
    )
    respx.get(f"{base}/item/3.json").mock(
        return_value=httpx.Response(200, json={"id": 3, "type": "job", "score": 999})
    )
    r = await get_adapter("hn")(spec("hn", endpoint="topstories", min_points=80), client)
    assert [e.title for e in r.entries] == ["Big"]
    m = r.entries[0].signal_meta
    assert m["hn_points"] == 300 and m["hn_points_per_hour"] == pytest.approx(150, rel=0.1)


@respx.mock
async def test_arxiv_ids_and_paper_type(client: PoliteClient) -> None:
    feed = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <id>http://arxiv.org/abs/2611.01234v2</id><title>A   Paper\n Title</title>
    <link href="http://arxiv.org/abs/2611.01234v2"/><published>2026-11-05T00:00:00Z</published>
    <summary>Abstract text.</summary></entry></feed>"""
    respx.get("https://export.arxiv.org/api/query").mock(return_value=httpx.Response(200, content=feed))
    r = await get_adapter("arxiv")(spec("arxiv", categories=["cs.CL", "cs.AI"]), client)
    e = r.entries[0]
    assert (
        e.external_id == "arxiv:2611.01234" and e.title == "A Paper Title" and e.content_type_hint == "paper"
    )
    q = respx.calls.last.request.url.params["search_query"]
    assert q == "cat:cs.CL OR cat:cs.AI"


@respx.mock
async def test_hf_daily_papers(client: PoliteClient) -> None:
    respx.get("https://huggingface.co/api/daily_papers").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "paper": {"id": "2611.00001", "title": "P", "summary": "S", "upvotes": 40},
                    "publishedAt": "2026-11-05T00:00:00Z",
                }
            ],
        )
    )
    r = await get_adapter("hf")(spec("hf", endpoint="daily_papers"), client)
    assert r.entries[0].url == "https://huggingface.co/papers/2611.00001"
    assert r.entries[0].signal_meta["hf_upvotes"] == 40


@respx.mock
async def test_github_releases_use_atom_feeds(client: PoliteClient) -> None:
    respx.get("https://github.com/acme/tool/releases.atom").mock(
        return_value=httpx.Response(200, content=ATOM)
    )
    r = await get_adapter("github")(spec("github", repos=["acme/tool"]), client)
    assert r.entries[0].title == "acme/tool Post one" and r.entries[0].content_type_hint == "release"


def test_trending_html_parser() -> None:
    html = """<html><body>
    <article class="Box-row"><h2><a href="/someone/tinyagent"> someone / tinyagent </a></h2>
      <p class="col-9">A 300-line agent framework</p><span>1,450 stars today</span></article>
    <article class="Box-row"><h2><a href="/b/c">b / c</a></h2><span>12 stars today</span></article>
    </body></html>"""
    out = parse_trending(html)
    assert [e.url for e in out] == ["https://github.com/someone/tinyagent", "https://github.com/b/c"]
    assert out[0].signal_meta["gh_stars_period"] == 1450 and "300-line" in out[0].title


async def test_credentialed_adapters_report_not_configured(client: PoliteClient) -> None:
    for t in ("reddit", "producthunt", "x", "email_in"):
        with pytest.raises(AdapterNotConfigured):
            await get_adapter(t)(spec(t), client)


@respx.mock
async def test_robots_txt_is_honoured_for_html(client: PoliteClient) -> None:
    respx.get("https://github.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /trending")
    )
    with pytest.raises(PermissionError):
        await get_adapter("github_trending")(spec("github_trending", languages=["python"]), client)


def test_spec_has_no_personal_data() -> None:
    from signal_core.sources.http import USER_AGENT

    assert json.dumps(USER_AGENT).count("@") == 0
