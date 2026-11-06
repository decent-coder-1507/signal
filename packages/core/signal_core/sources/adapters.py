"""Source adapters (§6.2). Endpoints verified at build time (ADR-012)."""

from __future__ import annotations

import asyncio
import calendar
import contextlib
import email
import email.policy
import imaplib
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import feedparser
import lxml.html

from signal_core.settings import get_settings
from signal_core.sources.base import AdapterNotConfigured, FetchResult, RawEntry, SourceSpec, adapter
from signal_core.sources.http import PoliteClient

HN_API = "https://hacker-news.firebaseio.com/v0"
ARXIV_API = "https://export.arxiv.org/api/query"
HF_API = "https://huggingface.co/api"


def _ts(struct: Any) -> datetime | None:
    if not struct:
        return None
    try:
        d = datetime.fromtimestamp(calendar.timegm(struct), UTC)
    except (
        TypeError,
        ValueError,
        OverflowError,
        OSError,
    ):  # Windows raises OSError for pre-1970 / year-1 dates
        return None
    return d if d.year >= 1990 else None


def _iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_feed(content: bytes, hint: str | None = None) -> list[RawEntry]:
    f = feedparser.parse(content)
    out: list[RawEntry] = []
    for e in f.entries:
        link = e.get("link") or ""
        if not link and e.get("links"):
            link = e["links"][0].get("href", "")
        ext = e.get("id") or e.get("guid") or link
        if not ext or not link:
            continue
        content_html = ""
        if e.get("content"):
            content_html = " ".join(c.get("value", "") for c in e["content"])
        media_desc = ""
        if e.get("media_description"):
            media_desc = e["media_description"]
        out.append(
            RawEntry(
                external_id=str(ext)[:500],
                url=link,
                title=(e.get("title") or "").strip() or link,
                published_at=_ts(e.get("published_parsed") or e.get("updated_parsed")),
                author=e.get("author"),
                summary=e.get("summary") or media_desc or "",
                content_html=content_html,
                content_type_hint=hint,
                raw={
                    "tags": [t.get("term") for t in e.get("tags", []) if t.get("term")][:10],
                    "enclosures": [x.get("href") for x in e.get("enclosures", [])][:3],
                },
            )
        )
    return out


@adapter("rss", "podcast", "youtube")
async def rss(spec: SourceSpec, http: PoliteClient) -> FetchResult:
    assert spec.url
    r = await http.get(spec.url, etag=spec.etag, last_modified=spec.last_modified)
    if r.status_code == 304:
        return FetchResult([], not_modified=True, etag=spec.etag, last_modified=spec.last_modified)
    r.raise_for_status()
    hint = {"podcast": "podcast", "youtube": "video"}.get(spec.type)
    return FetchResult(
        parse_feed(r.content, hint), etag=r.headers.get("etag"), last_modified=r.headers.get("last-modified")
    )


@adapter("hn")
async def hacker_news(spec: SourceSpec, http: PoliteClient) -> FetchResult:
    """Official Firebase API. Items below min_points are skipped; points/comments kept as signal."""
    endpoint = spec.params.get("endpoint", "topstories")
    limit = int(spec.params.get("limit", 200))
    min_points = int(spec.params.get("min_points", 0))
    ids = (await http.get(f"{HN_API}/{endpoint}.json")).json()[:limit]

    async def one(i: int) -> dict[str, Any] | None:
        r = await http.get(f"{HN_API}/item/{i}.json")
        return r.json() if r.status_code == 200 else None

    items = await asyncio.gather(*(one(i) for i in ids))
    out: list[RawEntry] = []
    for it in items:
        if not it or it.get("type") != "story" or it.get("dead") or it.get("deleted"):
            continue
        if int(it.get("score", 0)) < min_points:
            continue
        discussion = f"https://news.ycombinator.com/item?id={it['id']}"
        published = datetime.fromtimestamp(int(it.get("time", 0)), UTC)
        age_h = max((datetime.now(UTC) - published).total_seconds() / 3600, 0.5)
        out.append(
            RawEntry(
                external_id=f"hn:{it['id']}",
                url=it.get("url") or discussion,
                title=it.get("title", ""),
                published_at=published,
                author=it.get("by"),
                summary=it.get("text", "") or "",
                content_type_hint="post" if not it.get("url") else None,
                signal_meta={
                    "hn_points": it.get("score", 0),
                    "hn_comments": it.get("descendants", 0),
                    "hn_points_per_hour": round(it.get("score", 0) / age_h, 2),
                    "hn_url": discussion,
                },
            )
        )
    return FetchResult(out)


@adapter("arxiv")
async def arxiv(spec: SourceSpec, http: PoliteClient) -> FetchResult:
    cats = spec.params.get("categories") or ["cs.CL"]
    n = min(int(spec.params.get("max_per_day", 300)), 300)
    q = " OR ".join(f"cat:{c}" for c in cats)
    r = await http.get(
        ARXIV_API,
        params={
            "search_query": q,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": n,
        },
    )
    r.raise_for_status()
    out = []
    for e in parse_feed(r.content, "paper"):
        e.external_id = "arxiv:" + e.external_id.rsplit("/abs/", 1)[-1].split("v")[0]
        e.title = re.sub(r"\s+", " ", e.title)
        out.append(e)
    return FetchResult(out)


