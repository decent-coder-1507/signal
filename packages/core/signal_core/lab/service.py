"""LAB (§8): spark detection, pain signals, prior art, idea cards & scoring, capacity guard, build briefs, build logs.

Evidence rules: ids must exist in the provided lists (unknown refs dropped). Product ideas need ≥ 2 independent
signals (distinct stories with different sources) or are downgraded to an experiment.
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.base import OWNER_ID
from signal_core.db.models import (
    BuildBrief,
    BuildLog,
    Idea,
    IdeaEvidence,
    Item,
    ItemEnrichment,
    Profile,
    Skill,
    Source,
    Story,
    StoryItem,
)
from signal_core.embeddings import cosine, get_embedder
from signal_core.llm import router as llm

LAB_WEIGHTS = {
    "impact": 0.2,
    "confidence": 0.15,
    "ease": 0.15,
    "personal_fit": 0.2,
    "learning_value": 0.1,
    "content_value": 0.1,
    "novelty": 0.1,
}
STATUSES = ["spark", "shortlisted", "validating", "building", "shipped", "shared", "archived", "killed"]
PAIN = re.compile(
    r"\b(frustrat\w*|annoy\w*|hate|broken|struggl\w*|pain(ful)?|why (does|is|can't)|can't|doesn't work|"
    r"no good way|wish there (was|were)|tricked|hijack\w*|vulnerab\w*)\b",
    re.I,
)


def lab_score(scores: dict[str, float]) -> float:
    return round(sum(LAB_WEIGHTS[k] * float(scores.get(k, 0)) for k in LAB_WEIGHTS), 2)


async def building_count(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(select(func.count()).select_from(Idea).where(Idea.status == "building"))
        ).scalar_one()
    )


async def pain_signals(session: AsyncSession, since: datetime, limit: int = 20) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Item, Source, ItemEnrichment)
            .join(Source, Source.id == Item.source_id)
            .outerjoin(ItemEnrichment, ItemEnrichment.item_id == Item.id)
            .where(Item.fetched_at >= since, Item.status.in_(["enriched", "new"]))
        )
    ).all()
    out = []
    for it, src, enr in rows:
        text = f"{it.title}. {it.text[:600]}"
        if PAIN.search(text):
            out.append(
                {"id": str(it.id), "source": src.name, "text": (enr.summary_1line if enr else it.title)[:240]}
            )
    return out[:limit]


async def prior_art(session: AsyncSession, query_texts: list[str], k: int = 8) -> list[dict[str, Any]]:
    """Existing tools/repos/launches already in the DB that are close to the candidate topics (§8.3 novelty check)."""
    rows = list(
        (
            await session.execute(
                select(Item).where(
                    Item.content_type.in_(["repo", "launch", "release"]), Item.embedding.is_not(None)
                )
            )
        ).scalars()
    )
    if not rows or not query_texts:
        return []
    qv = await get_embedder().embed(query_texts)
    scored = sorted(((max(cosine(list(i.embedding), q) for q in qv), i) for i in rows), key=lambda x: -x[0])
    return [{"id": str(i.id), "title": i.title, "url": i.canonical_url} for _s, i in scored[:k]]


async def detect_sparks(
    session: AsyncSession,
    now: datetime,
    run_id: uuid.UUID | None = None,
    top_n: int = 8,
    story_ids: list[uuid.UUID] | None = None,
) -> list[Idea]:
    """Spark detection over today's top stories, or over specific stories ("Build" on a story)."""
    cfg = get_config()
    q = select(Story)
    if story_ids:
        q = q.where(Story.id.in_(story_ids))
    else:
        q = (
            q.where(
                Story.status == "active",
                Story.final_score > 0,
                Story.last_updated >= now - timedelta(days=3),
            )
            .order_by(desc(Story.final_score))
            .limit(top_n)
        )
    stories = list((await session.execute(q)).scalars())
    if not stories:
        return []
    summaries = {}
    for s in stories:
        summaries[str(s.id)] = (
            await session.execute(
                select(ItemEnrichment.summary_1line)
                .join(StoryItem, StoryItem.item_id == ItemEnrichment.item_id)
                .where(StoryItem.story_id == s.id)
                .limit(1)
            )
        ).scalar() or ""
    pains = await pain_signals(session, now - timedelta(days=7))
    pa = await prior_art(session, [s.title for s in stories])
    prof = (await session.execute(select(Profile).where(Profile.user_id == OWNER_ID))).scalar_one_or_none()
    existing = [
        i.title
        for i in (
            await session.execute(select(Idea).where(Idea.status.notin_(["archived", "killed"])))
        ).scalars()
    ]
    guard = await building_count(session) >= 2
    learn = [
        s.name
        for s in (await session.execute(select(Skill).order_by(desc(Skill.market_signal)).limit(5))).scalars()
    ]
    r = await llm.call(
        "spark_detect",
        {
            "owner": cfg.profile.owner.name,
            "role": prof.role if prof else cfg.profile.owner.role,
            "stack": prof.stack if prof else [],
            "goals": prof.goals if prof else [],
            "stories": [
                {"id": str(s.id), "title": s.title, "summary": summaries[str(s.id)]} for s in stories
            ],
            "pains": pains,
            "prior_art": pa,
            "learn_next": learn,
            "existing": existing,
            "capacity_guard": guard,
        },
        session=session,
        run_id=run_id,
    )
    valid_story = {str(s.id): s for s in stories}
    valid_item = {p["id"] for p in pains}
    pa_by_id = {a["id"]: a for a in pa}
    out = []
    for card in r.output.ideas:
        evidence = [
            e for e in card.evidence if e.ref in valid_story or e.ref in valid_item
        ]  # drop unknown refs
        if not evidence:
            continue
        kind = card.type
        if guard and kind != "practical":
            continue  # capacity guard (§8.6)
        if kind == "product" and await independent_signals(session, evidence, valid_story) < 2:
            kind = "experiment"  # not enough independent evidence for a product idea
        scores = card.scores.model_dump()
        idea = Idea(
            type=kind,
            title=card.title[:300],
            one_liner=card.one_liner,
            evidence=[e.model_dump() for e in evidence],
            problem=card.problem,
            persona=card.persona,
            why_now=card.why_now,
            solution=card.solution,
            mvp_scope=card.mvp_scope,
            not_in_mvp=card.not_in_mvp,
            stack=card.stack,
            effort=card.effort,
            risks=card.risks,
            moat=card.moat,
            validation_plan=card.validation_plan,
            learning_skills=card.learning_skills,
            content_plan=card.content_plan,
            scores=scores,
            lab_score=lab_score(scores),
            prior_art=[pa_by_id[x] for x in card.prior_art_refs if x in pa_by_id],
            status="spark",
            origin="spark",
            prompt_version=r.prompt_version,
            model=r.model,
        )
        session.add(idea)
        await session.flush()
        for e in evidence:
            if e.ref in valid_story:
                session.add(IdeaEvidence(idea_id=idea.id, story_id=uuid.UUID(e.ref), note=e.why))
            else:
                session.add(IdeaEvidence(idea_id=idea.id, item_id=uuid.UUID(e.ref), note=e.why))
        out.append(idea)
    await session.flush()
    return out


