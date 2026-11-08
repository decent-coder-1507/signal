"""Measure §16.1 performance targets against a seeded database (in-process ASGI, mock LLM).

Usage (e2e/demo DB):  SIGNAL_MODE=mock SIGNAL_DATABASE_URL=...signal_e2e uv run python scripts/perf.py
Targets: home < 1.5 s, story page < 1 s, search < 500 ms, draft (writer+grader+factcheck) < 60 s,
daily brief ≤ 10 min of compute. Prints a JSON report (recorded in docs/PROGRESS.md).
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from typing import Any

import httpx
from asgi_lifespan import LifespanManager

TARGETS_MS = {"today": 1500, "brief_latest": 1500, "story_page": 1000, "search": 500, "stories_list": 1000}


async def timed(c: httpx.AsyncClient, method: str, url: str, n: int = 15, **kw: Any) -> dict[str, float]:
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = await c.request(method, url, **kw)
        ts.append((time.perf_counter() - t0) * 1000)
        r.raise_for_status()
    ts.sort()
    return {"p50_ms": round(statistics.median(ts), 1), "p95_ms": round(ts[int(len(ts) * 0.95) - 1], 1)}


async def main() -> dict[str, Any]:
    from signal_api.main import create_app

    email = os.environ.get("SIGNAL_ADMIN_EMAIL", "owner@e2e.local")
    pw = os.environ.get("SIGNAL_ADMIN_PASSWORD", "e2e-password-123")
    app = create_app()
    out: dict[str, Any] = {}
    async with LifespanManager(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                                       base_url="http://perf", timeout=600) as c:
        r = await c.post("/auth/login", json={"email": email, "password": pw})
        r.raise_for_status()
        c.headers["x-csrf-token"] = r.json()["csrf"]
        t0 = time.perf_counter()
        b = await c.post("/briefs/generate", json={"kind": "daily"})
        out["brief_generate_s"] = round(time.perf_counter() - t0, 2)
        b.raise_for_status()
        stories = (await c.get("/stories?limit=5")).json()["items"]
        out["today"] = await timed(c, "GET", "/today")
        out["brief_latest"] = await timed(c, "GET", "/briefs/latest")
        out["stories_list"] = await timed(c, "GET", "/stories?limit=20")
        out["story_page"] = await timed(c, "GET", f"/stories/{stories[0]['id']}")
        out["search"] = await timed(c, "GET", "/search?q=open weights coding agent")
        t0 = time.perf_counter()
        angles = (await c.post("/studio/angles", json={"seed_type": "story", "seed_id": stories[0]["id"]})).json()
        idea = next((a for a in angles if not a["needs_input"]), angles[0])
        await c.post("/studio/drafts", json={"content_idea_id": idea["id"], "platforms": ["linkedin"],
                                             "skip_questions": True})
        out["angles_plus_graded_draft_s"] = round(time.perf_counter() - t0, 2)
    out["targets_ms"] = TARGETS_MS
    out["passed"] = (all(out[k]["p95_ms"] <= v for k, v in TARGETS_MS.items())
                     and out["angles_plus_graded_draft_s"] < 60 and out["brief_generate_s"] < 600)
    out["note"] = ("Mock LLM: measures SIGNAL's own overhead. Live Claude Runner latency adds the model time "
                   "(see docs/PROGRESS.md).")
    return out


if __name__ == "__main__":
    res = asyncio.run(main())
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["passed"] else 1)
