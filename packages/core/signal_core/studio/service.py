"""STUDIO pipeline (§7.1): seed → angles → ask-me → drafts (writer) → grade → fact-check → AI-tell → revise
(≤ 2 loops) → human edit → Ready gate → approve/schedule → publish-assist → published.

Truth rules: facts only from cited sources (item ids) or the raw-material bank / ask-me answers ("r:<id>").
A draft cannot reach Ready while it has blocking AI-tell issues, unsupported/uncited factual claims or high safety
flags — unless the user records an explicit override with a reason (§M4 acceptance).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.models import (
    ContentIdea,
    Draft,
    DraftVersion,
    Item,
    Publication,
    RawMaterial,
    ReferencePost,
    Source,
    Story,
    StoryItem,
)
from signal_core.embeddings import cosine, get_embedder
from signal_core.llm import router as llm
from signal_core.radar.insight import latest_insight
from signal_core.studio.aitell import scan, scan_thread
from signal_core.studio.voice import active_voice
from signal_core.truth import norm

PLATFORM_LABEL = {"linkedin": "a LinkedIn post", "x": "a single X post", "x_thread": "an X thread"}
FORMAT_RULES = {
    "linkedin": (
        "Return 2 versions: A) story-led 80–200 words, one sentence per line with a blank line between lines; "
        "B) short question-led under 60 words for an image post. Links go in `first_comment`, not the body."
    ),
    "x": "Return 1–3 variants, each ≤ 280 characters. Plain text, at most one hashtag.",
    "x_thread": (
        "Return one version whose `thread` has 4–10 posts, each ≤ 280 characters and self-contained. Post 1 "
        "is a standalone hook. The final post has the call to action. A short code snippet or command is "
        "allowed."
    ),
}
RUBRIC = {
    "linkedin": [
        {"name": "Hook", "points": 2, "full": "line 1 alone would stop a scroll and sounds like him"},
        {"name": "Rhythm", "points": 2, "full": "short lines, white space, reads aloud naturally"},
        {"name": "Specificity", "points": 2, "full": "real names, numbers, places; nothing generic"},
        {"name": "Voice match", "points": 2, "full": "indistinguishable from reference posts; no AI tells"},
        {"name": "Ending", "points": 1, "full": "a real question or clear CTA"},
        {"name": "Restraint", "points": 1, "full": "right length, 1–3 emoji, 0–3 hashtags"},
    ],
    "x": [
        {"name": "Hook", "points": 3, "full": "first line earns the read"},
        {"name": "Density", "points": 3, "full": "one sharp idea, no filler"},
        {"name": "Voice match", "points": 2, "full": "sounds like him"},
        {"name": "Ending", "points": 2, "full": "invites replies"},
    ],
    "x_thread": [
        {"name": "Hook", "points": 3, "full": "post 1 stands alone"},
        {"name": "Thread flow", "points": 3, "full": "each post self-contained, logical order"},
        {"name": "Density", "points": 2, "full": "no filler posts"},
        {"name": "Ending", "points": 2, "full": "clear CTA/link"},
    ],
}
FACTUAL = re.compile(r"\d|\b[A-Z][a-z]+[A-Z0-9-]|\b[A-Z][a-z]+ (?:AI|Labs|Semi)\b")


class GateError(Exception):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass
class SeedContext:
    seed_type: str
    seed_id: uuid.UUID | None
    title: str
    text: str
    sources: list[dict[str, Any]]  # [{id, source, title, text}]


# ---------------- seeds & angles ----------------
async def seed_context(
    session: AsyncSession, seed_type: str, seed_id: uuid.UUID | None, seed_text: str = ""
) -> SeedContext:
    if seed_type == "story" and seed_id:
        story = await session.get(Story, seed_id)
        if story is None:
            raise LookupError("story not found")
        rows = (
            await session.execute(
                select(Item, Source)
                .join(StoryItem, StoryItem.item_id == Item.id)
                .join(Source, Source.id == Item.source_id)
                .where(StoryItem.story_id == story.id)
                .order_by(Source.tier)
            )
        ).all()
        ins = await latest_insight(session, story.id)
        text = ins.what_happened if ins else " ".join(i.title for i, _ in rows)
        return SeedContext(
            "story",
            story.id,
            story.title,
            text,
            [
                {
                    "id": str(i.id),
                    "source": s.name,
                    "title": i.title,
                    "text": " ".join((i.text or i.title).split()[:300]),
                }
                for i, s in rows[:5]
            ],
        )
    if seed_type == "item" and seed_id:
        i = await session.get(Item, seed_id)
        if i is None:
            raise LookupError("item not found")
        s = await session.get(Source, i.source_id)
        return SeedContext(
            "item",
            i.id,
            i.title,
            i.text[:1500],
            [
                {
                    "id": str(i.id),
                    "source": s.name if s else "",
                    "title": i.title,
                    "text": " ".join(i.text.split()[:300]),
                }
            ],
        )
    if seed_type == "build_log" and seed_id:
        from signal_core.db.models import BuildLog, Idea

        idea = await session.get(Idea, seed_id)
        if idea is None:
            raise LookupError("idea not found")
        logs = list(
            (
                await session.execute(
                    select(BuildLog).where(BuildLog.idea_id == idea.id).order_by(BuildLog.logged_at)
                )
            ).scalars()
        )
        return SeedContext("build_log", idea.id, idea.title, "\n".join(lg.text for lg in logs), [])
    return SeedContext(seed_type, seed_id, seed_text.split("\n", 1)[0][:120] or "Free text", seed_text, [])


async def raw_for(
    session: AsyncSession, text: str, k: int = 3, ids: list[uuid.UUID] | None = None
) -> list[RawMaterial]:
    q = select(RawMaterial).where(RawMaterial.confidentiality != "private")
    if ids is not None:
        q = q.where(RawMaterial.id.in_(ids)) if ids else q.where(RawMaterial.id.is_(None))
        return list((await session.execute(q)).scalars())
    rows = list((await session.execute(q)).scalars())
    if not rows or not text:
        return []
    [v] = await get_embedder().embed([text])
    scored = sorted(rows, key=lambda r: -cosine(v, list(r.embedding)) if r.embedding is not None else 0)
    return [r for r in scored[:k] if r.embedding is not None and cosine(v, list(r.embedding)) > 0.15]


async def recent_theses(session: AsyncSession, days: int = 60) -> list[ContentIdea]:
    since = datetime.now(UTC) - timedelta(days=days)
    return list(
        (
            await session.execute(
                select(ContentIdea).where(
                    ContentIdea.created_at >= since, ContentIdea.status.in_(["drafting", "used"])
                )
            )
        ).scalars()
    )


async def create_angles(
    session: AsyncSession, seed_type: str, seed_id: uuid.UUID | None = None, seed_text: str = ""
) -> list[ContentIdea]:
    ctx = await seed_context(session, seed_type, seed_id, seed_text)
    owner = get_config().profile.owner
    raw = await raw_for(session, ctx.title + " " + ctx.text)
    used = await recent_theses(session)
    r = await llm.call(
        "angles",
        {
            "owner": owner.name,
            "role": owner.role,
            "seed_type": ctx.seed_type,
            "seed_title": ctx.title,
            "seed_text": ctx.text[:3000],
            "raw": [{"id": str(x.id), "text": x.text} for x in raw],
            "recent": [u.thesis for u in used][:20],
        },
        session=session,
        user_initiated=True,
    )
    vecs = await get_embedder().embed([a.thesis for a in r.output.angles])
    out: list[ContentIdea] = []
    for a, v in zip(r.output.angles, vecs, strict=True):
        # Avoid angles he already used in the last 60 days on similar topics (§7.3).
        if any(u.embedding is not None and cosine(v, list(u.embedding)) > 0.92 for u in used):
            continue
        ci = ContentIdea(
            seed_type=ctx.seed_type,
            seed_id=ctx.seed_id,
            seed_text=seed_text[:4000],
            angle_type=a.angle_type,
            thesis=a.thesis,
            credibility=a.credibility,
            needs_input=[n.model_dump() for n in a.needs_input],
            platform_suggestions=list(a.platforms),
            risk=a.risk,
            status="idea",
            source_ids=[s["id"] for s in ctx.sources],
            embedding=v,
        )
        session.add(ci)
        out.append(ci)
    await session.flush()
    return out


# ---------------- drafts ----------------
async def start_drafts(
    session: AsyncSession, idea_id: uuid.UUID, platforms: list[str], skip_questions: bool = False
) -> list[Draft]:
    idea = await session.get(ContentIdea, idea_id)
    if idea is None:
        raise LookupError("content idea not found")
    idea.status = "drafting"
    drafts = []
    for p in platforms:
        from signal_core.studio.visual import FORMATS

        fmt = FORMATS.get(p) or ("thread" if p == "x_thread" else "post")
        d = Draft(
            content_idea_id=idea.id,
            platform=p,
            format=fmt,
            status="drafting",
            pending_questions=[] if skip_questions else list(idea.needs_input or []),
        )
        if idea.seed_type == "story":
            d.timeliness_deadline = datetime.now(UTC) + timedelta(hours=24)  # news-reactive (§7.9)
        session.add(d)
        drafts.append(d)
    await session.flush()
    for d in drafts:
        if not d.pending_questions:
            await produce(session, d)
    return drafts


async def answer_questions(
    session: AsyncSession,
    draft_id: uuid.UUID,
    answers: dict[str, str],
    save_to_bank: bool = True,
    can_name: bool = False,
) -> Draft:
    """Ask-me answers become raw-material entries (with his consent) — the only legitimate personal facts."""
    d = await session.get(Draft, draft_id)
    if d is None:
        raise LookupError("draft not found")
    raw_ids = list((d.ready_override or {}).get("_answer_raw_ids", []))
    texts = [a.strip() for a in answers.values() if a and a.strip()]
    if texts:
        vecs = await get_embedder().embed(texts)
        for t, v in zip(texts, vecs, strict=True):
            rm = RawMaterial(
                kind="story",
                text=t,
                can_name=can_name,
                confidentiality="public" if save_to_bank else "private",
                origin="ask_me",
                embedding=v,
            )
            session.add(rm)
            await session.flush()
            raw_ids.append(str(rm.id))
    d.pending_questions = []
    d.ready_override = {**(d.ready_override or {}), "_answer_raw_ids": raw_ids}
    await session.flush()
    await produce(session, d)
    return d


def _platform_spec(platform: str) -> dict[str, Any]:
    vp = get_config().voice.platforms
    return dict(vp.get("x" if platform == "x_thread" else platform, {}))


async def _references(session: AsyncSession, text: str, k: int = 3) -> list[str]:
    rows = list(
        (await session.execute(select(ReferencePost).where(ReferencePost.is_own.is_(True)))).scalars()
    )
    if not rows:
        return []
    [v] = await get_embedder().embed([text])
    rows.sort(key=lambda r: -cosine(v, list(r.embedding)) if r.embedding is not None else 0)
    return [r.text for r in rows[:k]]


async def _context(session: AsyncSession, d: Draft) -> tuple[ContentIdea, SeedContext, list[RawMaterial]]:
    idea = await session.get(ContentIdea, d.content_idea_id) if d.content_idea_id else None
    if idea is None:
        raise LookupError("draft has no content idea")
    ctx = await seed_context(session, idea.seed_type, idea.seed_id, idea.seed_text)
    answer_ids = [uuid.UUID(x) for x in (d.ready_override or {}).get("_answer_raw_ids", [])]
    raw = await raw_for(session, ctx.title + " " + idea.thesis)
    if answer_ids:
        raw = [*await raw_for(session, "", ids=answer_ids), *[r for r in raw if r.id not in answer_ids]]
    if idea.seed_type == "build_log":  # the build log is the only source of personal facts (§8.5)
        raw = []
    return idea, ctx, raw


def _text_of(v: DraftVersion) -> str:
    return "\n\n".join(v.thread) if v.thread else v.body


async def produce(session: AsyncSession, d: Draft, repurpose: str | None = None) -> DraftVersion:
    """Dispatch to the text pipeline or the visual/long-form pipeline (M5) by platform."""
    from signal_core.studio.visual import FORMATS, generate_format

    if d.platform in FORMATS:
        return await generate_format(session, d, repurpose=repurpose)
    return await generate(session, d, repurpose=repurpose)


async def generate(
    session: AsyncSession, d: Draft, *, revise: dict[str, Any] | None = None, repurpose: str | None = None
) -> DraftVersion:
    """Writer → (grader → revise ≤ max loops) → checks. Stores every version; current = best."""
    cfg = get_config()
    voice = await active_voice(session)
    idea, ctx, raw = await _context(session, d)
    rules = dict(voice.rules if voice else {})
    banned = list(voice.banned_phrases if voice else cfg.voice.banned_phrases)
    refs = await _references(session, idea.thesis)
    sources = ctx.sources
    if idea.seed_type == "build_log":
        sources = [
            {"id": f"log:{idea.seed_id}", "source": "Build log", "title": ctx.title, "text": ctx.text[:3000]}
        ]
    inputs: dict[str, Any] = {
        "owner": cfg.profile.owner.name,
        "platform": d.platform,
        "platform_label": PLATFORM_LABEL.get(d.platform, d.platform),
        "platform_spec": _platform_spec(d.platform),
        "format_rules": FORMAT_RULES.get(d.platform, ""),
        "voice": {
            "base": rules.get("base", cfg.voice.base),
            "rules": {k: v for k, v in rules.items() if k not in ("base", "banned_patterns", "banned_chars")},
        },
        "banned": banned,
        "references": refs,
        "angle": {"angle_type": idea.angle_type, "thesis": idea.thesis},
        "sources": sources,
        "raw": [{"id": str(r.id), "text": r.text, "can_name": r.can_name} for r in raw],
        "revise": revise,
        "repurpose": repurpose,
    }
    target = float(rules.get("target_score", cfg.voice.target_score))
    loops = int(rules.get("max_revise_loops", cfg.voice.max_revise_loops))
    best: DraftVersion | None = None
    for attempt in range(loops + 1):
        w = await llm.call(
            "writer", inputs, session=session, user_initiated=True, use_cache=attempt == 0 and not revise
        )
        versions = await _store_versions(
            session, d, w, voice.version if voice else 1, sources, raw, rules, banned, refs
        )
        top = max(versions, key=lambda v: (v.grade or {}).get("total", 0))
        if best is None or (top.grade or {}).get("total", 0) > (best.grade or {}).get("total", 0):
            best = top
        if (top.grade or {}).get("total", 0) >= target or attempt == loops:
            break
        inputs = {
            **inputs,
            "revise": {
                "total": top.grade["total"],
                "edits": top.grade.get("top_edits", []),
                "previous": _text_of(top),
            },
        }
    assert best is not None
    d.current_version_id = best.id
    await session.flush()
    return best


async def _store_versions(
    session: AsyncSession,
    d: Draft,
    w: Any,
    voice_version: int,
    sources: list[dict[str, Any]],
    raw: list[RawMaterial],
    rules: dict[str, Any],
    banned: list[str],
    refs: list[str],
) -> list[DraftVersion]:
    n = (
        await session.execute(
            select(func.coalesce(func.max(DraftVersion.version), 0)).where(DraftVersion.draft_id == d.id)
        )
    ).scalar_one()
    claims = [c.model_dump() for c in w.output.claims]
    out = []
    for i, v in enumerate(w.output.versions):
        dv = DraftVersion(
            draft_id=d.id,
            version=n + i + 1,
            label=v.label,
            body=v.body,
            thread=v.thread or None,
            first_comment=v.first_comment,
            claims=claims,
            voice_version=voice_version,
            prompt_version=w.prompt_version,
            model=w.model,
            author="ai",
        )
        session.add(dv)
        out.append(dv)
    await session.flush()
    # The LLM checks of every version run concurrently (each call on its own session); results apply in order.
    results = await asyncio.gather(
        *(_llm_checks(d.platform, _text_of(dv), _fact_payload(dv, sources, raw), refs) for dv in out)
    )
    for dv, res in zip(out, results, strict=True):
        await run_checks(session, d, dv, sources, raw, rules, banned, refs, llm_results=res)
    return out


def _fact_payload(
    dv: DraftVersion, sources: list[dict[str, Any]], raw: list[RawMaterial]
) -> list[dict[str, Any]]:
    by_id = {s["id"]: s for s in sources} | {f"r:{r.id}": {"id": f"r:{r.id}", "text": r.text} for r in raw}
    return [
        {"sentence": c["sentence"], "sources": [by_id[x] for x in c["source_ids"] if x in by_id]}
        for c in dv.claims or []
        if c.get("source_ids")
    ]


async def _isolated_call(task: str, inputs: dict[str, Any]) -> Any:
    """One LLM call on its own short-lived session, so independent checks can run concurrently."""
    from signal_core.db.session import session_scope

    async with session_scope() as s:
        return (await llm.call(task, inputs, session=s, user_initiated=True)).output


async def _llm_checks(
    platform: str, text: str, fact_claims: list[dict[str, Any]], refs: list[str], grade: bool = True
) -> dict[str, Any]:
    """Fact-check, safety and grader for one version, concurrently."""
    conf = get_config().profile.owner.confidential_keywords
    jobs: dict[str, Any] = {"safety": _isolated_call("safety_check", {"text": text, "confidential": conf})}
    if fact_claims:
        jobs["factcheck"] = _isolated_call("factcheck", {"claims": fact_claims})
    if grade:
        jobs["grade"] = _isolated_call(
            "grader",
            {
                "platform": platform,
                "rubric": RUBRIC.get(platform, RUBRIC["linkedin"]),
                "references": refs,
                "draft": text,
            },
        )
    done = await asyncio.gather(*jobs.values())
    return dict(zip(jobs.keys(), done, strict=True))


async def run_checks(
    session: AsyncSession,
    d: Draft,
    dv: DraftVersion,
    sources: list[dict[str, Any]],
    raw: list[RawMaterial],
    rules: dict[str, Any],
    banned: list[str],
    refs: list[str],
    grade: bool = True,
    llm_results: dict[str, Any] | None = None,
) -> None:
    text = _text_of(dv)
    if llm_results is None:
        llm_results = await _llm_checks(d.platform, text, _fact_payload(dv, sources, raw), refs, grade)
    spec = _platform_spec(d.platform)
    sc = (
        scan_thread(dv.thread, rules, banned, spec)
        if dv.thread
        else scan(text, rules, banned, d.platform, spec)
    )
    dv.aitell = sc.as_dict()
    # Claims: every source id must resolve; every factual sentence must be covered by a claim (§9.8).
    allowed = {s["id"] for s in sources} | {f"r:{r.id}" for r in raw}
    bad_ids = sorted({sid for c in dv.claims or [] for sid in c.get("source_ids", []) if sid not in allowed})
    uncited = uncited_factual_sentences(text, dv.claims or [])
    fc = llm_results.get("factcheck")
    fc_results: list[dict[str, Any]] = [x.model_dump() for x in fc.results] if fc is not None else []
    dv.factcheck = {
        "results": fc_results,
        "unknown_source_ids": bad_ids,
        "uncited_sentences": uncited,
        "unsupported": [x["sentence"] for x in fc_results if x["verdict"] == "unsupported"],
        "partially": [x["sentence"] for x in fc_results if x["verdict"] == "partially"],
    }
    dv.checks = {
        "originality": await originality(session, text, sources),
        "safety": {"flags": [f.model_dump() for f in llm_results["safety"].flags]},
        "attribution": attribution(sources),
    }
    g = llm_results.get("grade")
    if grade and g is not None:
        dv.grade = g.model_dump()
        # LLM half of the AI-tell scan: the grader's flagged phrases become advisory highlights (ADR-018).
        issues = list((dv.aitell or {}).get("issues", []))
        for ph in g.ai_phrases:
            idx = text.lower().find(ph.lower())
            issues.append(
                {
                    "type": "ai_phrase",
                    "message": f'Sounds AI-written: "{ph}"',
                    "start": idx,
                    "end": idx + len(ph) if idx >= 0 else -1,
                    "severity": "warn",
                }
            )
        dv.aitell = {**(dv.aitell or {}), "issues": issues}
    await session.flush()


def uncited_factual_sentences(text: str, claims: list[dict[str, Any]]) -> list[str]:
    covered = [norm(c["sentence"]).lower() for c in claims if c.get("source_ids")]
    out = []
    for line in re.split(r"(?<=[.!?])\s+|\n+", text):
        s = line.strip()
        if len(s.split()) < 4 or s.endswith("?") or not FACTUAL.search(s):
            continue
        ns = norm(s).lower().rstrip(".")
        if not any(ns in c or c.rstrip(".") in ns for c in covered):
            out.append(s)
    return out


async def originality(session: AsyncSession, text: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    """vs his last 200 posts (avoid repeating himself) and vs source text (avoid near-copying; quotes ≤ 15 words)."""
    flags = []
    [v] = await get_embedder().embed([text])
    own = list(
        (
            await session.execute(
                select(Publication)
                .where(Publication.embedding.is_not(None))
                .order_by(desc(Publication.published_at))
                .limit(200)
            )
        ).scalars()
    )
    own_refs = list(
        (
            await session.execute(
                select(ReferencePost).where(
                    ReferencePost.is_own.is_(True), ReferencePost.embedding.is_not(None)
                )
            )
        ).scalars()
    )
    sims = [cosine(v, list(p.embedding)) for p in own] + [cosine(v, list(r.embedding)) for r in own_refs]
    top = max(sims, default=0.0)
    if top > 0.92:
        flags.append(
            {"type": "repeat", "message": f"Very similar to one of your past posts (similarity {top:.2f})"}
        )
    words = text.split()
    for s in sources:
        src = " ".join(s.get("text", "").split())
        for i in range(max(len(words) - 15, 0)):
            chunk = " ".join(words[i : i + 16])
            if len(chunk) > 60 and chunk in src:
                flags.append(
                    {
                        "type": "near_copy",
                        "message": f'16+ words copied from {s["source"]}: "{chunk[:80]}…"',
                        "severity": "error",
                    }
                )
                break
    return {"max_similarity_to_own": round(top, 3), "flags": flags}


def attribution(sources: list[dict[str, Any]]) -> list[str]:
    return [
        f'Credit {s["source"]} for "{s["title"][:60]}" (link in first comment)'
        for s in sources[:3]
        if s.get("source")
    ]


# ---------------- gate / lifecycle ----------------
def gate_reasons(dv: DraftVersion) -> list[str]:
    reasons = []
    ait = dv.aitell or {}
    for i in ait.get("issues", []):
        if i.get("severity") == "error":
            reasons.append(f"AI-tell: {i['message']}")
    fc = dv.factcheck or {}
    for s in fc.get("unsupported", []):
        reasons.append(f"Unsupported claim: {s}")
    for s in fc.get("uncited_sentences", []):
        reasons.append(f"Factual sentence without a source: {s}")
    if fc.get("unknown_source_ids"):
        reasons.append(f"Claims cite unknown sources: {fc['unknown_source_ids']}")
    for f in (dv.checks or {}).get("safety", {}).get("flags", []):
        if f.get("severity") == "high":
            reasons.append(f"Safety: {f['type']} ({f['text']})")
    for f in (dv.checks or {}).get("originality", {}).get("flags", []):
        if f.get("severity") == "error":
            reasons.append(f"Originality: {f['message']}")
    return reasons


async def current_version(session: AsyncSession, d: Draft) -> DraftVersion:
    dv = await session.get(DraftVersion, d.current_version_id) if d.current_version_id else None
    if dv is None:
        raise LookupError("draft has no version yet (answer the ask-me questions first)")
    return dv


async def mark_ready(session: AsyncSession, d: Draft, override_reason: str | None = None) -> Draft:
    dv = await current_version(session, d)
    reasons = gate_reasons(dv)
    if reasons and not override_reason:
        raise GateError(reasons)
    if reasons:
        d.ready_override = {
            **(d.ready_override or {}),
            "reason": override_reason,
            "overridden": reasons,
            "at": datetime.now(UTC).isoformat(),
        }
    d.status, d.approved_at = "ready", datetime.now(UTC)
    await session.flush()
    return d


async def human_edit(
    session: AsyncSession, d: Draft, body: str | None, thread: list[str] | None, first_comment: str | None
) -> DraftVersion:
    prev = await current_version(session, d)
    n = (
        await session.execute(select(func.max(DraftVersion.version)).where(DraftVersion.draft_id == d.id))
    ).scalar_one()
    dv = DraftVersion(
        draft_id=d.id,
        version=n + 1,
        label=prev.label,
        body=body if body is not None else prev.body,
        thread=thread if thread is not None else prev.thread,
        first_comment=first_comment if first_comment is not None else prev.first_comment,
        claims=prev.claims,
        voice_version=prev.voice_version,
        prompt_version="human",
        model="human",
        author="human",
        grade=prev.grade,
    )
    session.add(dv)
    await session.flush()
    voice = await active_voice(session)
    _idea, ctx, raw = await _context(session, d)
    await run_checks(
        session,
        d,
        dv,
        ctx.sources,
        raw,
        dict(voice.rules if voice else {}),
        list(voice.banned_phrases if voice else []),
        [],
        grade=False,
    )
    d.current_version_id = dv.id
    if d.status == "ready":
        d.status = "drafting"  # edits re-enter the gate
    await session.flush()
    return dv


async def repurpose(session: AsyncSession, d: Draft, platform: str) -> Draft:
    """Same core message and claims, rewritten natively — never copy-paste (§7.6)."""
    dv = await current_version(session, d)
    nd = Draft(
        content_idea_id=d.content_idea_id,
        platform=platform,
        format="thread" if platform == "x_thread" else "post",
        status="drafting",
        parent_draft_id=d.id,
        timeliness_deadline=d.timeliness_deadline,
        ready_override={"_answer_raw_ids": (d.ready_override or {}).get("_answer_raw_ids", [])},
    )
    session.add(nd)
    await session.flush()
    await produce(session, nd, repurpose=_text_of(dv))
    return nd


def publish_assist(d: Draft, dv: DraftVersion) -> dict[str, Any]:
    plat = get_config().platforms.model_dump()
    key = "x" if d.platform in ("x", "x_thread") else d.platform
    composer = (plat.get(key) or {}).get("composer_url")
    return {
        "platform": d.platform,
        "text": _text_of(dv),
        "thread": dv.thread,
        "first_comment": dv.first_comment,
        "composer_url": composer,
        "note": "Copy the text, open the composer, post, then tap Posted and paste the URL.",
    }


async def mark_published(
    session: AsyncSession, d: Draft, url: str, published_at: datetime | None
) -> Publication:
    dv = await current_version(session, d)
    text = _text_of(dv)
    [v] = await get_embedder().embed([text])
    idea = await session.get(ContentIdea, d.content_idea_id) if d.content_idea_id else None
    pub = Publication(
        draft_id=d.id,
        platform=d.platform,
        url=url,
        published_at=published_at or datetime.now(UTC),
        text=text,
        embedding=v,
        variables={
            "hook_type": idea.angle_type if idea else None,
            "format": d.format,
            "length_bucket": "short"
            if len(text.split()) < 60
            else ("medium" if len(text.split()) < 150 else "long"),
            "emoji_count": (dv.aitell or {}).get("counters", {}).get("emoji", 0),
            "voice_version": dv.voice_version,
            "label": dv.label,
            "time_slot": (published_at or datetime.now(UTC)).strftime("%a %H:00"),
        },
    )
    session.add(pub)
    d.status = "published"
    if idea:
        idea.status = "used"
    await session.flush()
    return pub
