"""Moat Radar (§6.11, P12): monthly / on-demand analysis of what is commoditising vs appreciating, with evidence links
and an accountable predictions scorecard."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.models import Item, MoatRadar, Prediction, Story, StoryInsight, StoryItem
from signal_core.llm import router as llm


async def generate(
    session: AsyncSession, now: datetime, topic: str | None = None, run_id: uuid.UUID | None = None
) -> MoatRadar:
    since = now - timedelta(days=30)
    q = (
        select(Story, StoryInsight)
        .join(StoryInsight, StoryInsight.story_id == Story.id)
        .where(Story.last_updated >= since, Story.status == "active")
        .order_by(desc(Story.final_score))
        .limit(60)
    )
    rows = (await session.execute(q)).all()
    seen: dict[uuid.UUID, tuple[Story, StoryInsight]] = {}
    for s, ins in rows:
        if s.id not in seen or ins.version > seen[s.id][1].version:
            seen[s.id] = (s, ins)
    pairs = list(seen.values())
    if topic:
        t = topic.lower()
        pairs = [
            (s, i) for s, i in pairs if t in s.title.lower() or t in " ".join(s.topics or []).lower()
        ] or pairs
    stories = [
        {
            "id": str(s.id),
            "title": s.title,
            "durability": i.durability,
            "hype": i.hype_verdict,
            "summary": i.what_happened[:300],
        }
        for s, i in pairs[:40]
    ]
    due = list(
        (
            await session.execute(
                select(Prediction).where(Prediction.outcome.is_(None), Prediction.revisit_on <= now.date())
            )
        ).scalars()
    )
    cfg = get_config().profile.owner
    r = await llm.call(
        "moat_radar",
        {
            "owner": cfg.name,
            "role": cfg.role,
            "goals": cfg.goals,
            "topic": topic,
            "stories": stories,
            "previous": [{"id": str(p.id), "text": p.text, "made_on": p.made_on.isoformat()} for p in due],
        },
        session=session,
        run_id=run_id,
        user_initiated=bool(topic),
    )
    valid = {s["id"] for s in stories}
    out = r.output.model_dump()

    def clean(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        res = []
        for p in points:
            ev = [e for e in p.get("evidence", []) if e in valid]
            if ev:  # a point without valid evidence is dropped, never shown
                res.append({**p, "evidence": ev})
        return res

    content = {
        "commoditising": clean(out["commoditising"]),
        "appreciating": clean(out["appreciating"]),
        "for_you": {k: clean(v) for k, v in out["for_you"].items()},
        "for_builders": clean(out["for_builders"]),
        "evidence": {s["id"]: s for s in stories},
    }
    radar = MoatRadar(
        period_start=since,
        period_end=now,
        topic=topic,
        content=content,
        prompt_version=r.prompt_version,
        model=r.model,
    )
    session.add(radar)
    await session.flush()
    for p in out["predictions"]:
        session.add(
            Prediction(
                text=p["text"],
                made_on=now.date(),
                revisit_on=now.date() + timedelta(days=int(p["revisit_in_days"])),
                origin="moat_radar",
                evidence=[],
            )
        )
    by_id = {str(p.id): p for p in due}
    for rv in out["prediction_reviews"]:
        p = by_id.get(rv["id"])
        if p is not None:
            p.outcome = rv["outcome"]
            p.evidence = [e for e in rv.get("evidence", []) if e in valid]
    await session.flush()
    return radar


async def evidence_links(session: AsyncSession, radar: MoatRadar) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for sid in (radar.content or {}).get("evidence", {}):
        url = (
            await session.execute(
                select(Item.canonical_url)
                .join(StoryItem, StoryItem.item_id == Item.id)
                .where(StoryItem.story_id == uuid.UUID(sid))
                .limit(1)
            )
        ).scalar()
        out[sid] = {
            "title": radar.content["evidence"][sid]["title"],
            "url": url or "",
            "story_url": f"/stories/{sid}",
        }
    return out


async def scorecard(session: AsyncSession) -> dict[str, Any]:
    preds = list((await session.execute(select(Prediction).order_by(desc(Prediction.made_on)))).scalars())
    done = [p for p in preds if p.outcome]
    right = sum(1 for p in done if p.outcome == "right")
    return {
        "total": len(preds),
        "resolved": len(done),
        "right": right,
        "accuracy": round(right / len(done), 2) if done else None,
        "items": [
            {
                "id": str(p.id),
                "text": p.text,
                "made_on": p.made_on.isoformat(),
                "revisit_on": p.revisit_on.isoformat(),
                "outcome": p.outcome,
            }
            for p in preds
        ],
    }