@adapter("hf")
async def huggingface(spec: SourceSpec, http: PoliteClient) -> FetchResult:
    ep = spec.params.get("endpoint", "daily_papers")
    out: list[RawEntry] = []
    if ep == "daily_papers":
        data = (await http.get(f"{HF_API}/daily_papers")).json()
        for d in data:
            p = d.get("paper", d)
            pid = p.get("id")
            if not pid:
                continue
            out.append(
                RawEntry(
                    external_id=f"hf-paper:{pid}",
                    url=f"https://huggingface.co/papers/{pid}",
                    title=p.get("title") or d.get("title", ""),
                    published_at=_iso(d.get("publishedAt") or p.get("publishedAt")),
                    summary=p.get("summary", ""),
                    content_type_hint="paper",
                    signal_meta={
                        "hf_upvotes": p.get("upvotes", 0),
                        "arxiv_url": f"https://arxiv.org/abs/{pid}",
                    },
                )
            )
    else:
        data = (await http.get(f"{HF_API}/models", params={"sort": "trendingScore", "limit": 30})).json()
        for m in data:
            mid = m.get("id") or m.get("modelId")
            if not mid:
                continue
            out.append(
                RawEntry(
                    external_id=f"hf-model:{mid}",
                    url=f"https://huggingface.co/{mid}",
                    title=f"Trending model: {mid}",
                    published_at=_iso(m.get("createdAt")),
                    summary=f"{m.get('pipeline_tag') or 'model'} on Hugging Face; likes {m.get('likes', 0)}, "
                    f"downloads {m.get('downloads', 0)}.",
                    content_type_hint="release",
                    signal_meta={"hf_likes": m.get("likes", 0), "hf_trending": m.get("trendingScore", 0)},
                )
            )
    return FetchResult(out)


@adapter("github")
async def github_releases(spec: SourceSpec, http: PoliteClient) -> FetchResult:
    """Watched-repo releases via public releases.atom feeds (no API quota)."""
    out: list[RawEntry] = []
    for repo in spec.params.get("repos", []):
        r = await http.get(f"https://github.com/{repo}/releases.atom")
        if r.status_code != 200:
            continue
        for e in parse_feed(r.content, "release")[:10]:
            e.title = f"{repo} {e.title}" if repo.split("/")[-1].lower() not in e.title.lower() else e.title
            e.raw["repo"] = repo
            out.append(e)
    return FetchResult(out)


_STARS = re.compile(r"([\d,]+)\s+stars?\s+(?:today|this week|this month)")


def parse_trending(html: str, since: str = "daily") -> list[RawEntry]:
    doc = lxml.html.fromstring(html)
    out: list[RawEntry] = []
    for row in doc.xpath("//article[contains(concat(' ', normalize-space(@class), ' '), ' Box-row ')]"):
        a = row.xpath(".//h2//a")
        if not a:
            continue
        repo = a[0].get("href", "").strip("/")
        desc_el = row.xpath(".//p")
        desc = desc_el[0].text_content().strip() if desc_el else ""
        m = _STARS.search(row.text_content())
        stars = int(m.group(1).replace(",", "")) if m else 0
        day = datetime.now(UTC).strftime("%Y%m%d")
        out.append(
            RawEntry(
                external_id=f"gh-trending:{repo}:{day}",
                url=f"https://github.com/{repo}",
                title=f"{repo}: {desc}" if desc else repo,
                published_at=datetime.now(UTC),
                summary=desc,
                content_type_hint="repo",
                signal_meta={"gh_stars_period": stars, "gh_trending_since": since},
            )
        )
    return out


@adapter("github_trending")
async def github_trending(spec: SourceSpec, http: PoliteClient) -> FetchResult:
    since = spec.params.get("since", "daily")
    out: list[RawEntry] = []
    for lang in spec.params.get("languages", ["python"]):
        r = await http.get(f"https://github.com/trending/{lang}", params={"since": since}, html=True)
        r.raise_for_status()
        out.extend(parse_trending(r.text, since))
    return FetchResult(out)


