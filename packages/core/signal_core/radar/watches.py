"""Topic watches (§6.10): natural-language alerts checked against new/updated stories.

Candidate stories: updated since the watch was last checked, embedding similar to the watch query (per-embedder
floor) and passing optional keyword/entity filters. Candidates get a fast-tier LLM condition check. Instant watches
notify immediately (in-app now, Telegram in M8); digest watches surface in the next brief.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import ItemEnrichment, Notification, Story, StoryItem, Watch, WatchHit
from signal_core.embeddings import cosine, get_embedder
from signal_core.llm import router as llm
from signal_core.llm.provider import BudgetExceeded, LLMError

SIM_FLOOR = {"mock": 0.15, "fastembed": 0.55}


@dataclass
class WatchStats:
    checked: int = 0
    candidates: int = 0
    hits: int = 0
    notified: int = 0


async def create_watch(
    session: AsyncSession,
    query: str,
    urgency: str = "digest",
    filters: dict[str, Any] | None = None,
    expires_at: datetime | None = None,
) -> Watch:
    [vec] = await get_embedder().embed([query])
    w = Watch(query=query, embedding=vec, urgency=urgency, filters=filters or {}, expires_at=expires_at)
    session.add(w)
    await session.flush()
    return w


def _passes_filters(w: Watch, story: Story) -> bool:
    f = w.filters or {}
    hay = (story.title + " " + " ".join(story.entity_names or [])).lower()
    kws = [k.lower() for k in f.get("keywords", [])]
    ents = [e.lower() for e in f.get("entities", [])]
    if kws and not any(k in hay for k in kws):
        return False
    return not (ents and not any(e in hay for e in ents))


async def check_watches(session: AsyncSession, now: datetime, run_id: uuid.UUID | None = None) -> WatchStats:
    st = WatchStats()
    floor = SIM_FLOOR.get(get_embedder().name, 0.5)
    watches = list((await session.execute(select(Watch).where(Watch.enabled.is_(True)))).scalars())
    for w in watches:
        if w.expires_at and w.expires_at < now:
            w.enabled = False
            continue
        st.checked += 1
        since = (w.filters or {}).get("_last_checked")
        since_dt = datetime.fromisoformat(since) if since else now - timedelta(days=2)
        stories = list(
            (
                await session.execute(
                    select(Story).where(
                        Story.status == "active",
                        Story.last_updated >= since_dt - timedelta(hours=36),
                        Story.centroid.is_not(None),
                    )
                )
            ).scalars()
        )
        done = set(
            (await session.execute(select(WatchHit.story_id).where(WatchHit.watch_id == w.id))).scalars()
        )
        for s in stories:
            if s.id in done or not _passes_filters(w, s):
                continue
            if w.embedding is not None and cosine(list(w.embedding), list(s.centroid)) < floor:
                continue
            st.candidates += 1
            summaries = list(
                (
                    await session.execute(
                        select(ItemEnrichment.summary_1line)
                        .join(StoryItem, StoryItem.item_id == ItemEnrichment.item_id)
                        .where(StoryItem.story_id == s.id)
                        .limit(4)
                    )
                ).scalars()
            )
            try:
                r = await llm.call(
                    "watch_check",
                    {"query": w.query, "story": {"title": s.title, "summaries": summaries}},
                    session=session,
                    run_id=run_id,
                )
            except (LLMError, BudgetExceeded):
                return st
            if not r.output.triggered:
                continue
            hit = WatchHit(watch_id=w.id, story_id=s.id, explanation=r.output.explanation)
            session.add(hit)
            w.last_triggered = now
            st.hits += 1
            if w.urgency == "instant":
                session.add(
                    Notification(
                        channel="app",
                        kind="watch",
                        status="sent",
                        sent_at=now,
                        payload={
                            "watch": w.query,
                            "story_id": str(s.id),
                            "title": s.title,
                            "explanation": r.output.explanation,
                        },
                    )
                )
                hit.notified_at = now
                st.notified += 1
        w.filters = {**(w.filters or {}), "_last_checked": now.isoformat()}
    await session.flush()
    return st
