"""STUDIO API (§13): angles, drafts, ask-me, revise, repurpose, edit, approve, schedule, publish-assist,
series, calendar, raw-material bank, reference posts."""

from __future__ import annotations

import datetime as dt
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from signal_api.deps import DB, CurrentUser
from signal_core.config import get_config
from signal_core.db.models import (
    ContentIdea,
    Draft,
    DraftVersion,
    Publication,
    RawMaterial,
    ReferencePost,
    Series,
)
from signal_core.embeddings import get_embedder
from signal_core.services.settings_store import set_setting
from signal_core.studio import service as studio

router = APIRouter(tags=["studio"])
Platform = Literal[
    "linkedin", "x", "x_thread", "instagram_carousel", "linkedin_carousel", "instagram_reel", "hashnode"
]


def idea_out(c: ContentIdea) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "seed_type": c.seed_type,
        "seed_id": str(c.seed_id) if c.seed_id else None,
        "angle_type": c.angle_type,
        "thesis": c.thesis,
        "credibility": c.credibility,
        "needs_input": c.needs_input,
        "platforms": c.platform_suggestions,
        "risk": c.risk,
        "status": c.status,
    }


def version_out(v: DraftVersion) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "version": v.version,
        "label": v.label,
        "body": v.body,
        "thread": v.thread,
        "first_comment": v.first_comment,
        "slides": v.slides,
        "script": v.script,
        "claims": v.claims,
        "grade": v.grade,
        "factcheck": v.factcheck,
        "aitell": v.aitell,
        "checks": v.checks,
        "author": v.author,
        "voice_version": v.voice_version,
        "prompt_version": v.prompt_version,
        "model": v.model,
        "created_at": v.created_at.isoformat(),
        "gate": studio.gate_reasons(v),
    }


async def draft_out(db: DB, d: Draft, versions: bool = False) -> dict[str, Any]:
    cur = await db.get(DraftVersion, d.current_version_id) if d.current_version_id else None
    idea = await db.get(ContentIdea, d.content_idea_id) if d.content_idea_id else None
    out: dict[str, Any] = {
        "id": str(d.id),
        "platform": d.platform,
        "format": d.format,
        "status": d.status,
        "idea": idea_out(idea) if idea else None,
        "pending_questions": d.pending_questions,
        "scheduled_for": d.scheduled_for.isoformat() if d.scheduled_for else None,
        "timeliness_deadline": d.timeliness_deadline.isoformat() if d.timeliness_deadline else None,
        "post_within_24h": bool(
            d.timeliness_deadline
            and d.timeliness_deadline > datetime.now(UTC)
            and d.status in ("drafting", "ready")
        ),
        "evergreen": d.evergreen,
        "series_id": str(d.series_id) if d.series_id else None,
        "parent_draft_id": str(d.parent_draft_id) if d.parent_draft_id else None,
        "override": {k: v for k, v in (d.ready_override or {}).items() if not k.startswith("_")} or None,
        "current": version_out(cur) if cur else None,
        "updated_at": d.updated_at.isoformat(),
    }
    if versions:
        vs = (
            await db.execute(
                select(DraftVersion).where(DraftVersion.draft_id == d.id).order_by(DraftVersion.version)
            )
        ).scalars()
        out["versions"] = [version_out(v) for v in vs]
    return out


async def _draft(db: DB, did: uuid.UUID) -> Draft:
    d = await db.get(Draft, did)
    if d is None:
        raise HTTPException(404, "draft not found")
    return d


class AnglesIn(BaseModel):
    seed_type: Literal["story", "item", "build_log", "gym", "moat", "raw", "free_text", "series"]
    seed_id: uuid.UUID | None = None
    seed_text: str = ""


@router.post("/studio/angles", status_code=201)
async def angles(body: AnglesIn, _: CurrentUser, db: DB) -> list[dict[str, Any]]:
    if body.seed_type in ("story", "item", "build_log") and not body.seed_id:
        raise HTTPException(422, "seed_id required for this seed type")
    if body.seed_type == "free_text" and not body.seed_text.strip():
        raise HTTPException(422, "seed_text required")
    try:
        ideas = await studio.create_angles(db, body.seed_type, body.seed_id, body.seed_text)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    return [idea_out(i) for i in ideas]


