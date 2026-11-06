"""RADAR processing after ingest: enrich → cluster → score → insights. Used by routine steps and the demo."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.llm import budget as budget_mod
from signal_core.radar.cluster import cluster_pending, merge_pass
from signal_core.radar.enrich import enrich_pending
from signal_core.radar.insight import generate_insights
from signal_core.radar.scoring import score_stories
from signal_core.settings import get_settings


async def process(
    session: AsyncSession, now: datetime, run_id: uuid.UUID | None = None, insights: bool = True
) -> dict[str, Any]:
    cfg = get_config()
    e = await enrich_pending(session, now, run_id)
    c = await cluster_pending(session, now)
    ranked = await score_stories(session, now, run_id)
    out: dict[str, Any] = {
        "enriched": e.enriched,
        "rejected_facts": e.rejected_facts,
        "stories_created": c.created,
        "items_joined": c.joined,
        "primary_traced": c.traced_primary,
        "stories_scored": len(ranked),
        "llm_unavailable": e.skipped_unavailable > 0,
    }
    if insights:
        st = await budget_mod.status(session, cfg.budget, get_settings().timezone, now)
        top_n = min(cfg.scoring.insight_top_n, st.insight_cap or cfg.scoring.insight_top_n)
        pool = [s for s in ranked if s.final_score > -0.5][:top_n]
        ins = await generate_insights(session, pool, run_id)
        out.update(
            {
                "insights": ins.generated,
                "titled": ins.titled,
                "uncited_dropped": ins.dropped_sentences,
                "insight_cap": top_n,
            }
        )
    return out


async def nightly(session: AsyncSession, now: datetime, run_id: uuid.UUID | None = None) -> dict[str, Any]:
    from signal_core.radar.preference import retrain

    merged = await merge_pass(session, now, run_id)
    pm = await retrain(session)
    return {"merged": merged, "preference_model": pm.version if pm else None}
