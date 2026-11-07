"""LAB API (§13): ideas, idea page, status (incl. kill with reason), build briefs (+ zip), build logs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from signal_api.deps import DB, CurrentUser
from signal_core.db.models import BuildBrief, BuildLog, Idea
from signal_core.lab import service as lab

router = APIRouter(tags=["lab"])


def idea_out(i: Idea) -> dict[str, Any]:
    return {
        k: (str(getattr(i, k)) if k == "id" else getattr(i, k))
        for k in (
            "id",
            "type",
            "title",
            "one_liner",
            "evidence",
            "problem",
            "persona",
            "why_now",
            "solution",
            "mvp_scope",
            "not_in_mvp",
            "stack",
            "effort",
            "risks",
            "moat",
            "validation_plan",
            "learning_skills",
            "content_plan",
            "scores",
            "lab_score",
            "prior_art",
            "status",
            "kill_reason",
            "origin",
        )
    } | {"created_at": i.created_at.isoformat(), "updated_at": i.updated_at.isoformat()}


async def _idea(db: DB, iid: uuid.UUID) -> Idea:
    i = await db.get(Idea, iid)
    if i is None:
        raise HTTPException(404, "idea not found")
    return i


@router.get("/ideas")
async def list_ideas(_: CurrentUser, db: DB, status: str | None = None) -> list[dict[str, Any]]:
    q = select(Idea).order_by(desc(Idea.lab_score), desc(Idea.created_at)).limit(300)
    if status:
        q = q.where(Idea.status == status)
    return [idea_out(i) for i in (await db.execute(q)).scalars()]


@router.get("/ideas/{iid}")
async def get_idea(iid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    i = await _idea(db, iid)
    logs = (
        await db.execute(select(BuildLog).where(BuildLog.idea_id == i.id).order_by(BuildLog.logged_at))
    ).scalars()
    briefs = (
        (
            await db.execute(
                select(BuildBrief).where(BuildBrief.idea_id == i.id).order_by(desc(BuildBrief.version))
            )
        )
        .scalars()
        .all()
    )
    return {
        **idea_out(i),
        "evidence_links": await lab.evidence_links(db, i),
        "logs": [
            {
                "id": str(lg.id),
                "text": lg.text,
                "attachments": lg.attachments,
                "logged_at": lg.logged_at.isoformat(),
            }
            for lg in logs
        ],
        "brief": {"version": briefs[0].version, "files": briefs[0].files} if briefs else None,
    }


class IdeaIn(BaseModel):
    type: Literal[
        "practical", "experiment", "poc", "weekend_build", "product", "oss_contribution", "teardown", "vanco"
    ]
    title: str = Field(min_length=3)
    one_liner: str = ""
    problem: str = ""
    solution: str = ""
    scores: dict[str, float] = {}


@router.post("/ideas", status_code=201)
async def create_idea(body: IdeaIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    i = Idea(**body.model_dump(), lab_score=lab.lab_score(body.scores), origin="manual", status="shortlisted")
    db.add(i)
    await db.flush()
    return idea_out(i)


@router.put("/ideas/{iid}")
async def update_idea(iid: uuid.UUID, body: dict[str, Any], _: CurrentUser, db: DB) -> dict[str, Any]:
    i = await _idea(db, iid)
    editable = {
        "title",
        "one_liner",
        "problem",
        "persona",
        "why_now",
        "solution",
        "mvp_scope",
        "not_in_mvp",
        "stack",
        "effort",
        "risks",
        "moat",
        "validation_plan",
        "learning_skills",
        "content_plan",
        "scores",
    }
    for k, v in body.items():
        if k in editable:
            setattr(i, k, v)
    if "scores" in body:
        i.lab_score = lab.lab_score(body["scores"])
    return idea_out(i)


class StatusIn(BaseModel):
    status: str
    kill_reason: str | None = None


@router.post("/ideas/{iid}/status")
async def status(iid: uuid.UUID, body: StatusIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    try:
        return idea_out(await lab.set_status(db, await _idea(db, iid), body.status, body.kill_reason))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/ideas/{iid}/brief", status_code=201)
async def brief(iid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    bb = await lab.generate_brief(db, await _idea(db, iid))
    return {"version": bb.version, "files": bb.files}


@router.get("/ideas/{iid}/brief.zip")
async def brief_zip(iid: uuid.UUID, _: CurrentUser, db: DB) -> Response:
    i = await _idea(db, iid)
    bb = (
        (
            await db.execute(
                select(BuildBrief)
                .where(BuildBrief.idea_id == i.id)
                .order_by(desc(BuildBrief.version))
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if bb is None:
        bb = await lab.generate_brief(db, i)
    slug = lab.slugify(i.title)
    return Response(
        lab.brief_zip(bb, slug),
        media_type="application/zip",
        headers={"content-disposition": f'attachment; filename="{slug}-brief.zip"'},
    )


class LogIn(BaseModel):
    text: str = Field(min_length=2, max_length=4000)
    attachments: list[dict[str, Any]] = []


@router.post("/ideas/{iid}/logs", status_code=201)
async def add_log(iid: uuid.UUID, body: LogIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    lg = await lab.add_log(db, await _idea(db, iid), body.text, body.attachments, datetime.now(UTC))
    return {"id": str(lg.id), "text": lg.text, "logged_at": lg.logged_at.isoformat()}


@router.post("/lab/sparks/detect")
async def detect(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    return [idea_out(i) for i in await lab.detect_sparks(db, datetime.now(UTC))]
