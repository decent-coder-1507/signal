"""GYM + Moat Radar API (§13): skills, learn-next, explainers, cards (FSRS), quizzes, progress, moat radar."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from signal_api.deps import DB, CurrentUser
from signal_core.brief import habit
from signal_core.db.models import Card, MoatRadar, Quiz, Skill, SkillEvent
from signal_core.gym import moat
from signal_core.gym import service as gym
from signal_core.gym.fsrs import CardState

router = APIRouter(tags=["gym"])


@router.get("/skills")
async def skills(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    return await gym.skill_tree(db)


class SkillPatch(BaseModel):
    current_level: float | None = Field(None, ge=0, le=5)
    target_level: float | None = Field(None, ge=0, le=5)
    durability: Literal["fundamental", "evolving", "tool-specific"] | None = None


@router.put("/skills/{sid}")
async def put_skill(sid: uuid.UUID, body: SkillPatch, _: CurrentUser, db: DB) -> dict[str, Any]:
    s = await db.get(Skill, sid)
    if s is None:
        raise HTTPException(404, "skill not found")
    if body.current_level is not None and body.current_level != s.current_level:
        db.add(
            SkillEvent(
                skill_id=s.id, kind="self", delta=body.current_level - s.current_level, note="self-rating"
            )
        )
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    await db.flush()
    return {
        "id": str(s.id),
        "name": s.name,
        "current_level": s.current_level,
        "target_level": s.target_level,
        "durability": s.durability,
    }


@router.get("/gym/learn-next")
async def learn_next(_: CurrentUser, db: DB) -> dict[str, Any]:
    return await gym.learn_next(db, datetime.now(UTC))


class ExplainerIn(BaseModel):
    topic: str = Field(min_length=2, max_length=255)
    depth: Literal["plain", "engineer", "deep"] = "engineer"
    story_id: uuid.UUID | None = None
    force: bool = False


def card_out(c: Card) -> dict[str, Any]:
    st = CardState.from_dict(c.fsrs_state)
    return {
        "id": str(c.id),
        "type": c.type,
        "front": c.front,
        "back": c.back,
        "durability": c.durability,
        "due_at": c.due_at.isoformat(),
        "skill_id": str(c.skill_id) if c.skill_id else None,
        "reps": st.reps,
        "lapses": st.lapses,
        "stability": round(st.stability, 2),
        "state": st.state,
    }


@router.post("/explainers", status_code=201)
async def explainer(body: ExplainerIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    ex, cards = await gym.explainer(db, body.topic, body.depth, body.story_id, body.force)
    return {
        "id": str(ex.id),
        "topic": ex.topic,
        "depth": ex.depth,
        "body": ex.body,
        "citations": ex.citations,
        "cards": [card_out(c) for c in cards],
        "prompt_version": ex.prompt_version,
    }


@router.get("/cards/due")
async def due(_: CurrentUser, db: DB, limit: int = 50) -> list[dict[str, Any]]:
    return [card_out(c) for c in await gym.due_cards(db, datetime.now(UTC), limit)]


class CardIn(BaseModel):
    front: str = Field(min_length=2)
    back: str = Field(min_length=1)
    type: Literal["qa", "cloze", "one_line", "scenario", "code"] = "qa"
    skill_id: uuid.UUID | None = None
    source_type: str = "highlight"
    source_id: uuid.UUID | None = None


@router.post("/cards", status_code=201)
async def add_card(body: CardIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    c = Card(**body.model_dump(), fsrs_state=CardState().to_dict(), due_at=datetime.now(UTC))
    db.add(c)
    await db.flush()
    return card_out(c)


class ReviewIn(BaseModel):
    rating: Literal[1, 2, 3, 4]
    elapsed_ms: int = 0


@router.post("/cards/{cid}/review")
async def review_card(cid: uuid.UUID, body: ReviewIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    c = await db.get(Card, cid)
    if c is None:
        raise HTTPException(404, "card not found")
    now = datetime.now(UTC)
    await gym.review_card(db, c, body.rating, now, body.elapsed_ms)
    remaining = len(await gym.due_cards(db, now))
    if remaining == 0:
        await habit.mark(db, now, "cards", 0)  # finishing the due cards completes the daily cards step
    return {**card_out(c), "remaining_due": remaining}


@router.post("/quizzes", status_code=201)
async def new_quiz(_: CurrentUser, db: DB, n: int = 10) -> dict[str, Any]:
    q = await gym.build_quiz(db, n)
    return {
        "id": str(q.id),
        "title": q.title,
        "questions": [{k: v for k, v in x.items() if k != "answer"} for x in q.questions],
    }


@router.get("/quizzes")
async def list_quizzes(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.execute(select(Quiz).order_by(desc(Quiz.created_at)).limit(20))).scalars()
    return [{"id": str(q.id), "title": q.title, "questions": len(q.questions)} for q in rows]


class AttemptIn(BaseModel):
    answers: list[str]


@router.post("/quizzes/{qid}/attempt")
async def attempt(qid: uuid.UUID, body: AttemptIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    q = await db.get(Quiz, qid)
    if q is None:
        raise HTTPException(404, "quiz not found")
    a = await gym.grade_quiz(db, q, body.answers)
    return {"score": a.score, "answers": [x["answer"] for x in q.questions]}


@router.get("/gym/progress")
async def gym_progress(_: CurrentUser, db: DB) -> dict[str, Any]:
    return await gym.progress(db, datetime.now(UTC))


def radar_out(r: MoatRadar, links: dict[str, Any]) -> dict[str, Any]:
    c = {k: v for k, v in (r.content or {}).items() if k != "evidence"}
    return {
        "id": str(r.id),
        "topic": r.topic,
        "period_start": r.period_start.isoformat(),
        "period_end": r.period_end.isoformat(),
        **c,
        "evidence": links,
        "prompt_version": r.prompt_version,
    }


@router.get("/moat-radar/latest")
async def moat_latest(_: CurrentUser, db: DB) -> dict[str, Any] | None:
    r = (
        (
            await db.execute(
                select(MoatRadar)
                .where(MoatRadar.topic.is_(None))
                .order_by(desc(MoatRadar.created_at))
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if r is None:
        return None
    return {**radar_out(r, await moat.evidence_links(db, r)), "scorecard": await moat.scorecard(db)}


@router.post("/moat-radar/generate", status_code=201)
async def moat_generate(_: CurrentUser, db: DB, topic: str | None = None) -> dict[str, Any]:
    r = await moat.generate(db, datetime.now(UTC), topic)
    return {**radar_out(r, await moat.evidence_links(db, r)), "scorecard": await moat.scorecard(db)}


@router.get("/predictions")
async def predictions(_: CurrentUser, db: DB) -> dict[str, Any]:
    return await moat.scorecard(db)


@router.get("/gym/stats")
async def stats(_: CurrentUser, db: DB) -> dict[str, int]:
    n = (await db.execute(select(func.count()).select_from(Card))).scalar_one()
    return {"cards": int(n)}
