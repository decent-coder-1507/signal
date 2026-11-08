"""Brief routine steps (§10.1): assemble_brief, plus the instant watch check."""

from __future__ import annotations

from typing import Any

from signal_core.brief.assemble import assemble
from signal_core.radar.watches import check_watches
from signal_core.routines.engine import StepContext, step


@step("assemble_brief")
async def step_assemble(ctx: StepContext) -> dict[str, Any]:
    await check_watches(ctx.session, ctx.now, ctx.run.id)
    kind = "weekend" if "weekend" in ctx.routine.name else "daily"
    from signal_core.ops.metrics import BRIEF_SECONDS

    with BRIEF_SECONDS.time():
        b = await assemble(ctx.session, ctx.now, kind, ctx.params, ctx.run.id)
    return {
        "brief_id": str(b.id),
        "kind": b.kind,
        "stories": len(b.content["stories"]),
        "degraded": b.degraded,
    }


@step("check_watches")
async def step_watches(ctx: StepContext) -> dict[str, Any]:
    st = await check_watches(ctx.session, ctx.now, ctx.run.id)
    return {"checked": st.checked, "hits": st.hits, "notified": st.notified}
