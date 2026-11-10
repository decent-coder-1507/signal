"""Delivery of routine outputs to channels (§10.1 'Delivery' column) + notification maintenance steps."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from signal_core.db.models import Brief
from signal_core.notify.dispatcher import dispatch, flush_queued
from signal_core.routines.engine import StepContext, step

BRIEF_TITLES = {
    "daily": "Your daily brief is ready",
    "weekend": "Your weekend brief is ready",
    "catchup": "While you were away: your catch-up brief is ready",
}


async def _in_app(ctx: StepContext, brief_id: str | None, review: dict[str, Any] | None) -> dict[str, str]:
    """In-app channel (ADR-027): a small 'ready' notification the bell and browser notifications pick up."""
    outs = ctx.outputs
    if brief_id:
        b = await ctx.session.get(Brief, uuid.UUID(brief_id))
        if b is not None:
            title = BRIEF_TITLES.get(b.kind, "Your brief is ready")
            n = len(b.content.get("stories", []))
            payload = {"brief_id": brief_id, "title": f"{title} ({n} stories)" if n else title}
            await dispatch(ctx.session, "app", "brief", payload, ctx.now)
            return {"app:brief": "sent"}
    elif "cards_due_check" in outs and outs["cards_due_check"].get("due", 0) > 0:
        due = int(outs["cards_due_check"]["due"])
        await dispatch(
            ctx.session, "app", "cards", {"due": due, "title": f"{due} cards due for review"}, ctx.now
        )
        return {"app:cards": "sent"}
    elif review and review.get("brief_id"):
        b = await ctx.session.get(Brief, uuid.UUID(review["brief_id"]))
        if b is not None:
            payload = {"brief_id": str(b.id), "title": f"Your {b.kind} review is ready"}
            await dispatch(ctx.session, "app", b.kind, payload, ctx.now)
            return {f"app:{b.kind}": "sent"}
    return {}


async def deliver(ctx: StepContext) -> dict[str, Any]:
    """Called by the engine after a routine's steps: push the outputs to the routine's channels."""
    sent: dict[str, str] = {}
    outs = ctx.outputs
    brief_id = (outs.get("assemble_brief") or {}).get("brief_id")
    review = outs.get("weekly_recap") or outs.get("state_of_tech")
    if "app" in (ctx.routine.channels or []):
        sent.update(await _in_app(ctx, brief_id, review))
    channels = [c for c in ctx.routine.channels or [] if c != "app"]
    for ch in channels:
        if brief_id:
            b = await ctx.session.get(Brief, uuid.UUID(brief_id))
            if b is not None:
                n = await dispatch(
                    ctx.session, ch, "brief", {"brief_id": brief_id, "content": b.content}, ctx.now
                )
                sent[f"{ch}:brief"] = n.status
        elif "cards_due_check" in outs and outs["cards_due_check"].get("due", 0) > 0:
            n = await dispatch(ctx.session, ch, "cards", {"due": outs["cards_due_check"]["due"]}, ctx.now)
            sent[f"{ch}:cards"] = n.status
        elif review and review.get("brief_id"):
            b = await ctx.session.get(Brief, uuid.UUID(review["brief_id"]))
            if b is not None:
                n = await dispatch(
                    ctx.session, ch, b.kind, {"brief_id": str(b.id), "content": b.content}, ctx.now
                )
                sent[f"{ch}:{b.kind}"] = n.status
    return sent


@step("flush_notifications")
async def step_flush(ctx: StepContext) -> dict[str, Any]:
    return {"sent": await flush_queued(ctx.session, ctx.now)}


@step("publish_assist_nudges")
async def step_publish_nudges(ctx: StepContext) -> dict[str, Any]:
    """Content nudge (§10.1): at a scheduled slot, push the ready draft with copy + composer link."""
    from datetime import timedelta

    from signal_core.db.models import Draft
    from signal_core.studio.service import current_version, publish_assist

    due = list(
        (
            await ctx.session.execute(
                select(Draft).where(
                    Draft.status == "scheduled",
                    Draft.scheduled_for <= ctx.now,
                    Draft.scheduled_for > ctx.now - timedelta(hours=2),
                )
            )
        ).scalars()
    )
    n = 0
    for d in due:
        if (d.ready_override or {}).get("_nudged"):
            continue
        pa = publish_assist(d, await current_version(ctx.session, d))
        await dispatch(
            ctx.session, "telegram", "publish_assist", {**pa, "draft_id": str(d.id)}, ctx.now, urgent=True
        )
        await dispatch(ctx.session, "app", "publish_assist", {**pa, "draft_id": str(d.id)}, ctx.now)
        d.ready_override = {**(d.ready_override or {}), "_nudged": ctx.now.isoformat()}
        n += 1
    return {"nudged": n}
