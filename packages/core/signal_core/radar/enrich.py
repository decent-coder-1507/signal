"""enrich_item (§6.3 step 5, §6.4): batched P1 enrichment with verbatim quote-span validation."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.base import OWNER_ID, uuid7
from signal_core.db.models import Entity, Item, ItemEnrichment, ItemEntity, Source
from signal_core.db.session import session_scope
from signal_core.llm import router as llm
from signal_core.llm.provider import BudgetExceeded, LLMUnavailable
from signal_core.logging import get_logger
from signal_core.ops.metrics import ITEMS_ENRICHED
from signal_core.truth import validate_key_facts

log = get_logger("enrich")
BATCH = 15
TEXT_WORDS = 1500
ENTITY_TYPES = {
    "companies": "company",
    "people": "person",
    "products": "product",
    "models": "model",
    "repos": "repo",
    "papers": "paper",
}


@dataclass
class EnrichStats:
    enriched: int = 0
    rejected_facts: int = 0
    skipped_unavailable: int = 0
    batches: int = 0


def _clip(text: str, words: int = TEXT_WORDS) -> str:
    w = text.split()
    return " ".join(w[:words])


async def pending_items(session: AsyncSession, limit: int = 300, now: datetime | None = None) -> list[Item]:
    """Captures first, then the last 48 h (what the next brief needs), then by prefilter score."""
    fresh = Item.published_at >= (now or datetime.now(UTC)) - timedelta(hours=48)
    q = (
        select(Item)
        .outerjoin(ItemEnrichment, ItemEnrichment.item_id == Item.id)
        .where(Item.status == "new", Item.prefilter_score.is_not(None), ItemEnrichment.id.is_(None))
        .order_by(Item.is_capture.desc(), fresh.desc().nulls_last(), Item.prefilter_score.desc().nulls_last())
        .limit(limit)
    )
    return list((await session.execute(q)).scalars())


async def upsert_entity(session: AsyncSession, etype: str, name: str) -> uuid.UUID:
    name = name.strip()[:255]
    stmt = (
        insert(Entity)
        .values(id=uuid7(), user_id=OWNER_ID, type=etype, name=name, aliases=[])
        .on_conflict_do_nothing(index_elements=["user_id", "type", "name"])
        .returning(Entity.id)
    )
    eid = (await session.execute(stmt)).scalar_one_or_none()
    if eid is None:
        eid = (
            await session.execute(select(Entity.id).where(Entity.type == etype, Entity.name == name))
        ).scalar_one()
    return eid


def enrich_topics() -> list[str]:
    return [
        t.name for ring in ("core", "adjacent", "wide") for t in getattr(get_config().profile.topics, ring)
    ]


def enrich_inputs(batch: list[Item], sources: dict[uuid.UUID, Source], topics: list[str]) -> dict[str, Any]:
    """P1 inputs for one batch (also the LLM cache key, so the benchmark builder can pre-warm it in parallel)."""
    payload = [
        {
            "item_id": str(i.id),
            "title": i.title,
            "text": _clip(i.text or i.title),
            "source": sources[i.source_id].name if i.source_id in sources else "?",
            "tier": sources[i.source_id].tier if i.source_id in sources else 3,
            "ring": sources[i.source_id].ring if i.source_id in sources else "core",
            "content_type": i.content_type,
            "prefilter": (i.signal_meta or {}).get("prefilter"),
        }
        for i in batch
    ]
    return {"topics": topics, "items": payload}


async def enrich_pending(
    session: AsyncSession,
    now: datetime,
    run_id: uuid.UUID | None = None,
    limit: int = 300,
    items: list[Item] | None = None,
) -> EnrichStats:
    """Enrich pending items (or exactly `items`, used by the benchmark builder) in batches of BATCH."""
    st = EnrichStats()
    items = await pending_items(session, limit, now) if items is None else items
    if not items:
        return st
    topics = enrich_topics()
    sources = {s.id: s for s in (await session.execute(select(Source))).scalars()}
    by_id = {str(i.id): i for i in items}
    batches = [items[k : k + BATCH] for k in range(0, len(items), BATCH)]

    async def call(batch: list[Item]) -> Any:
        # Independent LLM calls run concurrently (the runner caps parallel `claude -p`); each on its own session.
        async with session_scope() as s:
            return await llm.call(
                "enrich_items", enrich_inputs(batch, sources, topics), session=s, run_id=run_id
            )

    results = await asyncio.gather(*(call(b) for b in batches), return_exceptions=True)
    for batch, res in zip(batches, results, strict=True):
        if isinstance(res, (LLMUnavailable, BudgetExceeded)):
            log.warning("enrich_unavailable", error=str(res))
            st.skipped_unavailable += len(batch)
            continue  # items stay 'new'; the brief degrades gracefully (§16.4)
        if isinstance(res, BaseException):
            raise res
        st.batches += 1
        for out in res.output.items:
            item = by_id.get(out.item_id)
            if item is None:  # model hallucinated an id → ignore
                continue
            fc = validate_key_facts([f.model_dump() for f in out.key_facts], item.text or item.title)
            st.rejected_facts += len(fc.rejected)
            ents = out.entities.model_dump()
            # Entities must literally appear in the item (anti-hallucination).
            hay = (item.title + " " + (item.text or "")).lower()
            ents = {k: [n for n in v if n and n.lower() in hay] for k, v in ents.items()}
            session.add(
                ItemEnrichment(
                    item_id=item.id,
                    summary_1line=out.summary_1line,
                    summary_short=out.summary_short,
                    key_facts=fc.kept,
                    entities=ents,
                    topics=out.topics[:6],
                    ring=out.ring,
                    enrich_content_type=out.content_type,
                    tech_relevance=out.tech_relevance,
                    claims=out.claims_needing_verification,
                    is_primary_source=out.is_primary_source,
                    rejected_facts=len(fc.rejected),
                    prompt_version=res.prompt_version,
                    model=res.model,
                )
            )
            for key, names in ents.items():
                for n in names[:8]:
                    eid = await upsert_entity(session, ENTITY_TYPES[key], n)
                    await session.execute(
                        insert(ItemEntity)
                        .values(id=uuid7(), user_id=OWNER_ID, item_id=item.id, entity_id=eid)
                        .on_conflict_do_nothing()
                    )
            if out.is_primary_source:
                item.primary_source = True
            item.status = "enriched"
            st.enriched += 1
            ITEMS_ENRICHED.inc()
        await session.flush()
    return st
