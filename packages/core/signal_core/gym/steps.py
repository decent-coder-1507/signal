"""GYM / Moat routine steps: gym_item (daily learn item), cards_due_check, learn_next (weekly), quiz, skill_progress,
moat_radar (monthly)."""

from __future__ import annotations

from typing import Any

from signal_core.gym import moat
from signal_core.gym import service as gym
from signal_core.routines.engine import StepContext, step


@step("gym_item")
async def step_gym_item(ctx: StepContext) -> dict[str, Any]:
    """Daily learn item: an explainer (engineer depth) for the top learn-next skill, which also seeds cards."""
    ln = await gym.learn_next(ctx.session, ctx.now, ctx.run.id)
    if not ln["items"]:
        return {"explainer": None}
    top = ln["items"][0]
    ex, cards = await gym.explainer(ctx.session, top["plan"]["explainer_topic"] or top["skill"], "engineer")
    return {"skill": top["skill"], "explainer_id": str(ex.id), "cards": len(cards)}


@step("cards_due_check")
async def step_cards_due(ctx: StepContext) -> dict[str, Any]:
    return {"due": len(await gym.due_cards(ctx.session, ctx.now))}


@step("learn_next")
async def step_learn_next(ctx: StepContext) -> dict[str, Any]:
    ln = await gym.learn_next(ctx.session, ctx.now, ctx.run.id)
    return {"items": [i["skill"] for i in ln["items"]]}


@step("quiz")
async def step_quiz(ctx: StepContext) -> dict[str, Any]:
    q = await gym.build_quiz(ctx.session)
    return {"quiz_id": str(q.id), "questions": len(q.questions)}


@step("skill_progress")
async def step_progress(ctx: StepContext) -> dict[str, Any]:
    return await gym.progress(ctx.session, ctx.now)


@step("moat_radar")
async def step_moat(ctx: StepContext) -> dict[str, Any]:
    r = await moat.generate(ctx.session, ctx.now, None, ctx.run.id)
    return {
        "radar_id": str(r.id),
        "commoditising": len(r.content.get("commoditising", [])),
        "appreciating": len(r.content.get("appreciating", [])),
    }
