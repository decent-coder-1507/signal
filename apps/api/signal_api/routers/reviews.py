"""Weekly/monthly review flows (§10.1, §14 Reviews) + Telegram webhook (§13)."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import desc, select

from signal_api.deps import DB, CurrentUser
from signal_core.brief import habit
from signal_core.db.models import Brief, Routine
from signal_core.routines.engine import execute
from signal_core.settings import get_settings

router = APIRouter(tags=["reviews"])


def review_out(b: Brief) -> dict[str, Any]:
    return {
        "id": str(b.id),
        "kind": b.kind,
        "period_start": b.period_start.isoformat(),
        "period_end": b.period_end.isoformat(),
        "content": b.content,
        "completed_at": b.completed_at.isoformat() if b.completed_at else None,
    }


async def _review(db: DB, rid: uuid.UUID) -> Brief:
    b = await db.get(Brief, rid)
    if b is None or b.kind not in ("weekly", "monthly"):
        raise HTTPException(404, "review not found")
    return b


@router.get("/reviews/latest")
async def latest(
    _: CurrentUser, db: DB, kind: Literal["weekly", "monthly"] = "weekly"
) -> dict[str, Any] | None:
    b = (
        (await db.execute(select(Brief).where(Brief.kind == kind).order_by(desc(Brief.created_at)).limit(1)))
        .scalars()
        .first()
    )
    return review_out(b) if b else None


@router.post("/reviews/generate", status_code=201)
async def generate(_: CurrentUser, db: DB, kind: Literal["weekly", "monthly"] = "weekly") -> dict[str, Any]:
    name = "weekly_review" if kind == "weekly" else "monthly_review"
    r = (await db.execute(select(Routine).where(Routine.name == name))).scalar_one_or_none()
    if r is None:
        raise HTTPException(404, f"routine {name} not found")
    run = await execute(db, r, datetime.now(UTC))
    bid = run.outputs.get("_review_brief_id")
    if not bid:
        raise HTTPException(500, f"review run produced no document: {run.log[-500:]}")
    return review_out(await _review(db, uuid.UUID(bid)))


@router.get("/reviews/{rid}")
async def get_review(rid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    return review_out(await _review(db, rid))


class StepIn(BaseModel):
    key: str
    data: dict[str, Any] = {}


@router.post("/reviews/{rid}/step")
async def complete_step(rid: uuid.UUID, body: StepIn, _: CurrentUser, db: DB) -> dict[str, Any]:
    b = await _review(db, rid)
    flow = b.content.get("flow", [])
    if body.key not in flow:
        raise HTTPException(422, f"unknown step {body.key!r}; flow is {flow}")
    created = 0
    if body.key == "content_plan" and body.data.get("accept"):
        from signal_core.studio.service import create_angles

        for sid in body.data["accept"][:7]:
            created += len(await create_angles(db, "story", uuid.UUID(sid)))
    done = sorted({*b.content.get("done_steps", []), body.key}, key=flow.index)
    b.content = {**b.content, "done_steps": done}
    return {**review_out(b), "angles_created": created}


@router.post("/reviews/{rid}/complete")
async def complete(rid: uuid.UUID, _: CurrentUser, db: DB) -> dict[str, Any]:
    b = await _review(db, rid)
    missing = [s for s in b.content.get("flow", []) if s not in b.content.get("done_steps", [])]
    if missing:
        raise HTTPException(409, {"message": "finish the remaining steps first", "missing": missing})
    b.completed_at = datetime.now(UTC)
    await habit.mark(db, b.completed_at, "action")
    return review_out(b)


@router.get("/reviews/{rid}/pdf")
async def pdf(rid: uuid.UUID, _: CurrentUser, db: DB) -> Response:
    from signal_core.notify.email import render

    b = await _review(db, rid)
    _subject, html = render(b.kind, {"content": b.content})
    import os

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=None if os.environ.get("CI") else "chrome", headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="load")
        data = await page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"},
        )
        await browser.close()
    return Response(
        data,
        media_type="application/pdf",
        headers={"content-disposition": f'attachment; filename="signal-{b.kind}-review.pdf"'},
    )


# ---------------- Telegram webhook (HTTPS deployments; local mode uses long polling) ----------------
@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: DB) -> dict[str, Any]:
    from signal_core.notify.telegram import handle_update
    from signal_core.services.settings_store import get_setting

    expected = await get_setting(db, "telegram_webhook_secret", "")
    got = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not expected or not secrets.compare_digest(str(expected), got):
        raise HTTPException(401, "bad webhook secret")
    if not get_settings().telegram_bot_token:
        raise HTTPException(503, "telegram not configured")
    return await handle_update(db, await request.json())
