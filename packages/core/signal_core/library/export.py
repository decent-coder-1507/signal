"""Export (§11.3, §16.5): Markdown vault (Obsidian-compatible: one file per story/idea/draft/note/explainer with YAML
front-matter and [[wiki-links]]), full JSON dump, metrics CSV. The raw-material bank and VANCO context are sensitive
and excluded unless `include_private=True` (§16.2)."""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.base import Base
from signal_core.db.models import (
    BuildLog,
    Draft,
    DraftVersion,
    Explainer,
    Idea,
    Metric,
    Note,
    Publication,
    RawMaterial,
    Story,
    StoryInsight,
)
from signal_core.radar.insight import story_items

SENSITIVE_TABLES = {"raw_materials", "users", "llm_cache", "profiles"}
SECRET_COLS = {"password_hash", "totp_secret", "api_token_hash", "embedding", "centroid", "tsv"}


def safe_name(title: str, used: set[str]) -> str:
    base = re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", title).strip()[:80] or "untitled"
    base = re.sub(r"\s+", " ", base)
    name, n = base, 2
    while name.lower() in used:
        name = f"{base} ({n})"
        n += 1
    used.add(name.lower())
    return name


def md(front: dict[str, Any], body: str) -> str:
    return (
        "---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True) + "---\n\n" + body.strip() + "\n"
    )


