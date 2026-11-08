"""Ingestion pipeline (§6.3 steps 1–4): fetch → normalise → dedupe → embed → prefilter.

Idempotent: (source_id, external_id) and (user_id, url_hash) are unique; inserts use ON CONFLICT DO NOTHING.
When the same URL arrives from another source (e.g. HN linking an official post) the new source's signal
metadata (points, stars …) is merged into the existing item instead of creating a second item.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.base import OWNER_ID, uuid7
from signal_core.db.models import FetchLog, Item, Profile, ProfileVector, Source
from signal_core.embeddings import get_embedder
from signal_core.logging import get_logger
from signal_core.radar.dedupe import CONTAINMENT_MIN, MASK64, containment, dedupe_text, shingles, simhash
from signal_core.radar.normalise import normalise
from signal_core.radar.prefilter import ProfileVec, prefilter
from signal_core.sources.base import AdapterNotConfigured, FetchResult, RawEntry, SourceSpec, get_adapter
from signal_core.sources.http import PoliteClient

log = get_logger("ingest")
FAILS_TO_FLAG = 3
ZERO_ITEM_DAYS_TO_FLAG = 7


@dataclass
class IngestStats:
    source: str
    status: str = "ok"
    found: int = 0
    new: int = 0
    merged: int = 0
    duplicates: int = 0
    prefiltered_out: int = 0
    passed: int = 0
    error: str | None = None
    new_item_ids: list[uuid.UUID] = field(default_factory=list)


def spec_of(s: Source) -> SourceSpec:
    return SourceSpec(
        id=str(s.id),
        type=s.type,
        name=s.name,
        url=s.url,
        params=dict(s.params or {}),
        etag=s.etag,
        last_modified=s.last_modified,
    )


async def load_profile(session: AsyncSession) -> tuple[list[ProfileVec], list[str], list[str]]:
    p = (await session.execute(select(Profile).where(Profile.user_id == OWNER_ID))).scalar_one_or_none()
    if p is None:
        return [], [], []
    kw: dict[str, list[str]] = {}
    for ring in ("core", "adjacent", "wide"):
        for t in (p.topics or {}).get(ring, []):
            kw[t["name"]] = list(t.get("keywords") or [])
    rows = (await session.execute(select(ProfileVector).where(ProfileVector.profile_id == p.id))).scalars()
    vecs = [ProfileVec(r.label, r.ring, r.weight, list(r.embedding), kw.get(r.label, [])) for r in rows]
    return vecs, list(p.blocked_keywords or []), list(p.blocked_entities or [])


def update_health(src: Source, ok: bool, found: int, now: datetime, error: str | None = None) -> None:
    h = dict(src.health or {})
    if ok:
        h["consecutive_failures"] = 0
        h["last_ok_at"] = now.isoformat()
        if found > 0:
            h["last_nonzero_at"] = now.isoformat()
        h.setdefault("last_nonzero_at", h.get("first_seen_at") or now.isoformat())
    else:
        h["consecutive_failures"] = int(h.get("consecutive_failures", 0)) + 1
        h["last_error"] = (error or "")[:500]
        h["last_error_at"] = now.isoformat()
    h.setdefault("first_seen_at", now.isoformat())
    flag = None
    if h.get("consecutive_failures", 0) >= FAILS_TO_FLAG:
        flag = f"failed {h['consecutive_failures']} times in a row — fix or disable"
    elif h.get("last_nonzero_at"):
        zero_since = datetime.fromisoformat(h["last_nonzero_at"])
        if now - zero_since >= timedelta(days=ZERO_ITEM_DAYS_TO_FLAG):
            flag = f"no new items for {(now - zero_since).days} days — fix or disable"
    h["flagged"] = flag
    src.health = h


class SimhashIndex:
    """In-memory SimHash index for one screening pass: vectorised XOR + popcount instead of a per-item SQL scan
    (the per-item scan was O(n²) and stalled the first live run at ~7k items)."""

    def __init__(self) -> None:
        self.ids: list[uuid.UUID] = []
        self._hashes: list[int] = []
        self._arr: np.ndarray | None = None

    @classmethod
    async def load(cls, session: AsyncSession, since: datetime) -> SimhashIndex:
        idx = cls()
        rows = (
            await session.execute(
                select(Item.id, Item.simhash).where(
                    Item.simhash.is_not(None),
                    Item.simhash != 0,
                    Item.duplicate_of.is_(None),
                    Item.fetched_at >= since,
                    Item.prefilter_score.is_not(None),
                )
            )
        ).all()
        for rid, sh in rows:
            idx.add(rid, sh)
        return idx

    def add(self, rid: uuid.UUID, sh: int | None) -> None:
        if not sh:
            return
        self.ids.append(rid)
        self._hashes.append(sh & MASK64)
        self._arr = None

    def nearest(self, sh: int, max_dist: int) -> uuid.UUID | None:
        if not self._hashes or not sh:
            return None
        if self._arr is None:
            self._arr = np.array(self._hashes, dtype=np.uint64)
        d = np.bitwise_count(np.bitwise_xor(self._arr, np.uint64(sh & MASK64)))
        i = int(np.argmin(d))
        return self.ids[i] if int(d[i]) <= max_dist else None


async def _near_duplicate(
    session: AsyncSession,
    item: Item,
    sh: int,
    now: datetime,
    max_dist: int,
    cos_min: float,
    window_h: int,
    index: SimhashIndex | None = None,
) -> uuid.UUID | None:
    since = now - timedelta(hours=window_h)
    if index is None:
        index = await SimhashIndex.load(session, since)
    hit = index.nearest(sh, max_dist)
    if hit is not None and hit != item.id:
        return hit
    if item.embedding is not None:
        # Nearest neighbours that were screened before this item (never a later item → stable "original").
        neighbours = (
            await session.execute(
                text(
                    "select id, text, 1 - (embedding <=> cast(:v as vector)) as sim from items "
                    "where id != :id and embedding is not null and duplicate_of is null and fetched_at >= :since "
                    "and prefilter_score is not null "
                    "order by embedding <=> cast(:v as vector) limit 5"
                ),
                {"v": str(list(item.embedding)), "id": item.id, "since": since},
            )
        ).all()
        mine = shingles(item.text)
        for r in neighbours:
            sim = float(r.sim)
            if sim >= cos_min:
                return uuid.UUID(str(r.id))
            if sim >= 0.6 and containment(mine, shingles(r.text or "")) >= CONTAINMENT_MIN:
                return uuid.UUID(str(r.id))
    return None


async def store_entries(
    session: AsyncSession,
    src: Source,
    entries: list[RawEntry],
    now: datetime,
    *,
    is_capture: bool = False,
    capture_intent: str | None = None,
) -> IngestStats:
    stats = IngestStats(source=src.name, found=len(entries))
    new_items: list[Item] = []
    for e in entries:
        if not e.url.lower().startswith(("http://", "https://", "mid:")):
            continue  # only http(s) links (and email message ids) are ever stored or rendered as hrefs
        n = normalise(e.url, e.title, e.summary, e.content_html, e.content_type_hint)
        if not n.title:
            continue
        existing = (
            (
                await session.execute(
                    select(Item).where(
                        (Item.url_hash == n.url_hash)
                        | ((Item.source_id == src.id) & (Item.external_id == e.external_id))
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            if e.signal_meta and existing.source_id != src.id:
                existing.signal_meta = {
                    **(existing.signal_meta or {}),
                    **e.signal_meta,
                    "also_from": sorted({*existing.signal_meta.get("also_from", []), src.name}),
                }
                stats.merged += 1
            continue
        values: dict[str, Any] = dict(
            user_id=OWNER_ID,
            source_id=src.id,
            external_id=e.external_id[:500],
            canonical_url=n.canonical_url,
            url_hash=n.url_hash,
            title=n.title,
            author=(e.author or None),
            published_at=e.published_at or now,
            fetched_at=now,
            content_type=n.content_type,
            language=n.language,
            text=n.text,
            text_hash=n.text_hash,
            word_count=n.word_count,
            raw={**e.raw, "source_url": e.url},
            signal_meta=e.signal_meta,
            status="new",
            is_capture=is_capture,
            capture_intent=capture_intent,
            primary_source=src.tier == 1,
            simhash=simhash(dedupe_text(n.title, n.text)),
        )
        values["id"] = uuid7()
        stmt = insert(Item).values(**values).on_conflict_do_nothing().returning(Item.id)
        new_id = (await session.execute(stmt)).scalar_one_or_none()
        if new_id is None:
            # Lost a race with a concurrent source inserting the same URL: merge our signal into the winner.
            winner = (
                (await session.execute(select(Item).where(Item.url_hash == n.url_hash))).scalars().first()
            )
            if winner is not None and e.signal_meta and winner.source_id != src.id:
                winner.signal_meta = {
                    **(winner.signal_meta or {}),
                    **e.signal_meta,
                    "also_from": sorted({*(winner.signal_meta or {}).get("also_from", []), src.name}),
                }
                stats.merged += 1
            continue
        item = await session.get(Item, new_id)
        assert item is not None
        new_items.append(item)
    stats.new = len(new_items)
    if new_items:
        from signal_core.ops.metrics import ITEMS_INGESTED

        ITEMS_INGESTED.labels(src.type).inc(len(new_items))
    if not new_items:
        return stats

    vecs = await get_embedder().embed([f"{i.title}\n{i.text[:2000]}" for i in new_items])
    for i, v in zip(new_items, vecs, strict=True):
        i.embedding = v
        if is_capture:
            i.capture_intent = capture_intent
    await session.flush()

    stats.new_item_ids = [i.id for i in new_items]
    return stats


@dataclass
class ScreenStats:
    screened: int = 0
    duplicates: int = 0
    prefiltered_out: int = 0
    passed: int = 0
    passed_ids: list[uuid.UUID] = field(default_factory=list)


async def screen_new_items(session: AsyncSession, now: datetime) -> ScreenStats:
    """Sequential dedupe + prefilter over unscreened items (prefilter_score IS NULL), oldest first.

    Runs after concurrent fetches have committed, so every item is compared with earlier items from all
    sources. Manual captures skip the prefilter (§11.2) but are still deduplicated.
    """
    cfg = get_config().scoring
    st = ScreenStats()
    pending = (
        (
            await session.execute(
                select(Item)
                .where(Item.prefilter_score.is_(None), Item.status == "new")
                .order_by(Item.published_at.asc().nulls_last(), Item.fetched_at.asc(), Item.id.asc())
            )
        )
        .scalars()
        .all()
    )
    if not pending:
        return st
    profile, blocked_kw, blocked_ent = await load_profile(session)
    index = await SimhashIndex.load(session, now - timedelta(hours=cfg.dedupe.window_hours))
    for i in pending:
        st.screened += 1
        dup = await _near_duplicate(
            session,
            i,
            i.simhash or 0,
            now,
            cfg.dedupe.simhash_max_distance,
            cfg.dedupe.embedding_cosine,
            cfg.dedupe.window_hours,
            index,
        )
        if dup is None:
            index.add(i.id, i.simhash)
        if dup is not None:
            i.duplicate_of, i.status, i.prefilter_score = dup, "duplicate", 0.0
            st.duplicates += 1
        elif i.is_capture:
            i.prefilter_score = 1.0
            st.passed += 1
            st.passed_ids.append(i.id)
        else:
            pf = prefilter(
                list(i.embedding) if i.embedding is not None else [],
                i.title,
                i.text,
                profile,
                blocked_kw,
                blocked_ent,
            )
            i.prefilter_score = pf.score
            i.signal_meta = {
                **(i.signal_meta or {}),
                "prefilter": {"best": pf.best_label, "ring": pf.ring, "keywords": pf.keyword_hits[:8]},
            }
            if pf.blocked or pf.score < cfg.prefilter_min:
                i.status = "prefiltered_out"
                st.prefiltered_out += 1
            else:
                st.passed += 1
                st.passed_ids.append(i.id)
        await session.flush()  # later items must see this decision
    return st


@dataclass
class FetchOutcome:
    """Result of the network phase. Holds no DB resources, so many fetches can run concurrently."""

    source_id: uuid.UUID
    result: FetchResult | None
    status: str  # ok | not_modified | skipped | error
    error: str | None
    latency_ms: int


async def fetch_phase(spec: SourceSpec, client: PoliteClient) -> FetchOutcome:
    sid = uuid.UUID(spec.id)
    t0 = time.monotonic()
    try:
        result = await get_adapter(spec.type)(spec, client)
        status = "not_modified" if result.not_modified else "ok"
        return FetchOutcome(sid, result, status, None, int((time.monotonic() - t0) * 1000))
    except AdapterNotConfigured as e:
        return FetchOutcome(sid, None, "skipped", str(e), int((time.monotonic() - t0) * 1000))
    except Exception as e:
        err = f"{e.__class__.__name__}: {e}"[:1000]
        log.warning("source_failed", source=spec.name, error=err)
        from signal_core.ops.metrics import SOURCE_ERRORS

        SOURCE_ERRORS.labels(spec.name).inc()
        return FetchOutcome(sid, None, "error", err, int((time.monotonic() - t0) * 1000))


async def apply_phase(
    session: AsyncSession, outcome: FetchOutcome, now: datetime, screen: bool = True
) -> IngestStats:
    src = await session.get(Source, outcome.source_id)
    if src is None:
        raise LookupError(f"source {outcome.source_id} not found")
    stats = IngestStats(source=src.name, status=outcome.status, error=outcome.error)
    if outcome.status == "ok" and outcome.result is not None:
        stats = await store_entries(session, src, outcome.result.entries, now)
        src.etag, src.last_modified = outcome.result.etag, outcome.result.last_modified
        if screen:
            sc = await screen_new_items(session, now)
            stats.duplicates, stats.prefiltered_out, stats.passed = (
                sc.duplicates,
                sc.prefiltered_out,
                sc.passed,
            )
    if outcome.status in ("ok", "not_modified"):
        update_health(src, True, stats.new, now)
    elif outcome.status == "error":
        update_health(src, False, 0, now, outcome.error)
    src.last_fetched_at = now
    session.add(
        FetchLog(
            source_id=src.id,
            started_at=now,
            status=stats.status,
            items_found=stats.found,
            items_new=stats.new,
            latency_ms=outcome.latency_ms,
            error=stats.error,
        )
    )
    await session.flush()
    return stats


async def ingest_source(
    session: AsyncSession,
    source_id: uuid.UUID,
    http: PoliteClient | None = None,
    now: datetime | None = None,
    screen: bool = True,
) -> IngestStats:
    now = now or datetime.now(UTC)
    src = await session.get(Source, source_id)
    if src is None:
        raise LookupError(f"source {source_id} not found")
    own_http = http is None
    client = http or PoliteClient()
    try:
        outcome = await fetch_phase(spec_of(src), client)
    finally:
        if own_http:
            await client.aclose()
    return await apply_phase(session, outcome, now, screen)


async def due_sources(session: AsyncSession, now: datetime) -> list[Source]:
    """Enabled, non-capture sources whose fetch interval elapsed. In mock mode only fixture sources run, so
    mock mode never touches the network (ADR-013)."""
    from signal_core.settings import get_settings

    mock = get_settings().is_mock
    rows = (
        await session.execute(select(Source).where(Source.enabled.is_(True), Source.type != "capture"))
    ).scalars()
    return [
        s
        for s in rows
        if (not mock or (s.params or {}).get("fixture"))
        and (s.last_fetched_at is None or s.last_fetched_at + timedelta(minutes=s.fetch_every) <= now)
    ]
