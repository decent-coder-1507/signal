"""Analytics routine steps: metrics_prompts (+48 h / +7 d) and content_learnings (monthly P16 proposal)."""

from __future__ import annotations

from typing import Any

from signal_core.analytics.service import propose_learnings, send_prompts
from signal_core.routines.engine import StepContext, step


@step("metrics_prompts")
async def step_metrics_prompts(ctx: StepContext) -> dict[str, Any]:
    return {"prompted": await send_prompts(ctx.session, ctx.now)}


@step("content_learnings")
async def step_learnings(ctx: StepContext) -> dict[str, Any]:
    p = await propose_learnings(ctx.session, ctx.now, ctx.run.id)
    return {"proposal_id": p["id"], "findings": p["findings"][:3]}
