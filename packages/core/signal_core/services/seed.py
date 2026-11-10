"""Idempotent seeding from config/*.yaml (`scripts/dev.py seed`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.auth import hash_password
from signal_core.config.schemas import AppConfig, SkillNode
from signal_core.db.base import OWNER_ID
from signal_core.db.models import Item, Profile, ProfileVector, Routine, Skill, Source, User, VoiceProfile
from signal_core.embeddings import get_embedder
from signal_core.services.settings_store import get_setting, set_setting

PROFILE_EMBEDDER_KEY = "profile_vectors.embedder"


async def ensure_user(session: AsyncSession, email: str, password: str, tz: str) -> User:
    user = await session.get(User, OWNER_ID)
    if user is None:
        user = User(id=OWNER_ID, email=email.lower(), password_hash=hash_password(password), timezone=tz)
        session.add(user)
        await session.flush()
    return user


async def seed_profile(session: AsyncSession, cfg: AppConfig) -> Profile:
    p = (await session.execute(select(Profile).where(Profile.user_id == OWNER_ID))).scalar_one_or_none()
    o, t = cfg.profile.owner, cfg.profile.topics
    topics = {
        "core": [x.model_dump() for x in t.core],
        "adjacent": [x.model_dump() for x in t.adjacent],
        "wide": [x.model_dump() for x in t.wide],
    }
    if p is None:
        p = Profile(
            role=o.role,
            goals=o.goals,
            stack=o.stack,
            topics=topics,
            blocked_entities=t.blocked_entities,
            blocked_keywords=t.blocked_keywords,
            vanco_context=o.vanco_context,
        )
        session.add(p)
        await session.flush()
        await rebuild_profile_vectors(session, p)
    return p


def topic_text(topic: dict[str, Any]) -> str:
    return f"{topic['name'].replace('-', ' ')}: " + ", ".join(topic.get("keywords") or [])


def profile_vector_rows(
    topics: dict[str, Any], goals: list[str], stack: list[str]
) -> list[tuple[str, str, str, float, str]]:
    """(kind, label, ring, weight, text) for every interest-profile vector."""
    rows: list[tuple[str, str, str, float, str]] = []
    for ring in ("core", "adjacent", "wide"):
        for tp in (topics or {}).get(ring, []):
            rows.append(("topic", tp["name"], ring, float(tp.get("weight", 1.0)), topic_text(tp)))
    for g in goals:
        rows.append(("goal", g[:255], "core", 0.8, g))
    if stack:
        rows.append(("stack", "stack", "core", 0.6, "Tech stack: " + ", ".join(stack)))
    return rows


async def rebuild_profile_vectors(session: AsyncSession, p: Profile) -> None:
    await session.execute(delete(ProfileVector).where(ProfileVector.profile_id == p.id))
    rows = profile_vector_rows(p.topics, p.goals, p.stack)
    emb = get_embedder()
    vecs = await emb.embed([r[4] for r in rows]) if rows else []
    for (kind, label, ring, weight, _), v in zip(rows, vecs, strict=True):
        session.add(
            ProfileVector(profile_id=p.id, kind=kind, label=label, ring=ring, weight=weight, embedding=v)
        )
    await set_setting(session, PROFILE_EMBEDDER_KEY, emb.name)
    await session.flush()
    await rebuild_topic_centroids(session, p)


async def rebuild_topic_centroids(session: AsyncSession, p: Profile, now: datetime | None = None) -> int:
    """Keyword-seeded topic centroids for the hybrid prefilter (ADR-026), from recently fetched items. Runs after a
    profile rebuild and nightly; topics with too few matching items keep only their text vector."""
    from signal_core.config import get_config
    from signal_core.radar.prefilter import CENTROID, keyword_centroids

    hy = get_config().scoring.prefilter_hybrid
    min_items, days = (hy.centroid_min_items, hy.centroid_days) if hy else (20, 180)
    await session.execute(
        delete(ProfileVector).where(ProfileVector.profile_id == p.id, ProfileVector.kind == CENTROID)
    )
    since = (now or datetime.now(UTC)) - timedelta(days=days)
    rows = (
        await session.execute(
            select(Item.title, func.left(Item.text, 4000), Item.embedding).where(
                Item.embedding.is_not(None), Item.duplicate_of.is_(None), Item.fetched_at >= since
            )
        )
    ).all()
    topics = [
        (t["name"], ring, float(t.get("weight", 1.0)), list(t.get("keywords") or []))
        for ring in ("core", "adjacent", "wide")
        for t in (p.topics or {}).get(ring, [])
    ]
    cents = keyword_centroids(((r[0], r[1] or "", list(r[2])) for r in rows), topics, min_items)
    for name, ring, weight, _kw in topics:
        if name in cents:
            session.add(
                ProfileVector(
                    profile_id=p.id,
                    kind=CENTROID,
                    label=name,
                    ring=ring,
                    weight=weight,
                    embedding=cents[name],
                )
            )
    await session.flush()
    return len(cents)


async def ensure_profile_vectors(session: AsyncSession, p: Profile) -> bool:
    """Rebuild the profile vectors when they were made by another embedder than the one that embeds items.

    Seeding in mock mode and then ingesting live left hashed bag-of-words profile vectors next to bge-small item
    vectors: every cosine was ~0, so the prefilter's embedding half and the relevance score silently did nothing
    (ADR-026). Returns True when it rebuilt."""
    if await get_setting(session, PROFILE_EMBEDDER_KEY, "") == get_embedder().name:
        return False
    await rebuild_profile_vectors(session, p)
    return True


async def seed_sources(session: AsyncSession, cfg: AppConfig) -> int:
    existing = {s.name: s for s in (await session.execute(select(Source))).scalars()}
    n = 0
    for sc in cfg.sources.sources:
        extra = {
            k: v
            for k, v in sc.model_dump().items()
            if k
            not in {"type", "name", "url", "tier", "ring", "topics", "fetch_every", "enabled", "terms_note"}
        }
        if sc.name in existing:
            s = existing[sc.name]
            s.type, s.url, s.tier, s.ring, s.topics = sc.type, sc.url, sc.tier, sc.ring, sc.topics
            s.fetch_every, s.params, s.terms_note = sc.fetch_every_minutes, extra, sc.terms_note
        else:
            session.add(
                Source(
                    type=sc.type,
                    name=sc.name,
                    url=sc.url,
                    tier=sc.tier,
                    ring=sc.ring,
                    topics=sc.topics,
                    fetch_every=sc.fetch_every_minutes,
                    enabled=sc.enabled,
                    params=extra,
                    terms_note=sc.terms_note,
                )
            )
            n += 1
    await session.flush()
    return n


async def seed_routines(session: AsyncSession, cfg: AppConfig, tz: str) -> None:
    existing = {r.name: r for r in (await session.execute(select(Routine))).scalars()}
    for rc in cfg.routines.routines:
        if rc.name in existing:
            r = existing[rc.name]
            if not (r.params or {}).get(
                "_user_edited"
            ):  # config updates flow in until the user edits it in the UI
                r.cron, r.steps, r.channels = rc.cron, rc.steps, list(rc.channels)
                r.params = {**rc.params}
            continue
        session.add(
            Routine(
                name=rc.name,
                cron=rc.cron,
                timezone=tz,
                steps=rc.steps,
                channels=list(rc.channels),
                params=rc.params,
                enabled=rc.enabled,
            )
        )
    await session.flush()


async def seed_skills(session: AsyncSession, cfg: AppConfig) -> None:
    existing = {s.name for s in (await session.execute(select(Skill))).scalars()}

    async def walk(node: SkillNode, parent_id: Any) -> None:
        if node.name in existing:
            sid = (await session.execute(select(Skill.id).where(Skill.name == node.name))).scalar_one()
        else:
            s = Skill(
                parent_id=parent_id,
                name=node.name,
                description=node.description,
                durability=node.durability,
                prereqs=node.prereqs,
                target_level=node.target_level,
                current_level=node.current_level,
                resources=node.resources,
            )
            session.add(s)
            await session.flush()
            sid = s.id
        for c in node.children:
            await walk(c, sid)

    for d in cfg.skills.domains:
        await walk(d, None)


async def seed_voice(session: AsyncSession, cfg: AppConfig) -> None:
    has = (await session.execute(select(VoiceProfile.id).limit(1))).first()
    if has:
        return
    v = cfg.voice
    session.add(
        VoiceProfile(
            version=1,
            active=True,
            note="seeded from config/voice.yaml",
            rules={
                "base": v.base,
                **v.rules,
                "hook_types": v.hook_types,
                "banned_patterns": v.banned_patterns,
                "banned_chars": v.banned_chars,
                "target_score": v.target_score,
                "max_revise_loops": v.max_revise_loops,
                "goals_per_week": v.goals_per_week,
            },
            banned_phrases=v.banned_phrases,
            emoji_set=list(v.rules.get("emoji", {}).get("set", [])),
            platform_overrides=v.platforms,
        )
    )
    await session.flush()


async def seed_all(
    session: AsyncSession, cfg: AppConfig, email: str, password: str, tz: str
) -> dict[str, Any]:
    await ensure_user(session, email, password, tz)
    await seed_profile(session, cfg)
    new_sources = await seed_sources(session, cfg)
    await seed_routines(session, cfg, tz)
    await seed_skills(session, cfg)
    await seed_voice(session, cfg)
    return {"new_sources": new_sources}