async def markdown_vault(session: AsyncSession, include_private: bool = False) -> bytes:
    used: set[str] = set()
    files: dict[str, str] = {}
    story_names: dict[str, str] = {}
    stories = list((await session.execute(select(Story).where(Story.status == "active"))).scalars())
    for s in stories:
        story_names[str(s.id)] = safe_name(s.title, used)
    for s in stories:
        ins = (
            (
                await session.execute(
                    select(StoryInsight)
                    .where(StoryInsight.story_id == s.id)
                    .order_by(StoryInsight.version.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        rows = await story_items(session, s.id)
        cite = {str(it.id): i + 1 for i, (_si, it, _src, _e) in enumerate(rows)}
        what = ins.what_happened if ins else ""

        def footnote(m: re.Match[str], cite: dict[str, int] = cite) -> str:
            return f"[^{cite.get(m.group(1), '?')}]"

        what = re.sub(r"\[([0-9a-f-]{36})\]", footnote, what)
        refs = "\n".join(
            f"[^{i + 1}]: [{it.title}]({it.canonical_url}) ({src.name})"
            for i, (_si, it, src, _e) in enumerate(rows)
        )
        body = f"# {s.title}\n\n## What happened\n\n{what}\n\n"
        if ins:
            body += (
                f"## Why it matters to you\n\n{ins.why_you}\n\n## Hype check\n\n{ins.hype_verdict}\n\n"
                f"## Durability\n\n{ins.durability}: {ins.durability_reason}\n\n"
            )
        body += f"## Sources\n\n{refs}\n"
        files[f"Stories/{story_names[str(s.id)]}.md"] = md(
            {
                "type": "story",
                "id": str(s.id),
                "ring": s.ring,
                "topics": s.topics,
                "score": s.final_score,
                "first_seen": s.first_seen.isoformat(),
                "tags": ["signal/story", *[f"topic/{t}" for t in s.topics]],
            },
            body,
        )
    for i in (await session.execute(select(Idea))).scalars():
        name = safe_name(i.title, used)
        links = [f"[[{story_names[e['ref']]}]]" for e in (i.evidence or []) if e.get("ref") in story_names]
        logs = list(
            (
                await session.execute(
                    select(BuildLog).where(BuildLog.idea_id == i.id).order_by(BuildLog.logged_at)
                )
            ).scalars()
        )
        body = (
            f"# {i.title}\n\n{i.one_liner}\n\n## Problem\n\n{i.problem}\n\n## Solution\n\n{i.solution}\n\n"
            f"## Evidence\n\n"
            + "\n".join(f"- {x}" for x in links)
            + "\n\n## Build log\n\n"
            + "\n".join(f"- {lg.logged_at.date()}: {lg.text}" for lg in logs)
        )
        files[f"Ideas/{name}.md"] = md(
            {
                "type": "idea",
                "id": str(i.id),
                "status": i.status,
                "lab_score": i.lab_score,
                "tags": ["signal/idea", f"status/{i.status}"],
            },
            body,
        )
    for d in (await session.execute(select(Draft))).scalars():
        v = await session.get(DraftVersion, d.current_version_id) if d.current_version_id else None
        if v is None:
            continue
        name = safe_name(f"{d.platform} draft {d.created_at.date()}", used)
        text = "\n\n".join(v.thread) if v.thread else v.body
        files[f"Drafts/{name}.md"] = md(
            {
                "type": "draft",
                "id": str(d.id),
                "platform": d.platform,
                "status": d.status,
                "tags": ["signal/draft", f"platform/{d.platform}"],
            },
            text,
        )
    for n in (await session.execute(select(Note))).scalars():
        name = safe_name(n.text.split("\n", 1)[0][:60], used)
        files[f"Notes/{name}.md"] = md(
            {"type": n.kind, "id": str(n.id), "tags": ["signal/note", *n.tags]}, n.text
        )
    for e in (await session.execute(select(Explainer))).scalars():
        name = safe_name(f"{e.topic} ({e.depth})", used)
        files[f"Explainers/{name}.md"] = md(
            {"type": "explainer", "id": str(e.id), "depth": e.depth, "tags": ["signal/explainer"]}, e.body
        )
    if include_private:
        for r in (await session.execute(select(RawMaterial))).scalars():
            name = safe_name(f"{r.kind} {r.text[:50]}", used)
            files[f"Private/Raw material/{name}.md"] = md(
                {"type": "raw_material", "kind": r.kind, "confidentiality": r.confidentiality}, r.text
            )
    files["SIGNAL index.md"] = md(
        {"type": "index", "exported_at": datetime.now(UTC).isoformat()},
        "# SIGNAL export\n\n" + "\n".join(f"- [[{n}]]" for n in sorted(story_names.values())),
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, content in files.items():
            z.writestr(f"SIGNAL/{path}", content)
    return buf.getvalue()


async def json_dump(session: AsyncSession, include_private: bool = False) -> bytes:
    out: dict[str, list[dict[str, Any]]] = {}
    for table in Base.metadata.sorted_tables:
        if table.name in SENSITIVE_TABLES and not (include_private and table.name == "raw_materials"):
            continue
        cols = [c for c in table.columns if c.name not in SECRET_COLS]
        rows = (await session.execute(select(*cols))).mappings().all()
        out[table.name] = [
            {
                k: (
                    v.isoformat()
                    if hasattr(v, "isoformat")
                    else str(v)
                    if not isinstance(v, (int, float, str, bool, list, dict, type(None)))
                    else v
                )
                for k, v in r.items()
            }
            for r in rows
        ]
    return json.dumps(
        {"exported_at": datetime.now(UTC).isoformat(), "tables": out}, default=str, ensure_ascii=False
    ).encode()


async def metrics_csv(session: AsyncSession) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "platform",
            "url",
            "published_at",
            "horizon",
            "impressions",
            "reactions",
            "comments",
            "reposts",
            "saves",
            "profile_views",
            "followers_gained",
            "source",
        ]
    )
    rows = (
        await session.execute(
            select(Metric, Publication)
            .join(Publication, Publication.id == Metric.publication_id)
            .order_by(Publication.published_at)
        )
    ).all()
    for m, p in rows:
        w.writerow(
            [
                p.platform,
                p.url,
                p.published_at.isoformat(),
                m.horizon,
                m.impressions,
                m.reactions,
                m.comments,
                m.reposts,
                m.saves,
                m.profile_views,
                m.followers_gained,
                m.source,
            ]
        )
    return buf.getvalue()
