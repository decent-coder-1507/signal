"""Analytics, Ask SIGNAL (SSE), search, library (notes/highlights), export (§13)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, text

from signal_api.deps import DB, CurrentUser
from signal_core.analytics import service as analytics
from signal_core.ask import service as ask
from signal_core.db.models import (
    BuildLog,
    ChatMessage,
    ChatThread,
    Experiment,
    Explainer,
    Note,
    Publication,
    StoryItem,
)
from signal_core.embeddings import get_embedder
from signal_core.library import export

router = APIRouter(tags=["knowledge"])


# ---------------- analytics ----------------
class MetricsIn(BaseModel):
    horizon: Literal["48h", "7d", "custom"] = "custom"
    impressions: int = Field(0, ge=0)
    reactions: int = Field(0, ge=0)
    comments: int = Field(0, ge=0)
    reposts: int = Field(0, ge=0)
    saves: int = Field(0, ge=0)
    profile_views: int = Field(0, ge=0)
    followers_gained: int = 0


@router.post("/publications/{pid}/metrics", status_code=201)
async def add_metrics(pid: uuid.UUID, body: MetricsIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    p = await db.get(Publication, pid)
    if p is None:
        raise HTTPException(404, "publication not found")
    m = await analytics.record_metrics(db, p, body.model_dump(exclude={"horizon"}), body.horizon, "manual")
    return {"id": str(m.id), "engagement": analytics.engagement(m)}


@router.get("/publications")
async def list_publications(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (
        await db.execute(select(Publication).order_by(desc(Publication.published_at)).limit(200))
    ).scalars()
    return [
        {
            "id": str(p.id),
            "platform": p.platform,
            "url": p.url,
            "published_at": p.published_at.isoformat(),
            "is_baseline": p.is_baseline,
            "variables": {k: v for k, v in (p.variables or {}).items() if not k.startswith("_")},
        }
        for p in rows
    ]


class BaselineIn(BaseModel):
    platform: Literal["linkedin", "x", "instagram"]
    url: str
    published_at: datetime
    text: str = ""
    impressions: int = Field(ge=0)
    reactions: int = 0
    comments: int = 0
    reposts: int = 0
    saves: int = 0


@router.post("/analytics/baseline", status_code=201)
async def baseline(body: BaselineIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    vals = body.model_dump(include={"impressions", "reactions", "comments", "reposts", "saves"})
    p = await analytics.add_baseline_post(db, body.platform, body.url, body.published_at, vals, body.text)
    return {"id": str(p.id)}


@router.post("/metrics/import-csv")
async def import_csv(
    file: UploadFile, _: CurrentUser, db: DB, platform: Literal["linkedin", "x"] = "linkedin"
) -> dict[str, int]:
    try:
        return await analytics.import_csv(db, (await file.read()).decode("utf-8", "replace"), platform)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/analytics/summary")
async def summary(_: CurrentUser, db: DB, days: int = 90) -> dict[str, Any]:
    return await analytics.summary(db, datetime.now(UTC), days)


class ExperimentIn(BaseModel):
    name: str
    variable: Literal[
        "hook_type", "length_bucket", "format", "time_slot", "emoji_count", "voice_version", "label"
    ]
    variants: list[str] = Field(min_length=2)
    start: date
    end: date | None = None


@router.post("/experiments", status_code=201)
async def add_exp(body: ExperimentIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    if (
        await db.execute(select(Experiment).where(Experiment.end.is_(None)))
    ).scalars().first() and body.end is None:
        raise HTTPException(
            409, "one experiment at a time: close the running one first (one variable at a time)"
        )
    e = Experiment(**body.model_dump())
    db.add(e)
    await db.flush()
    return {"id": str(e.id), **body.model_dump(mode="json")}


@router.get("/experiments")
async def list_exp(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    out = []
    for e in (await db.execute(select(Experiment).order_by(desc(Experiment.start)))).scalars():
        out.append(
            {
                "id": str(e.id),
                "name": e.name,
                "variable": e.variable,
                "variants": e.variants,
                "start": e.start.isoformat(),
                "end": e.end.isoformat() if e.end else None,
                "result": await analytics.experiment_result(db, e),
            }
        )
    return out


@router.put("/experiments/{eid}")
async def end_exp(eid: uuid.UUID, _: CurrentUser, db: DB, end: date | None = None) -> dict[str, Any]:
    e = await db.get(Experiment, eid)
    if e is None:
        raise HTTPException(404, "experiment not found")
    e.end = end or datetime.now(UTC).date()
    e.result = await analytics.experiment_result(db, e)
    return {"id": str(e.id), "result": e.result}


@router.post("/analytics/learnings", status_code=201)
async def learnings(_: CurrentUser, db: DB) -> dict[str, Any]:
    return await analytics.propose_learnings(db, datetime.now(UTC))


@router.get("/analytics/learnings")
async def list_learnings(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    from signal_core.services.settings_store import get_setting

    return list(await get_setting(db, "learning_proposals", []) or [])


@router.post("/analytics/learnings/{lid}/accept")
async def accept(lid: str, _: CurrentUser, db: DB) -> dict[str, Any]:
    try:
        return await analytics.accept_learnings(db, lid)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


# ---------------- Ask ----------------
class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    thread_id: uuid.UUID | None = None
    stream: bool = False


@router.post("/ask")
async def ask_q(body: AskIn, _: CurrentUser, db: DB) -> Any:
    res = await ask.answer(db, body.question, body.thread_id)
    if not body.stream:
        return res
    await db.commit()  # the stream is consumed after the request scope

    async def events() -> AsyncIterator[bytes]:
        words = res["answer"].split(" ")
        for i in range(0, len(words), 6):
            yield f"event: token\ndata: {json.dumps(' '.join(words[i : i + 6]) + ' ')}\n\n".encode()
            await asyncio.sleep(0)
        meta = {k: v for k, v in res.items() if k != "answer"}
        yield f"event: done\ndata: {json.dumps(meta, default=str)}\n\n".encode()

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/chat-threads")
async def chat_threads(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    return [
        {"id": str(t.id), "title": t.title, "updated_at": t.updated_at.isoformat()}
        for t in await ask.threads(db)
    ]


@router.get("/chat-threads/{tid}")
async def chat_thread(tid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    t = await db.get(ChatThread, tid)
    if t is None:
        raise HTTPException(404, "thread not found")
    msgs = (
        await db.execute(
            select(ChatMessage).where(ChatMessage.thread_id == tid).order_by(ChatMessage.created_at)
        )
    ).scalars()
    return {
        "id": str(t.id),
        "title": t.title,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "citations": m.citations,
                **(m.meta or {}),  # mode, not_in_kb, offer_watch: same fields as the live answer
            }
            for m in msgs
        ],
    }


@router.delete("/chat-threads/{tid}")
async def del_thread(tid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, bool]:
    t = await db.get(ChatThread, tid)
    if t is None:
        raise HTTPException(404, "thread not found")
    for m in (await db.execute(select(ChatMessage).where(ChatMessage.thread_id == tid))).scalars():
        await db.delete(m)
    await db.delete(t)
    return {"deleted": True}


class TurnIntoIn(BaseModel):
    target: Literal["post", "idea", "card", "note"]


@router.post("/ask/messages/{mid}/turn-into", status_code=201)
async def turn_into(mid: uuid.UUID, body: TurnIntoIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    m = await db.get(ChatMessage, mid)
    if m is None or m.role != "assistant":
        raise HTTPException(404, "answer not found")
    content = m.content
    if body.target == "post":
        from signal_core.studio.service import create_angles

        ideas = await create_angles(db, "free_text", None, content)
        return {"target": "post", "content_idea_ids": [str(i.id) for i in ideas]}
    if body.target == "idea":
        from signal_core.db.models import Idea

        i = Idea(
            type="poc",
            title=content.split(".")[0][:200],
            one_liner=content[:400],
            origin="manual",
            status="shortlisted",
        )
        db.add(i)
        await db.flush()
        return {"target": "idea", "idea_id": str(i.id)}
    if body.target == "card":
        from signal_core.db.models import Card
        from signal_core.gym.fsrs import CardState

        q = (
            (
                await db.execute(
                    select(ChatMessage)
                    .where(
                        ChatMessage.thread_id == m.thread_id,
                        ChatMessage.role == "user",
                        ChatMessage.created_at <= m.created_at,
                    )
                    .order_by(desc(ChatMessage.created_at))
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        c = Card(
            front=q.content if q else "Recall",
            back=content[:600],
            type="qa",
            source_type="ask",
            source_id=m.id,
            fsrs_state=CardState().to_dict(),
            due_at=datetime.now(UTC),
        )
        db.add(c)
        await db.flush()
        return {"target": "card", "card_id": str(c.id)}
    [v] = await get_embedder().embed([content])
    n = Note(text=content, kind="note", target_type="answer", target_id=m.id, embedding=v)
    db.add(n)
    await db.flush()
    return {"target": "note", "note_id": str(n.id)}


# ---------------- search & library ----------------
@router.get("/search")
async def search(
    _: CurrentUser, db: DB, q: str, kind: str | None = None, since: date | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    kinds = tuple(kind.split(",")) if kind else None
    chunks = await ask.retrieve(
        db,
        q,
        datetime.now(UTC),
        k=min(limit, 50),
        since=datetime.combine(since, datetime.min.time(), UTC) if since else None,
        kinds=kinds,
    )
    links = await _search_links(db, chunks)
    return [
        {
            "id": c.id,
            "kind": c.kind,
            "title": c.title,
            "snippet": c.text[:240],
            "url": c.url,
            "href": links.get(c.id),  # in-app page, or None (open `url`)
            "date": c.at.date().isoformat() if c.at else None,
        }
        for c in chunks
    ]


async def _search_links(db: DB, chunks: list[ask.Chunk]) -> dict[str, str | None]:
    """In-app href per hit; every href points at a page that exists. Items link to their story (if any)."""

    def ids(kind: str) -> list[uuid.UUID]:
        out = []
        for c in chunks:
            if c.kind == kind:
                with contextlib.suppress(ValueError):
                    out.append(uuid.UUID(c.id))
        return out

    links: dict[str, str | None] = {}
    if item_ids := ids("item"):
        rows = await db.execute(
            select(StoryItem.item_id, StoryItem.story_id).where(StoryItem.item_id.in_(item_ids))
        )
        links |= {str(i): f"/stories/{s}" for i, s in rows.all()}
    if log_ids := ids("build_log"):
        logs = await db.execute(select(BuildLog.id, BuildLog.idea_id).where(BuildLog.id.in_(log_ids)))
        links |= {str(i): f"/lab/{idea}" for i, idea in logs.all()}
    if ex_ids := ids("explainer"):
        exps = await db.execute(
            select(Explainer.id, Explainer.topic, Explainer.depth).where(Explainer.id.in_(ex_ids))
        )
        links |= {str(i): f"/gym?tab=explain&topic={quote(t)}&depth={quote(d)}" for i, t, d in exps.all()}
    for c in chunks:
        if c.kind == "story":
            links[c.id] = f"/stories/{c.id}"
        elif c.kind == "idea":
            links[c.id] = f"/lab/{c.id}"
        elif c.kind == "note":
            links[c.id] = "/library?tab=notes"
        links.setdefault(c.id, None)
    return links


class NoteIn(BaseModel):
    text: str = Field(min_length=1)
    kind: Literal["note", "highlight"] = "note"
    target_type: str | None = None
    target_id: uuid.UUID | None = None
    tags: list[str] = []
    collection: str | None = None
    make_card: bool = False


@router.post("/notes", status_code=201)
async def add_note(body: NoteIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    [v] = await get_embedder().embed([body.text])
    n = Note(**body.model_dump(exclude={"make_card"}), embedding=v)
    db.add(n)
    await db.flush()
    card_id = None
    if body.make_card:  # select text → highlight → optional flashcard (§11.3)
        from signal_core.db.models import Card
        from signal_core.gym.fsrs import CardState

        c = Card(
            front=f"Recall the key point: {body.text[:80]}…",
            back=body.text,
            type="one_line",
            source_type="highlight",
            source_id=n.id,
            fsrs_state=CardState().to_dict(),
            due_at=datetime.now(UTC),
        )
        db.add(c)
        await db.flush()
        card_id = str(c.id)
    return {"id": str(n.id), "card_id": card_id}


@router.get("/notes")
async def list_notes(_: CurrentUser, db: DB, collection: str | None = None) -> list[dict[str, Any]]:
    q = select(Note).order_by(desc(Note.created_at)).limit(300)
    if collection:
        q = q.where(Note.collection == collection)
    return [
        {
            "id": str(n.id),
            "kind": n.kind,
            "text": n.text,
            "tags": n.tags,
            "collection": n.collection,
            "target_type": n.target_type,
            "target_id": str(n.target_id) if n.target_id else None,
            "created_at": n.created_at.isoformat(),
        }
        for n in (await db.execute(q)).scalars()
    ]


@router.delete("/notes/{nid}")
async def del_note(nid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, bool]:
    n = await db.get(Note, nid)
    if n is None:
        raise HTTPException(404, "note not found")
    await db.delete(n)
    return {"deleted": True}


@router.get("/library/saved")
async def saved(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            text(
                "select i.id::text, i.title, i.canonical_url, i.capture_intent, i.created_at from items i "
                "where i.is_capture or exists (select 1 from feedback f where f.target_id = i.id and f.kind = 'saved') "
                "order by i.created_at desc limit 200"
            )
        )
    ).all()
    return [
        {"id": r[0], "title": r[1], "url": r[2], "intent": r[3], "saved_at": r[4].isoformat()} for r in rows
    ]


# ---------------- export ----------------
@router.get("/export/markdown.zip")
async def export_md(_: CurrentUser, db: DB, include_private: bool = False) -> Response:
    data = await export.markdown_vault(db, include_private)
    return Response(
        data,
        media_type="application/zip",
        headers={"content-disposition": 'attachment; filename="signal-vault.zip"'},
    )


@router.get("/export/json")
async def export_json(_: CurrentUser, db: DB, include_private: bool = False) -> Response:
    return Response(
        await export.json_dump(db, include_private),
        media_type="application/json",
        headers={"content-disposition": 'attachment; filename="signal-export.json"'},
    )


@router.get("/export/metrics.csv")
async def export_csv(_: CurrentUser, db: DB) -> Response:
    return Response(
        await export.metrics_csv(db),
        media_type="text/csv",
        headers={"content-disposition": 'attachment; filename="signal-metrics.csv"'},
    )
