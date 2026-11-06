"""Story insights (§6.7, P2) for the candidate pool, plus generated story titles (§6.6).

Every factual sentence must cite [item_id] of a story member; unknown ids are stripped and uncited factual
sentences dropped before storage (§9.8). Insights are regenerated when a story materially changes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.base import OWNER_ID
from signal_core.db.models import Item, ItemEnrichment, Profile, Source, Story, StoryInsight, StoryItem
from signal_core.llm import router as llm
from signal_core.llm.provider import BudgetExceeded, LLMError
from signal_core.logging import get_logger
from signal_core.truth import check_citations, drop_uncited_sentences, strip_unknown_citations

log = get_logger("insight")
ROLE_ORDER = {"primary": 0, "report": 1, "followup": 2, "reaction": 3}


@dataclass
class InsightStats:
    generated: int = 0
    titled: int = 0
    dropped_sentences: int = 0
    skipped_unavailable: bool = False


async def latest_insight(session: AsyncSession, story_id: uuid.UUID) -> StoryInsight | None:
    return (
        (
            await session.execute(
                select(StoryInsight)
                .where(StoryInsight.story_id == story_id)
                .order_by(StoryInsight.version.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def story_items(
    session: AsyncSession, story_id: uuid.UUID
) -> list[tuple[StoryItem, Item, Source, ItemEnrichment | None]]:
    rows = (
        await session.execute(
            select(StoryItem, Item, Source, ItemEnrichment)
            .join(Item, Item.id == StoryItem.item_id)
            .join(Source, Source.id == Item.source_id)
            .outerjoin(ItemEnrichment, ItemEnrichment.item_id == Item.id)
            .where(StoryItem.story_id == story_id)
        )
    ).all()
    return sorted(
        [(a, b, c, d) for a, b, c, d in rows],
        key=lambda r: (ROLE_ORDER.get(r[0].role, 9), r[2].tier, r[1].published_at or datetime.min),
    )


def needs_insight(story: Story, ins: StoryInsight | None) -> bool:
    if ins is None:
        return True
    return bool(story.material_update_at and story.material_update_at > ins.created_at)


async def generate_insights(
    session: AsyncSession, stories: list[Story], run_id: uuid.UUID | None = None, force: bool = False
) -> InsightStats:
    st = InsightStats()
    prof = (await session.execute(select(Profile).where(Profile.user_id == OWNER_ID))).scalar_one_or_none()
    owner = get_config().profile.owner
    pinfo = {
        "name": owner.name,
        "role": prof.role if prof else owner.role,
        "goals": prof.goals if prof else owner.goals,
        "stack": prof.stack if prof else owner.stack,
        "context": "",
    }  # VANCO context is sensitive: only sent when the user enables it (§16.2)
    for s in stories:
        ins = await latest_insight(session, s.id)
        if not force and not needs_insight(s, ins):
            continue
        rows = await story_items(session, s.id)
        if not rows:
            continue
        items = [
            {
                "item_id": str(it.id),
                "source": src.name,
                "tier": src.tier,
                "primary": si.role == "primary",
                "title": it.title,
                "text": " ".join((it.text or it.title).split()[:350]),
            }
            for si, it, src, _e in rows[:6]
        ]
        allowed = {str(it.id) for _si, it, _src, _e in rows}
        try:
            if len(rows) > 1 and (s.title == rows[0][1].title or not (s.scores or {}).get("titled")):
                t = await llm.call(
                    "story_title", {"titles": [r[1].title for r in rows[:6]]}, session=session, run_id=run_id
                )
                s.title = t.output.title[:500]
                s.scores = {**(s.scores or {}), "titled": True}
                st.titled += 1
            r = await llm.call(
                "story_insight",
                {"profile": pinfo, "items": items, "related": []},
                session=session,
                run_id=run_id,
            )
        except (LLMError, BudgetExceeded) as e:
            log.warning("insight_unavailable", story=str(s.id), error=str(e))
            st.skipped_unavailable = True
            break
        o = r.output
        what = drop_uncited_sentences(o.what_happened, allowed)
        changes = strip_unknown_citations(o.what_changes, allowed)
        st.dropped_sentences += len(check_citations(o.what_happened, allowed).uncited)
        if not what:  # nothing verifiable survived → fall back to extractive, cited summaries
            what = " ".join(
                f"{(e.summary_1line if e else it.title)} [{it.id}]" for _si, it, _src, e in rows[:3]
            )
        version = (
            (
                await session.execute(
                    select(func.max(StoryInsight.version)).where(StoryInsight.story_id == s.id)
                )
            ).scalar()
            or 0
        ) + 1
        citations = [
            {
                "id": str(it.id),
                "title": it.title,
                "url": it.canonical_url,
                "source": src.name,
                "tier": src.tier,
                "role": si.role,
            }
            for si, it, src, _e in rows
        ]
        session.add(
            StoryInsight(
                story_id=s.id,
                version=version,
                what_happened=what,
                why_you=o.why_it_matters_to_you,
                what_changes=changes,
                hype_verdict=o.hype_verdict,
                hype_reasons=o.hype_reasons,
                durability=o.durability,
                durability_reason=o.durability_reason,
                moat_note=o.moat_note,
                open_questions=o.open_questions,
                actions=[a.model_dump(exclude_none=True) for a in o.actions],
                confidence=o.confidence,
                confidence_reason=o.confidence_reason,
                reading_time=o.reading_time,
                uncertainty_labels=o.uncertainty_labels,
                citations=citations,
                prompt_version=r.prompt_version,
                model=r.model,
            )
        )
        s.durability, s.hype_verdict = o.durability, o.hype_verdict
        st.generated += 1
        await session.flush()
    return st


async def degraded_insight(session: AsyncSession, s: Story) -> StoryInsight:
    """No-LLM fallback (§16.4): extractive, cited summary from enrichments or titles."""
    rows = await story_items(session, s.id)
    what = " ".join(f"{(e.summary_1line if e else it.title)} [{it.id}]" for _si, it, _src, e in rows[:3])
    version = (
        (
            await session.execute(select(func.max(StoryInsight.version)).where(StoryInsight.story_id == s.id))
        ).scalar()
        or 0
    ) + 1
    ins = StoryInsight(
        story_id=s.id,
        version=version,
        what_happened=what,
        why_you="Degraded mode: AI analysis unavailable; ranked by deterministic scores.",
        what_changes="",
        hype_verdict="too_early",
        durability=s.durability or "trend",
        citations=[
            {
                "id": str(it.id),
                "title": it.title,
                "url": it.canonical_url,
                "source": src.name,
                "tier": src.tier,
                "role": si.role,
            }
            for si, it, src, _e in rows
        ],
        degraded=True,
        prompt_version="extractive",
        model="none",
        confidence=0.3,
        uncertainty_labels=["AI analysis unavailable"],
    )
    session.add(ins)
    await session.flush()
    return ins