async def build_from_story(session: AsyncSession, story: Story, now: datetime) -> list[Idea]:
    """Story "Build" action: spark detection scoped to this story. When nothing passes the evidence rules, a plain
    experiment idea is created with the story as its only evidence (title from the story, nothing invented)."""
    ideas = await detect_sparks(session, now, story_ids=[story.id])
    if ideas:
        for i in ideas:
            i.origin = "story"
            i.status = "shortlisted"
        return ideas
    idea = Idea(
        type="experiment",
        title=story.title[:300],
        evidence=[{"ref": str(story.id), "why": "Saved from the brief with Build"}],
        scores={},
        lab_score=0.0,
        status="shortlisted",
        origin="story",
    )
    session.add(idea)
    await session.flush()
    session.add(IdeaEvidence(idea_id=idea.id, story_id=story.id, note="Saved from the brief with Build"))
    await session.flush()
    return [idea]


async def independent_signals(session: AsyncSession, evidence: list[Any], stories: dict[str, Story]) -> int:
    sources: set[str] = set()
    for e in evidence:
        ref = e.ref if hasattr(e, "ref") else e["ref"]
        if ref in stories:
            names = (stories[ref].scores or {}).get("sources", [])
            sources |= {f"{ref}:{n}" for n in names[:1]} if names else {ref}
        else:
            sources.add(ref)
    return len({s.split(":", 1)[0] for s in sources})