class DraftsIn(BaseModel):
    content_idea_id: uuid.UUID
    platforms: list[Platform] = Field(min_length=1)
    skip_questions: bool = False


@router.post("/studio/drafts", status_code=201)
async def create_drafts(body: DraftsIn, _: CurrentUser, db: DB) -> list[dict[str, Any]]:
    try:
        drafts = await studio.start_drafts(
            db, body.content_idea_id, list(body.platforms), body.skip_questions
        )
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    return [await draft_out(db, d) for d in drafts]


@router.get("/studio/drafts")
async def list_drafts(_: CurrentUser, db: DB, status: str | None = None) -> list[dict[str, Any]]:
    q = select(Draft).order_by(desc(Draft.updated_at)).limit(200)
    if status:
        q = q.where(Draft.status == status)
    return [await draft_out(db, d) for d in (await db.execute(q)).scalars()]


@router.get("/studio/drafts/{did}")
async def get_draft(did: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    return await draft_out(db, await _draft(db, did), versions=True)


class AnswersIn(BaseModel):
    answers: dict[str, str] = {}
    save_to_bank: bool = True  # consent toggle (§7.4)
    can_name: bool = False
    skip: bool = False


@router.post("/studio/drafts/{did}/answer")
async def answer(did: uuid.UUID, body: AnswersIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    d = await _draft(db, did)
    if body.skip:  # writer must then not pretend to have personal experience
        d.pending_questions = []
        await studio.generate(db, d)
    else:
        await studio.answer_questions(db, d.id, body.answers, body.save_to_bank, body.can_name)
    return await draft_out(db, d, versions=True)


@router.post("/studio/drafts/{did}/revise")
async def revise(did: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    d = await _draft(db, did)
    cur = await studio.current_version(db, d)
    await studio.generate(
        db,
        d,
        revise={
            "total": (cur.grade or {}).get("total", 0),
            "edits": (cur.grade or {}).get("top_edits", []),
            "previous": cur.body or "\n\n".join(cur.thread or []),
        },
    )
    return await draft_out(db, d, versions=True)


class RepurposeIn(BaseModel):
    platform: Platform


@router.post("/studio/drafts/{did}/repurpose", status_code=201)
async def repurpose(did: uuid.UUID, body: RepurposeIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    nd = await studio.repurpose(db, await _draft(db, did), body.platform)
    return await draft_out(db, nd, versions=True)


class EditIn(BaseModel):
    slides: list[dict[str, Any]] | None = None  # inline slide edits → new human version, then re-render
    body: str | None = None
    thread: list[str] | None = None
    first_comment: str | None = None
    version_id: uuid.UUID | None = None  # pick a different version (e.g. B) as current


@router.put("/studio/drafts/{did}")
async def edit(did: uuid.UUID, body: EditIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    d = await _draft(db, did)
    if body.version_id:
        v = await db.get(DraftVersion, body.version_id)
        if v is None or v.draft_id != d.id:
            raise HTTPException(404, "version not found")
        d.current_version_id = v.id
    if body.slides is not None:
        cur = await studio.current_version(db, d)
        nv = await studio.human_edit(db, d, cur.body, cur.thread, cur.first_comment)
        nv.slides = {**(cur.slides or {}), "items": body.slides}
        from signal_core.studio.visual import _spec, validate_carousel

        issues = validate_carousel(body.slides, _spec(d.platform))
        nv.aitell = {**(nv.aitell or {}), "issues": [*(nv.aitell or {}).get("issues", []), *issues]}
        await db.flush()
    if body.body is not None or body.thread is not None or body.first_comment is not None:
        await studio.human_edit(db, d, body.body, body.thread, body.first_comment)
    return await draft_out(db, d, versions=True)


class ApproveIn(BaseModel):
    override_reason: str | None = Field(None, min_length=5)


@router.post("/studio/drafts/{did}/approve")
async def approve(did: uuid.UUID, body: ApproveIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    d = await _draft(db, did)
    try:
        await studio.mark_ready(db, d, body.override_reason)
    except studio.GateError as e:
        raise HTTPException(409, {"message": "Draft cannot reach Ready", "reasons": e.reasons}) from e
    except LookupError as e:
        raise HTTPException(409, str(e)) from e
    return await draft_out(db, d)


class ScheduleIn(BaseModel):
    scheduled_for: datetime | None = None
    evergreen: bool = False


@router.post("/studio/drafts/{did}/schedule")
async def schedule(did: uuid.UUID, body: ScheduleIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    d = await _draft(db, did)
    if d.status not in ("ready", "scheduled"):
        raise HTTPException(409, "approve the draft (Ready) before scheduling")
    if body.evergreen and not body.scheduled_for:
        d.evergreen, d.fresh_until = True, datetime.now(UTC) + timedelta(days=60)
    else:
        if not body.scheduled_for:
            raise HTTPException(422, "scheduled_for required (or evergreen=true)")
        d.scheduled_for, d.status = body.scheduled_for, "scheduled"
    return await draft_out(db, d)


@router.get("/studio/drafts/{did}/publish-assist")
async def assist(did: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    d = await _draft(db, did)
    if d.status not in ("ready", "scheduled", "published"):
        raise HTTPException(409, "only Ready or Scheduled drafts can be published")
    return studio.publish_assist(d, await studio.current_version(db, d))


class PublishedIn(BaseModel):
    url: str = Field(min_length=8)
    published_at: datetime | None = None


@router.post("/studio/drafts/{did}/published")
async def published(did: uuid.UUID, body: PublishedIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    """He posts manually (publish-assist), then taps Posted and pastes the URL (§7.10). Never auto-post."""
    d = await _draft(db, did)
    if d.status not in ("ready", "scheduled"):
        raise HTTPException(409, "draft must be Ready or Scheduled")
    pub = await studio.mark_published(db, d, body.url, body.published_at)
    return {"publication_id": str(pub.id), "draft": await draft_out(db, d)}


@router.get("/studio/board")
async def board(_: CurrentUser, db: DB) -> dict[str, list[dict[str, Any]]]:
    cols: dict[str, list[dict[str, Any]]] = {
        k: [] for k in ("idea", "drafting", "ready", "scheduled", "published", "measured")
    }
    for c in (
        await db.execute(
            select(ContentIdea)
            .where(ContentIdea.status == "idea")
            .order_by(desc(ContentIdea.created_at))
            .limit(30)
        )
    ).scalars():
        cols["idea"].append({"kind": "idea", **idea_out(c)})
    for d in (
        await db.execute(
            select(Draft).where(Draft.status != "archived").order_by(desc(Draft.updated_at)).limit(200)
        )
    ).scalars():
        cols.setdefault(d.status, []).append({"kind": "draft", **(await draft_out(db, d))})
    return cols


@router.get("/calendar")
async def calendar(_: CurrentUser, db: DB, start: dt.date | None = None, days: int = 14) -> dict[str, Any]:
    start = start or datetime.now(UTC).date() - timedelta(days=datetime.now(UTC).weekday())
    s_dt = datetime.combine(start, datetime.min.time(), UTC)
    e_dt = s_dt + timedelta(days=days)
    drafts = (
        await db.execute(select(Draft).where(Draft.scheduled_for >= s_dt, Draft.scheduled_for < e_dt))
    ).scalars()
    pubs = (
        await db.execute(
            select(Publication).where(Publication.published_at >= s_dt, Publication.published_at < e_dt)
        )
    ).scalars()
    goals = get_config().voice.goals_per_week
    week_start = s_dt
    progress = {}
    for p, goal in goals.items():
        n = (
            await db.execute(
                select(func.count())
                .select_from(Publication)
                .where(
                    Publication.platform.in_([p, "x_thread"] if p == "x" else [p]),
                    Publication.published_at >= week_start,
                    Publication.published_at < week_start + timedelta(days=7),
                )
            )
        ).scalar_one()
        progress[p] = {"goal": goal, "done": int(n)}
    series = [
        {"id": str(s.id), "name": s.name, "platform": s.platform, "cadence": s.cadence, "slot": s.slot}
        for s in (await db.execute(select(Series))).scalars()
    ]
    evergreen = [
        await draft_out(db, d)
        for d in (
            await db.execute(select(Draft).where(Draft.evergreen.is_(True), Draft.status == "ready"))
        ).scalars()
    ]
    return {
        "start": start.isoformat(),
        "days": days,
        "scheduled": [
            {"id": str(d.id), "platform": d.platform, "at": d.scheduled_for.isoformat()}
            for d in drafts
            if d.scheduled_for
        ],
        "published": [
            {"id": str(p.id), "platform": p.platform, "at": p.published_at.isoformat(), "url": p.url}
            for p in pubs
        ],
        "goals": progress,
        "series": series,
        "evergreen": evergreen,
    }


# ---------------- series ----------------
class SeriesIn(BaseModel):
    name: str
    platform: str
    cadence: str  # cron, e.g. "0 9 * * 5"
    template: str = ""
    slot: str = ""


@router.post("/series", status_code=201)
async def add_series(body: SeriesIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    from croniter import croniter

    if not croniter.is_valid(body.cadence):
        raise HTTPException(422, "cadence must be a cron expression")
    s = Series(**body.model_dump())
    db.add(s)
    await db.flush()
    return {"id": str(s.id), **body.model_dump()}


@router.get("/series")
async def list_series(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "platform": s.platform,
            "cadence": s.cadence,
            "template": s.template,
            "slot": s.slot,
        }
        for s in (await db.execute(select(Series))).scalars()
    ]


@router.delete("/series/{sid}")
async def del_series(sid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, bool]:
    s = await db.get(Series, sid)
    if s is None:
        raise HTTPException(404, "series not found")
    await db.delete(s)
    return {"deleted": True}


# ---------------- raw-material bank & reference posts ----------------
class RawIn(BaseModel):
    kind: Literal["story", "quote", "number", "failure", "mentor", "opinion"]
    text: str = Field(min_length=3)
    people: list[str] = []
    date: dt.date | None = None
    can_name: bool = False
    confidentiality: Literal["public", "vague-only", "private"] = "public"


def raw_out(r: RawMaterial) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "kind": r.kind,
        "text": r.text,
        "people": r.people,
        "date": r.date.isoformat() if r.date else None,
        "can_name": r.can_name,
        "confidentiality": r.confidentiality,
        "origin": r.origin,
    }


@router.get("/raw-materials")
async def list_raw(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    return [
        raw_out(r)
        for r in (await db.execute(select(RawMaterial).order_by(desc(RawMaterial.created_at)))).scalars()
    ]


@router.post("/raw-materials", status_code=201)
async def add_raw(body: RawIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    [v] = await get_embedder().embed([body.text])
    r = RawMaterial(**body.model_dump(), embedding=v)
    db.add(r)
    await db.flush()
    return raw_out(r)


@router.put("/raw-materials/{rid}")
async def put_raw(rid: uuid.UUID, body: RawIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    r = await db.get(RawMaterial, rid)
    if r is None:
        raise HTTPException(404, "not found")
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    [r.embedding] = await get_embedder().embed([body.text])
    return raw_out(r)


@router.delete("/raw-materials/{rid}")
async def del_raw(rid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, bool]:
    r = await db.get(RawMaterial, rid)
    if r is None:
        raise HTTPException(404, "not found")
    await db.delete(r)
    return {"deleted": True}


class RefIn(BaseModel):
    platform: str = "linkedin"
    text: str = Field(min_length=20)
    posted_at: datetime | None = None
    metrics: dict[str, Any] = {}
    is_own: bool = True


@router.get("/reference-posts")
async def list_refs(_: CurrentUser, db: DB) -> list[dict[str, Any]]:
    return [
        {"id": str(r.id), "platform": r.platform, "text": r.text, "is_own": r.is_own, "metrics": r.metrics}
        for r in (await db.execute(select(ReferencePost).order_by(desc(ReferencePost.created_at)))).scalars()
    ]


@router.post("/reference-posts", status_code=201)
async def add_ref(body: RefIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    [v] = await get_embedder().embed([body.text])
    r = ReferencePost(**body.model_dump(), embedding=v)
    db.add(r)
    await db.flush()
    own = (
        await db.execute(
            select(func.count()).select_from(ReferencePost).where(ReferencePost.is_own.is_(True))
        )
    ).scalar_one()
    await set_setting(db, "voice_calibrated", own >= 5)  # §0.3: STUDIO flags "voice not calibrated" until 5+
    return {"id": str(r.id), "own_posts": int(own), "voice_calibrated": own >= 5}


@router.delete("/reference-posts/{rid}")
async def del_ref(rid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, bool]:
    r = await db.get(ReferencePost, rid)
    if r is None:
        raise HTTPException(404, "not found")
    await db.delete(r)
    return {"deleted": True}


# ---------------- M5: visual assets, long-form export, API publishing ----------------
def asset_out(a: Any) -> dict[str, Any]:
    return {"id": str(a.id), "kind": a.kind, "meta": a.meta, "url": f"/assets/{a.id}"}


@router.post("/studio/drafts/{did}/render", status_code=201)
async def render_assets(did: uuid.UUID, _: CurrentUser, db: DB) -> list[dict[str, Any]]:
    from signal_core.render.renderer import RenderError
    from signal_core.studio.visual import render_draft

    try:
        assets = await render_draft(db, await _draft(db, did))
    except RenderError as e:
        raise HTTPException(422, str(e)) from e
    return [asset_out(a) for a in assets]


@router.get("/studio/drafts/{did}/assets")
async def list_assets(did: uuid.UUID, _: CurrentUser, db: DB) -> list[dict[str, Any]]:
    from signal_core.db.models import Asset

    rows = (await db.execute(select(Asset).where(Asset.draft_id == did).order_by(Asset.created_at))).scalars()
    return [asset_out(a) for a in rows]


@router.get("/assets/{aid}")
async def get_asset(aid: uuid.UUID, _: CurrentUser, db: DB) -> Any:
    from pathlib import Path

    from fastapi.responses import FileResponse

    from signal_core.db.models import Asset
    from signal_core.settings import get_settings

    a = await db.get(Asset, aid)
    if a is None:
        raise HTTPException(404, "asset not found")
    path = Path(a.path).resolve()
    root = (get_settings().data_dir / "assets").resolve()
    if root not in path.parents or not path.exists():  # never serve files outside the assets folder
        raise HTTPException(404, "asset file missing")
    media = {
        "png": "image/png",
        "pdf": "application/pdf",
        "md": "text/markdown",
        "svg": "image/svg+xml",
        "zip": "application/zip",
    }.get(a.kind, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=path.name)


@router.get("/studio/drafts/{did}/export.md")
async def export_md(did: uuid.UUID, _: CurrentUser, db: DB) -> Any:
    from fastapi.responses import PlainTextResponse

    d = await _draft(db, did)
    if d.platform != "hashnode":
        raise HTTPException(409, "Markdown export is for articles")
    v = await studio.current_version(db, d)
    return PlainTextResponse(
        v.body,
        media_type="text/markdown",
        headers={"content-disposition": 'attachment; filename="article.md"'},
    )


class PublishApiIn(BaseModel):
    confirm: bool = False  # explicit approval of THIS post (§7.10)


@router.post("/studio/drafts/{did}/publish-api")
async def publish_api(did: uuid.UUID, body: PublishApiIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    from signal_core.studio.visual import PublishError, publish_via_api

    try:
        return await publish_via_api(db, await _draft(db, did), body.confirm, transport=_hashnode_transport)
    except PublishError as e:
        raise HTTPException(409, str(e)) from e


_hashnode_transport: Any = None  # tests inject a mock transport here


class CardIn(BaseModel):
    kind: Literal["quote_card", "stat_card"]
    title: str = Field(min_length=1, max_length=200)
    body: str = Field("", max_length=300)
    source: str | None = None


@router.post("/studio/cards", status_code=201)
async def make_card(body: CardIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    from signal_core.studio.visual import render_card

    a = await render_card(db, body.kind, body.title, body.body, body.source, uuid.uuid4().hex[:12])
    return asset_out(a)
