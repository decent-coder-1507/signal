"""Verify the starter source pack live (§0.1 rule 7). Usage: uv run python scripts/verify_sources.py [--json out.json]

For RSS/podcast/youtube: GET + feedparser, report entries and newest date. For github: releases.atom per repo.
API sources are probed with one request. Prints a table; exit code 1 if any enabled source fails.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import feedparser
import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
UA = "SIGNAL/0.1 (personal feed reader; +https://github.com/)"


async def check_feed(c: httpx.AsyncClient, url: str) -> dict[str, Any]:
    r = await c.get(url)
    f = feedparser.parse(r.content)
    dates = [
        e.get("published") or e.get("updated") for e in f.entries if e.get("published") or e.get("updated")
    ]
    return {
        "http": r.status_code,
        "entries": len(f.entries),
        "newest": dates[0] if dates else None,
        "ok": r.status_code == 200 and len(f.entries) > 0,
        "final_url": str(r.url),
    }


SEM = asyncio.Semaphore(6)


async def check(c: httpx.AsyncClient, s: dict[str, Any]) -> dict[str, Any]:
    async with SEM:
        r = await _check(c, s)
        if r.get("ok") is False:
            await asyncio.sleep(2)
            r = await _check(c, s)
        return r


async def _check(c: httpx.AsyncClient, s: dict[str, Any]) -> dict[str, Any]:
    t = s["type"]
    try:
        if t in ("rss", "podcast", "youtube"):
            return await check_feed(c, s["url"])
        if t == "hn":
            r = await c.get(f"https://hacker-news.firebaseio.com/v0/{s.get('endpoint', 'topstories')}.json")
            return {"http": r.status_code, "entries": len(r.json()), "ok": r.status_code == 200}
        if t == "arxiv":
            r = await c.get(
                "https://export.arxiv.org/api/query",
                params={"search_query": "cat:cs.CL", "max_results": 5, "sortBy": "submittedDate"},
            )
            return {
                "http": r.status_code,
                "entries": len(feedparser.parse(r.content).entries),
                "ok": r.status_code == 200,
            }
        if t == "hf":
            url = (
                "https://huggingface.co/api/daily_papers"
                if s.get("endpoint") == "daily_papers"
                else "https://huggingface.co/api/models?sort=trendingScore&limit=20"
            )
            r = await c.get(url)
            return {"http": r.status_code, "entries": len(r.json()), "ok": r.status_code == 200}
        if t == "github":
            res = {}
            for repo in s.get("repos", []):
                res[repo] = (await check_feed(c, f"https://github.com/{repo}/releases.atom"))["entries"]
            bad = [k for k, v in res.items() if v == 0]
            return {"http": 200, "entries": sum(res.values()), "ok": not bad, "bad_repos": bad}
        if t == "github_trending":
            r = await c.get("https://github.com/trending/python?since=daily")
            return {
                "http": r.status_code,
                "entries": r.text.count('class="Box-row"'),
                "ok": r.status_code == 200,
            }
        return {"ok": None, "note": "not probed (needs credentials or no remote)"}
    except Exception as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}


async def main() -> int:
    data = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))["sources"]
    async with httpx.AsyncClient(headers={"user-agent": UA}, timeout=60, follow_redirects=True) as c:
        results = await asyncio.gather(*(check(c, s) for s in data))
    failed = 0
    for s, r in zip(data, results, strict=True):
        enabled = s.get("enabled", True)
        mark = "OK " if r.get("ok") else ("-- " if r.get("ok") is None or not enabled else "FAIL")
        if r.get("ok") is False and enabled:
            failed += 1
        print(
            f"{mark:4} {s['type']:15} {s['name'][:34]:34} entries={r.get('entries', '-'):<4} "
            f"http={r.get('http', '-')} {r.get('error', '') or r.get('bad_repos', '') or r.get('newest', '') or ''}"
        )
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(
            json.dumps(
                [{"name": s["name"], **r} for s, r in zip(data, results, strict=True)], indent=2, default=str
            )
        )
    print(f"\n{len(data)} sources, {failed} enabled failing")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
