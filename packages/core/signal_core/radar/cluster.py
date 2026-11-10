"""Story clustering and timelines (§6.6).

Incremental: each enriched item joins the best active story (updated within window_days) whose centroid cosine
≥ join_threshold AND whose entities are compatible; otherwise it starts a new story. Entity compatibility: if both
sides name *specific* entities (models, products, repos, papers) they must share one; otherwise ≥1 shared entity of
any type (min_entity_overlap). This separates "Nimbus-4 launch" from "Nimbus-3 price cut" even though both mention
the same company (ADR-015).

Nightly merge: active stories with centroid cosine ≥ merge_threshold and compatible entities are merged; borderline
pairs (within 0.05 below the threshold, sharing a specific entity) go to the fast-tier LLM tie-breaker.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.config.schemas import ClusterCfg
from signal_core.db.models import Item, ItemEnrichment, Source, Story, StoryItem
from signal_core.embeddings import cosine, get_embedder, mean_vec
from signal_core.llm import router as llm
from signal_core.llm.provider import BudgetExceeded, LLMError
from signal_core.logging import get_logger

log = get_logger("cluster")
SPECIFIC = ("model", "product", "repo", "paper")
REACTION_SOURCES = ("hn", "reddit", "x")
URL_RX = re.compile(r"https?://[^\s)\]>\"']+")
ARXIV_RX = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|/papers/)(\d{4}\.\d{4,5})")


DASHES = re.compile(r"[‐-―−]")
CORP_SUFFIX = re.compile(r"\s+(inc|ltd|limited|llc|corp|corporation|plc|gmbh)\.?$")


def norm_tag(tag: str) -> str:
    """Canonical entity tag (ADR-026): unicode dashes → '-', '-'/'_' → space, vendor prefix dropped from model and
    product ids ("openai/gpt-live-1" → "gpt live 1"), corporate suffixes dropped ("eMudhra Limited" → "emudhra").
    On the real-data benchmark, spelling variants were the main reason same-event pairs failed the entity rule."""
    kind, _, name = tag.partition(":")
    n = DASHES.sub("-", name.strip().lower())
    if kind in ("model", "product") and "/" in n:
        n = n.rsplit("/", 1)[1]
    if kind != "repo":
        n = re.sub(r"[-_\s]+", " ", n).strip()
    if kind == "company":
        n = CORP_SUFFIX.sub("", n)
    return f"{kind}:{n}"


def entity_tags(entities: dict[str, list[str]]) -> list[str]:
    m = {
        "companies": "company",
        "people": "person",
        "products": "product",
        "models": "model",
        "repos": "repo",
        "papers": "paper",
    }
    return sorted(
        {norm_tag(f"{m[k]}:{n}") for k, v in (entities or {}).items() if k in m for n in v if n and n.strip()}
    )


def _same_name(a: str, b: str) -> bool:
    """Specific names match if equal, or one is a whole-word part of the other and has ≥ 2 words
    ("gemini 3.8 live" ⊂ "gemini 3.8 live extended thinking"; "python" ⊄ "python 3.15")."""
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short.split()) >= 2 and f" {short} " in f" {long_} "


def compatible(a: list[str], b: list[str], min_overlap: int) -> bool:
    sa, sb = {norm_tag(t) for t in a}, {norm_tag(t) for t in b}
    spec_a = {t.split(":", 1)[1] for t in sa if t.split(":", 1)[0] in SPECIFIC}
    spec_b = {t.split(":", 1)[1] for t in sb if t.split(":", 1)[0] in SPECIFIC}
    if spec_a and spec_b:
        if any(_same_name(x, y) for x in spec_a for y in spec_b):
            return True
        # Specific names differ, but two shared companies/people still tie the reports together (ADR-026).
        return len(sa & sb) >= 2
    if not sa or not sb:
        return True  # nothing to contradict; rely on cosine alone
    return len(sa & sb) >= min_overlap


def cfg_now() -> ClusterCfg:
    return get_config().scoring.cluster_for(get_embedder().name)


def role_for(item: Item, src: Source | None, story: Story | None, enr: ItemEnrichment | None) -> str:
    if item.primary_source or (enr and enr.is_primary_source):
        return "primary"
    if (src and src.type in REACTION_SOURCES) or item.content_type == "post":
        return "reaction"
    if story and item.published_at and item.published_at > story.first_seen + timedelta(hours=24):
        return "followup"
    return "report"


async def story_sources(session: AsyncSession, story_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await session.execute(
        select(Item.source_id)
        .join(StoryItem, StoryItem.item_id == Item.id)
        .where(StoryItem.story_id == story_id)
    )
    return set(rows.scalars())


async def same_source_blocked(
    session: AsyncSession, sim: float, cfg: ClusterCfg, story_id: uuid.UUID, other: set[uuid.UUID]
) -> bool:
    """One feed rarely reports one event twice, but its series look alike (releases, changelogs, papers): a
    single-source story only takes more of that feed above cfg.same_source_join_threshold (ADR-026)."""
    t = cfg.same_source_join_threshold
    if t is None or sim >= t or len(other) != 1:
        return False
    return await story_sources(session, story_id) == other


async def recompute(session: AsyncSession, story: Story) -> None:
    rows = (
        await session.execute(
            select(
                Item.embedding,
                Item.published_at,
                ItemEnrichment.topics,
                ItemEnrichment.entities,
                ItemEnrichment.ring,
            )
            .join(StoryItem, StoryItem.item_id == Item.id)
            .outerjoin(ItemEnrichment, ItemEnrichment.item_id == Item.id)
            .where(StoryItem.story_id == story.id)
        )
    ).all()
    vecs = [list(r.embedding) for r in rows if r.embedding is not None]
    if vecs:
        story.centroid = mean_vec(vecs)
    pubs = [r.published_at for r in rows if r.published_at]
    if pubs:
        story.first_seen, story.last_updated = min(pubs), max(pubs)
    story.topics = sorted({t for r in rows for t in (r.topics or [])})[:10]
    story.entity_names = sorted({t for r in rows for t in entity_tags(r.entities or {})})[:40]
    rings = {r.ring for r in rows if r.ring}
    story.ring = "core" if "core" in rings else ("adjacent" if "adjacent" in rings else story.ring or "core")


@dataclass
class ClusterStats:
    joined: int = 0
    created: int = 0
    traced_primary: int = 0


async def assign_item(
    session: AsyncSession,
    item: Item,
    enr: ItemEnrichment | None,
    now: datetime,
    cfg: ClusterCfg | None = None,
) -> tuple[Story, bool]:
    cfg = cfg or cfg_now()
    tags = entity_tags(enr.entities if enr else {})
    src = await session.get(Source, item.source_id)
    best: tuple[float, Story] | None = None
    if item.embedding is not None:
        rows = (
            await session.execute(
                text(
                    "select id, 1 - (centroid <=> cast(:v as vector)) as sim from stories "
                    "where status = 'active' and centroid is not null and last_updated >= :since "
                    "order by centroid <=> cast(:v as vector) limit 8"
                ),
                {"v": str(list(item.embedding)), "since": now - timedelta(days=cfg.window_days)},
            )
        ).all()
        for r in rows:
            sim = float(r.sim)
            if sim < cfg.join_threshold:
                break
            if await same_source_blocked(session, sim, cfg, r.id, {item.source_id}):
                continue
            st = await session.get(Story, r.id)
            if st is not None and compatible(tags, list(st.entity_names or []), cfg.min_entity_overlap):
                best = (sim, st)
                break
    if best is not None:
        story = best[1]
        if story.last_shown_at and item.published_at and item.published_at > story.last_shown_at:
            # Developing story: a material update re-enters the brief with an UPDATE badge (§6.6).
            story.material_update_at = now
            story.what_changed = (enr.summary_1line if enr else item.title)[:500]
        session.add(StoryItem(story_id=story.id, item_id=item.id, role=role_for(item, src, story, enr)))
        await session.flush()
        await recompute(session, story)
        return story, False
    pub = item.published_at or now
    story = Story(
        title=item.title[:500],
        centroid=list(item.embedding) if item.embedding is not None else None,
        first_seen=pub,
        last_updated=pub,
        ring=(enr.ring if enr else "core"),
        topics=(enr.topics if enr else [])[:10],
        entity_names=tags,
    )
    session.add(story)
    await session.flush()
    session.add(StoryItem(story_id=story.id, item_id=item.id, role=role_for(item, src, None, enr)))
    await session.flush()
    return story, True


async def unclustered(session: AsyncSession) -> list[tuple[Item, ItemEnrichment]]:
    q = (
        select(Item, ItemEnrichment)
        .join(ItemEnrichment, ItemEnrichment.item_id == Item.id)
        .outerjoin(StoryItem, StoryItem.item_id == Item.id)
        .where(Item.status == "enriched", StoryItem.id.is_(None))
        .order_by(Item.published_at.asc().nulls_last(), Item.id)
    )
    return [(i, e) for i, e in (await session.execute(q)).all()]


async def cluster_pending(session: AsyncSession, now: datetime) -> ClusterStats:
    st = ClusterStats()
    cfg = cfg_now()
    for item, enr in await unclustered(session):
        _, created = await assign_item(session, item, enr, now, cfg)
        if created:
            st.created += 1
        else:
            st.joined += 1
    st.traced_primary = await trace_primary_sources(session)
    return st


async def trace_primary_sources(session: AsyncSession) -> int:
    """Attach the primary item (paper, repo, official post) a re-write links to, and mark it primary (§6.3 step 8)."""
    from signal_core.radar.normalise import canonical_url

    n = 0
    rows = (
        await session.execute(
            select(StoryItem, Item)
            .join(Item, Item.id == StoryItem.item_id)
            .where(StoryItem.role != "primary")
        )
    ).all()
    for si, it in rows:
        blob = f"{it.text or ''} {(it.signal_meta or {}).get('arxiv_url', '')}"
        targets: list[Item] = []
        for u in URL_RX.findall(blob):
            u = u.rstrip(".,;:!?)]'\"")  # trailing sentence punctuation is not part of the link
            hit = (
                (await session.execute(select(Item).where(Item.canonical_url == canonical_url(u))))
                .scalars()
                .first()
            )
            if hit is not None and hit.id != it.id:
                targets.append(hit)
        for aid in ARXIV_RX.findall(blob):
            hit = (
                (await session.execute(select(Item).where(Item.external_id == f"arxiv:{aid}")))
                .scalars()
                .first()
            )
            if hit is not None and hit.id != it.id:
                targets.append(hit)
        for t in targets:
            existing = (
                (await session.execute(select(StoryItem).where(StoryItem.item_id == t.id))).scalars().first()
            )
            if existing is None:
                session.add(StoryItem(story_id=si.story_id, item_id=t.id, role="primary"))
            elif existing.story_id == si.story_id:
                existing.role = "primary"
            else:
                continue  # already anchors another story; the nightly merge pass will reconcile
            t.primary_source = True
            n += 1
    await session.flush()
    return n


async def _summaries(session: AsyncSession, story: Story, n: int = 4) -> list[str]:
    rows = (
        (
            await session.execute(
                select(ItemEnrichment.summary_1line)
                .join(StoryItem, StoryItem.item_id == ItemEnrichment.item_id)
                .where(StoryItem.story_id == story.id)
                .limit(n)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def merge_pass(session: AsyncSession, now: datetime, run_id: uuid.UUID | None = None) -> int:
    cfg = cfg_now()
    stories = list(
        (
            await session.execute(
                select(Story).where(
                    Story.status == "active",
                    Story.centroid.is_not(None),
                    Story.last_updated >= now - timedelta(days=cfg.window_days),
                )
            )
        ).scalars()
    )
    merged = 0
    gone: set[uuid.UUID] = set()
    for a_idx, a in enumerate(stories):
        if a.id in gone:
            continue
        for b in stories[a_idx + 1 :]:
            if b.id in gone or a.id in gone:
                continue
            sim = cosine(list(a.centroid), list(b.centroid))
            if sim < cfg.merge_threshold - 0.05 or not compatible(
                list(a.entity_names), list(b.entity_names), cfg.min_entity_overlap
            ):
                continue
            if await same_source_blocked(session, sim, cfg, a.id, await story_sources(session, b.id)):
                continue
            same = sim >= cfg.merge_threshold
            if not same:
                shared_specific = {
                    t for t in set(a.entity_names) & set(b.entity_names) if t.split(":", 1)[0] in SPECIFIC
                }
                if not shared_specific:
                    continue
                try:
                    r = await llm.call(
                        "cluster_tiebreak",
                        {
                            "a": {"title": a.title, "summaries": await _summaries(session, a)},
                            "b": {"title": b.title, "summaries": await _summaries(session, b)},
                        },
                        session=session,
                        run_id=run_id,
                    )
                    same = bool(r.output.same_event)
                except (LLMError, BudgetExceeded):
                    continue
            if same:
                keep, drop = (a, b) if a.first_seen <= b.first_seen else (b, a)
                await merge_into(session, keep, drop)
                gone.add(drop.id)
                merged += 1
    return merged


async def merge_into(session: AsyncSession, keep: Story, drop: Story) -> None:
    for si in (await session.execute(select(StoryItem).where(StoryItem.story_id == drop.id))).scalars():
        si.story_id = keep.id
    drop.status, drop.merged_into = "merged", keep.id
    keep.followed = keep.followed or drop.followed
    await session.flush()
    await recompute(session, keep)