async def evidence_links(session: AsyncSession, idea: Idea) -> list[dict[str, str]]:
    out = []
    for ev in (await session.execute(select(IdeaEvidence).where(IdeaEvidence.idea_id == idea.id))).scalars():
        if ev.story_id:
            s = await session.get(Story, ev.story_id)
            first = (
                await session.execute(
                    select(Item.canonical_url)
                    .join(StoryItem, StoryItem.item_id == Item.id)
                    .where(StoryItem.story_id == ev.story_id)
                    .limit(1)
                )
            ).scalar()
            out.append({"title": s.title if s else "story", "url": first or "", "note": ev.note})
        elif ev.item_id:
            i = await session.get(Item, ev.item_id)
            if i:
                out.append({"title": i.title, "url": i.canonical_url, "note": ev.note})
    return out


async def generate_brief(session: AsyncSession, idea: Idea) -> BuildBrief:
    cfg = get_config()
    ev = await evidence_links(session, idea)
    prof = (await session.execute(select(Profile).where(Profile.user_id == OWNER_ID))).scalar_one_or_none()
    card = {
        k: getattr(idea, k)
        for k in (
            "type",
            "title",
            "one_liner",
            "problem",
            "persona",
            "why_now",
            "solution",
            "mvp_scope",
            "not_in_mvp",
            "stack",
            "effort",
            "risks",
            "moat",
            "validation_plan",
            "learning_skills",
            "content_plan",
        )
    }
    r = await llm.call(
        "build_brief",
        {"owner": cfg.profile.owner.name, "stack": prof.stack if prof else [], "idea": card, "evidence": ev},
        session=session,
        user_initiated=True,
    )
    files = {"BRIEF.md": r.output.brief_md, "CLAUDE.md": r.output.claude_md}
    if r.output.experiment_md.strip():
        files["EXPERIMENT.md"] = r.output.experiment_md
    ver = (
        (
            await session.execute(select(func.max(BuildBrief.version)).where(BuildBrief.idea_id == idea.id))
        ).scalar()
        or 0
    ) + 1
    bb = BuildBrief(idea_id=idea.id, files=files, version=ver, prompt_version=r.prompt_version, model=r.model)
    session.add(bb)
    await session.flush()
    return bb


def brief_zip(bb: BuildBrief, slug: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in bb.files.items():
            z.writestr(f"{slug}/{name}", content)
    return buf.getvalue()


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "idea"


async def set_status(session: AsyncSession, idea: Idea, status: str, kill_reason: str | None = None) -> Idea:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if status == "killed" and not (kill_reason and kill_reason.strip()):
        raise ValueError("killing an idea needs a reason (killing is healthy, but say why)")
    if status == "building" and idea.type != "practical" and await building_count(session) >= 2:
        raise ValueError("capacity guard: 2 ideas are already building — finish or kill one first")
    idea.status = status
    idea.kill_reason = kill_reason if status == "killed" else idea.kill_reason
    await session.flush()
    return idea


async def add_log(
    session: AsyncSession,
    idea: Idea,
    text: str,
    attachments: list[dict[str, Any]] | None = None,
    at: datetime | None = None,
) -> BuildLog:
    lg = BuildLog(
        idea_id=idea.id, text=text.strip(), attachments=attachments or [], logged_at=at or datetime.now(UTC)
    )
    session.add(lg)
    await session.flush()
    return lg
