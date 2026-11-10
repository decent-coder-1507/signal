"""Stories, story pages and feedback (§13)."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc, or_, select

from signal_api.deps import DB, CurrentUser
from signal_core.db.models import Feedback, Story, StoryInsight
from signal_core.radar.insight import generate_insights, latest_insight, story_items
from signal_core.radar.preference import nudge_topics, retrain
from signal_core.radar.scoring import score_stories
from signal_core.truth import first_sentence

router = APIRouter(tags=["stories"])

BADGE_HYPE = {
    "substance": "Substance",
    "mixed": "Mixed",
    "mostly_hype": "Mostly hype",
    "too_early": "Too early",
}


def insight_out(i: StoryInsight | None) -> dict[str, Any] | None:
    if i is None:
        return None
    return {
        "version": i.version,
        "what_happened": i.what_happened,
        "why_you": i.why_you,
        "what_changes": i.what_changes,
        "hype_verdict": i.hype_verdict,
        "hype_reasons": i.hype_reasons,
        "durability": i.durability,
        "durability_reason": i.durability_reason,
        "moat_note": i.moat_note,
        "open_questions": i.open_questions,
        "actions": i.actions,
        "confidence": i.confidence,
        "confidence_reason": i.confidence_reason,
        "reading_time": i.reading_time,
        "uncertainty_labels": i.uncertainty_labels,
        "citations": i.citations,
        "degraded": i.degraded,
        "prompt_version": i.prompt_version,
        "model": i.model,
        "created_at": i.created_at.isoformat(),
    }


def story_card(s: Story, ins: StoryInsight | None) -> dict[str, Any]:
    update = bool(
        s.material_update_at
        and (not s.last_shown_at or s.material_update_at > s.last_shown_at)
        and s.last_shown_at
    )
    one_line = first_sentence(ins.what_happened) if ins else ""
    return {
        "id": str(s.id),
        "title": s.title,
        "ring": s.ring,
        "topics": s.topics,
        "final_score": s.final_score,
        "first_seen": s.first_seen.isoformat(),
        "last_updated": s.last_updated.isoformat(),
        "followed": s.followed,
        "durability": s.durability,
        "hype_verdict": s.hype_verdict,
        "update": update,
        "what_changed": s.what_changed,
        "one_line": one_line,
        "why_you": ins.why_you if ins else None,
        "sources": (s.scores or {}).get("sources", []),
        "excluded": (s.scores or {}).get("excluded"),
    }


def _cursor(s: Story) -> str:
    return base64.urlsafe_b64encode(json.dumps([s.final_score, str(s.id)]).encode()).decode()


@router.get("/stories")
async def list_stories(
    _: CurrentUser,
    db: DB,
    ring: str | None = None,
    topic: str | None = None,
    since: datetime | None = None,
    include_excluded: bool = False,
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    q = select(Story).where(Story.status == "active")
    if ring:
        q = q.where(Story.ring == ring)
    if topic:
        q = q.where(Story.topics.contains([topic]))
    if since:
        q = q.where(Story.last_updated >= since)
    if not include_excluded:
        q = q.where(Story.final_score > -0.5)
    if cursor:
        score, sid = json.loads(base64.urlsafe_b64decode(cursor))
        q = q.where(
            or_(Story.final_score < score, and_(Story.final_score == score, Story.id < uuid.UUID(sid)))
        )
    rows = list(
        (await db.execute(q.order_by(desc(Story.final_score), desc(Story.id)).limit(limit + 1))).scalars()
    )
    page, more = rows[:limit], len(rows) > limit
    cards = [story_card(s, await latest_insight(db, s.id)) for s in page]
    return {"items": cards, "next_cursor": _cursor(page[-1]) if more and page else None}


@router.get("/stories/{sid}")
async def get_story(sid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    s = await db.get(Story, sid)
    if s is None:
        raise HTTPException(404, "story not found")
    if s.status == "merged" and s.merged_into:
        s = await db.get(Story, s.merged_into) or s
    ins = await latest_insight(db, s.id)
    rows = await story_items(db, s.id)
    timeline = sorted(
        [
            {
                "item_id": str(it.id),
                "title": it.title,
                "url": it.canonical_url,
                "source": src.name,
                "tier": src.tier,
                "role": si.role,
                "published_at": it.published_at.isoformat() if it.published_at else None,
                "summary": e.summary_1line if e else None,
                "key_facts": e.key_facts if e else [],
                "signal": {k: v for k, v in (it.signal_meta or {}).items() if k != "prefilter"},
            }
            for si, it, src, e in rows
        ],
        key=lambda x: x["published_at"] or "",
    )
    for i, t in enumerate(timeline):
        t["label"] = (
            "first reported"
            if i == 0
            else {
                "primary": "official / primary source",
                "reaction": "community reaction",
                "followup": "follow-up",
            }.get(t["role"], "report")
        )
    related = (
        list(
            (
                await db.execute(
                    select(Story)
                    .where(Story.id != s.id, Story.status == "active", Story.topics.overlap(s.topics or []))
                    .order_by(desc(Story.final_score))
                    .limit(5)
                )
            ).scalars()
        )
        if s.topics
        else []
    )
    sc = s.scores or {}
    why = {
        "final_score": s.final_score,
        "weights": sc.get("weights"),
        "penalties": sc.get("penalties", []),
        "excluded": sc.get("excluded"),
        "matched_profile": sc.get("matched_profile"),
        "judge": sc.get("judge"),
        "sub_scores": {
            k: sc.get(k)
            for k in (
                "relevance",
                "impact",
                "signal",
                "novelty",
                "credibility",
                "durability",
                "actionability",
                "learned",
                "momentum",
            )
        },
    }
    return {
        "story": story_card(s, ins),
        "insight": insight_out(ins),
        "timeline": timeline,
        "related": [{"id": str(r.id), "title": r.title} for r in related],
        "why": why,
    }


@router.post("/stories/{sid}/follow")
async def follow(sid: uuid.UUID, _: CurrentUser, db: DB, on: bool = True) -> dict[str, bool]:
    s = await db.get(Story, sid)
    if s is None:
        raise HTTPException(404, "story not found")
    s.followed = on
    return {"followed": on}


@router.post("/stories/{sid}/regenerate-insight")
async def regenerate(sid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    s = await db.get(Story, sid)
    if s is None:
        raise HTTPException(404, "story not found")
    await generate_insights(db, [s], force=True)
    return {"insight": insight_out(await latest_insight(db, s.id))}


FeedbackKind = Literal[
    "useful", "not_for_me", "more", "less", "wrong", "known", "opened", "dwell", "used", "saved"
]


class FeedbackIn(BaseModel):
    target_type: Literal["story", "item", "draft", "idea", "card", "insight", "brief", "explainer", "answer"]
    target_id: uuid.UUID
    kind: FeedbackKind
    value: float = 1.0
    context: dict[str, Any] = {}


@router.post("/feedback", status_code=201)
async def feedback(body: FeedbackIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    db.add(Feedback(**body.model_dump()))
    await db.flush()
    out: dict[str, Any] = {"ok": True}
    if body.target_type == "story":
        s = await db.get(Story, body.target_id)
        if s is not None:
            now = datetime.now(UTC)
            out["topic_nudges"] = await nudge_topics(db, s, body.kind, now)
            if body.kind in ("useful", "not_for_me", "more", "less", "known", "wrong", "used", "saved"):
                pm = await retrain(db)
                out["preference_model"] = pm.version if pm else None
                await score_stories(db, now, judge=False)
    if body.kind == "wrong":
        from signal_core.db.models import EvalCase

        db.add(
            EvalCase(
                task=f"report:{body.target_type}",
                input={"target_id": str(body.target_id), **body.context},
                expected={},
                label="wrong/inaccurate",
                origin="user_report",
            )
        )
    return out
