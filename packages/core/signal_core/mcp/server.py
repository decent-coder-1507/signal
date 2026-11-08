"""SIGNAL MCP server (stdio), READ-ONLY tools over the knowledge base (ADR-020).

Used by the Claude Runner for Ask SIGNAL (`--mcp-config data/mcp-signal.json --allowedTools mcp__signal`) and usable
from your own Claude Code / Claude Desktop. Write `data/mcp-signal.json` with `python -m signal_core.cli mcp-config`.
Built on MCP Python SDK 2.x (`MCPServer`, formerly FastMCP), verified 2026-11-08 against mcp 2.3.0.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy import desc, select

from signal_core.db.models import Brief, Item, Story
from signal_core.db.session import session_scope
from signal_core.settings import REPO_ROOT, get_settings

server: MCPServer = MCPServer(
    name="signal",
    instructions="Read-only access to Srijoy's SIGNAL knowledge base (stories, items, briefs). Cite ids you use.",
)


@server.tool(
    description="Hybrid search (semantic + keyword) over items, stories, notes, ideas, build logs and "
    "explainers. Optional since_days limits recency."
)
async def search_knowledge(query: str, since_days: int | None = None, limit: int = 8) -> list[dict[str, Any]]:
    from signal_core.ask.service import retrieve

    now = datetime.now(UTC)
    async with session_scope() as s:
        chunks = await retrieve(
            s, query, now, k=min(limit, 20), since=now - timedelta(days=since_days) if since_days else None
        )
    return [
        {
            "id": c.id,
            "kind": c.kind,
            "title": c.title,
            "text": c.text[:800],
            "url": c.url,
            "date": c.at.date().isoformat() if c.at else None,
        }
        for c in chunks
    ]


@server.tool(description="Get one story with its latest insight and source items.")
async def get_story(story_id: str) -> dict[str, Any]:
    from signal_core.radar.insight import latest_insight, story_items

    async with session_scope() as s:
        st = await s.get(Story, uuid.UUID(story_id))
        if st is None:
            return {"error": "not found"}
        ins = await latest_insight(s, st.id)
        rows = await story_items(s, st.id)
        return {
            "id": story_id,
            "title": st.title,
            "durability": st.durability,
            "what_happened": ins.what_happened if ins else None,
            "why_you": ins.why_you if ins else None,
            "items": [
                {"id": str(it.id), "title": it.title, "url": it.canonical_url, "source": src.name}
                for _si, it, src, _e in rows
            ],
        }


@server.tool(description="Get one stored item (article, paper, repo, post) by id.")
async def get_item(item_id: str) -> dict[str, Any]:
    async with session_scope() as s:
        it = await s.get(Item, uuid.UUID(item_id))
        if it is None:
            return {"error": "not found"}
        return {
            "id": item_id,
            "title": it.title,
            "url": it.canonical_url,
            "text": it.text[:4000],
            "published_at": it.published_at.isoformat() if it.published_at else None,
        }


@server.tool(description="Top stories of the last N days by score.")
async def top_stories(days: int = 7, limit: int = 10) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(days=days)
    async with session_scope() as s:
        rows = (
            await s.execute(
                select(Story)
                .where(Story.status == "active", Story.last_updated >= since, Story.final_score > 0)
                .order_by(desc(Story.final_score))
                .limit(min(limit, 25))
            )
        ).scalars()
        return [
            {"id": str(x.id), "title": x.title, "score": x.final_score, "durability": x.durability}
            for x in rows
        ]


@server.tool(description="The most recent brief (daily/weekly/monthly) as structured content.")
async def latest_brief(kind: str = "daily") -> dict[str, Any]:
    async with session_scope() as s:
        b = (
            (
                await s.execute(
                    select(Brief).where(Brief.kind == kind).order_by(desc(Brief.created_at)).limit(1)
                )
            )
            .scalars()
            .first()
        )
        return {"id": str(b.id), "content": b.content} if b else {"error": "no brief"}


def write_config(path: Path | None = None) -> Path:
    """MCP client config for the Claude Runner / your Claude apps. No secrets in the file: the server is launched
    from the repo directory and reads the database URL from `.env` via settings."""
    s = get_settings()
    path = path or s.data_dir / "mcp-signal.json"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    cfg = {
        "mcpServers": {
            "signal": {
                "command": "uv",
                "args": ["run", "--directory", str(REPO_ROOT), "python", "-m", "signal_core.mcp.server"],
                "env": {"SIGNAL_MODE": s.mode},
            }
        }
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return path


if __name__ == "__main__":
    server.run("stdio")