@adapter("reddit")
async def reddit(spec: SourceSpec, http: PoliteClient) -> FetchResult:
    s = get_settings()
    if not (s.reddit_client_id and s.reddit_client_secret):
        raise AdapterNotConfigured("Reddit needs SIGNAL_REDDIT_CLIENT_ID/SECRET (official API only)")
    tok = await http.post(
        "https://www.reddit.com/api/v1/access_token",
        data={"grant_type": "client_credentials"},
        auth=(s.reddit_client_id, s.reddit_client_secret),
    )
    tok.raise_for_status()
    h = {"authorization": f"bearer {tok.json()['access_token']}"}
    out: list[RawEntry] = []
    for sub in spec.params.get("subreddits", []):
        r = await http.get(
            f"https://oauth.reddit.com/r/{sub}/top", params={"t": "day", "limit": 25}, headers=h
        )
        for c in r.json().get("data", {}).get("children", []):
            d = c["data"]
            out.append(
                RawEntry(
                    external_id=f"reddit:{d['id']}",
                    url=d.get("url_overridden_by_dest") or f"https://www.reddit.com{d['permalink']}",
                    title=d["title"],
                    published_at=datetime.fromtimestamp(d["created_utc"], UTC),
                    author=d.get("author"),
                    summary=d.get("selftext", "")[:4000],
                    content_type_hint="post",
                    signal_meta={
                        "reddit_score": d.get("score", 0),
                        "reddit_comments": d.get("num_comments", 0),
                        "subreddit": sub,
                        "permalink": f"https://www.reddit.com{d['permalink']}",
                    },
                )
            )
    return FetchResult(out)


@adapter("producthunt")
async def producthunt(spec: SourceSpec, http: PoliteClient) -> FetchResult:
    s = get_settings()
    if not s.producthunt_token:
        raise AdapterNotConfigured("Product Hunt needs SIGNAL_PRODUCTHUNT_TOKEN")
    q = "{ posts(first: 30, order: RANKING) { edges { node { id name tagline url votesCount createdAt website } } } }"
    r = await http.post(
        "https://api.producthunt.com/v2/api/graphql",
        json={"query": q},
        headers={"authorization": f"Bearer {s.producthunt_token}"},
    )
    r.raise_for_status()
    out = []
    for edge in r.json()["data"]["posts"]["edges"]:
        n = edge["node"]
        out.append(
            RawEntry(
                external_id=f"ph:{n['id']}",
                url=n.get("website") or n["url"],
                title=f"{n['name']}: {n['tagline']}",
                published_at=_iso(n.get("createdAt")),
                summary=n["tagline"],
                content_type_hint="launch",
                signal_meta={"ph_votes": n.get("votesCount", 0), "ph_url": n["url"]},
            )
        )
    return FetchResult(out)


@adapter("x")
async def x_lists(spec: SourceSpec, http: PoliteClient) -> FetchResult:
    s = get_settings()
    if not s.x_bearer_token or not spec.params.get("list_id"):
        raise AdapterNotConfigured("X needs official API access (SIGNAL_X_BEARER_TOKEN) and a list_id")
    r = await http.get(
        f"https://api.x.com/2/lists/{spec.params['list_id']}/tweets",
        params={"max_results": 100, "tweet.fields": "created_at,author_id,public_metrics"},
        headers={"authorization": f"Bearer {s.x_bearer_token}"},
    )
    r.raise_for_status()
    out = []
    for t in r.json().get("data", []):
        out.append(
            RawEntry(
                external_id=f"x:{t['id']}",
                url=f"https://x.com/i/web/status/{t['id']}",
                title=t["text"][:120],
                published_at=_iso(t.get("created_at")),
                summary=t["text"],
                content_type_hint="post",
                signal_meta=t.get("public_metrics", {}),
            )
        )
    return FetchResult(out)


def _imap_fetch(url: str, limit: int = 50) -> list[RawEntry]:
    u = urlsplit(url)
    box = (u.path or "/INBOX").lstrip("/") or "INBOX"
    conn = (
        imaplib.IMAP4_SSL(u.hostname or "", u.port or 993)
        if u.scheme == "imaps"
        else imaplib.IMAP4(u.hostname or "", u.port or 143)
    )
    try:
        conn.login(u.username or "", u.password or "")
        conn.select(box)
        _, data = conn.search(None, "UNSEEN")
        out: list[RawEntry] = []
        for num in (data[0].split() if data and data[0] else [])[:limit]:
            _, msg_data = conn.fetch(num, "(RFC822)")
            raw = msg_data[0][1] if msg_data and isinstance(msg_data[0], tuple) else b""
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            body = msg.get_body(preferencelist=("html", "plain"))
            content = body.get_content() if body else ""
            date = parsedate_to_datetime(msg["date"]) if msg["date"] else None
            mid = (msg["message-id"] or f"imap:{num.decode()}").strip("<>")
            out.append(
                RawEntry(
                    external_id=f"email:{mid}",
                    url=f"mid:{mid}",
                    title=str(msg["subject"] or "(no subject)"),
                    published_at=date,
                    author=str(msg["from"] or ""),
                    content_html=str(content),
                    content_type_hint="newsletter",
                )
            )
        return out
    finally:
        with contextlib.suppress(Exception):
            conn.logout()


@adapter("email_in")
async def email_in(spec: SourceSpec, http: PoliteClient) -> FetchResult:
    url = get_settings().imap_url
    if not url:
        raise AdapterNotConfigured("email_in needs SIGNAL_IMAP_URL (imaps://user:pass@host/INBOX)")
    return FetchResult(await asyncio.to_thread(_imap_fetch, url))


@adapter("capture", "jobs")
async def not_fetched(spec: SourceSpec, http: PoliteClient) -> FetchResult:
    """Capture items arrive via POST /capture; job feeds are phase 2."""
    return FetchResult([])
