"""Ask SIGNAL (§11.1): chat over the knowledge base with citations.

Retrieval: hybrid — pgvector cosine + Postgres full-text (websearch_to_tsquery) over items, story insights, notes,
ideas, build logs and explainers, fused with reciprocal-rank fusion (RRF); time-aware ("this week", "today",
"last month", "since March 2026"). Answer: P15 (balanced) with chunk ids; citations validated; when nothing relevant
is retrieved the answer is an honest "Not in your knowledge base" with an offer to create a watch.
In live mode the Claude Runner may also call SIGNAL's read-only MCP tools for extra context (ADR-020).
Raw-material entries are private by default and only included when `ask.include_raw_materials` is on.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from dateutil import parser as dtparser
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import ChatMessage, ChatThread
from signal_core.embeddings import get_embedder
from signal_core.llm import router as llm
from signal_core.llm.provider import Msg
from signal_core.services.settings_store import flag
from signal_core.settings import get_settings
from signal_core.truth import CITE, check_citations, strip_unknown_citations

NOT_IN_KB = "Not in your knowledge base yet."
RRF_K = 60
SLASH = re.compile(r"^/(compare|timeline|explain|whatchanged)\b\s*(.*)$", re.I | re.S)
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"


@dataclass
class Chunk:
    id: str
    kind: str
    title: str
    text: str
    url: str | None
    at: datetime | None
    score: float = 0.0


def _iso_date(d: datetime | None) -> str | None:
    return d.date().isoformat() if d else None


def time_window(q: str, now: datetime) -> tuple[datetime | None, str]:
    ql = q.lower()
    rules = [
        (r"\btoday\b", timedelta(days=1)),
        (r"\byesterday\b", timedelta(days=2)),
        (r"\bthis week\b|\bpast week\b|\blast 7 days\b", timedelta(days=7)),
        (r"\blast week\b", timedelta(days=14)),
        (r"\bthis month\b|\blast 30 days\b", timedelta(days=30)),
        (r"\blast month\b", timedelta(days=60)),
    ]
    for rx, dt in rules:
        if re.search(rx, ql):
            return now - dt, re.sub(rx, " ", q, flags=re.I).strip()
    m = re.search(rf"\bsince\s+((?:{MONTHS})(?:\s+\d{{4}})?|\d{{4}}-\d{{2}}-\d{{2}})", ql)
    if m:
        try:
            d = dtparser.parse(m.group(1), default=datetime(now.year, 1, 1))
            if d.replace(tzinfo=UTC) > now:
                d = d.replace(year=d.year - 1)
            return d.replace(tzinfo=UTC), (q[: m.start()] + q[m.end() :]).strip()
        except (ValueError, OverflowError):
            pass
    return None, q


SOURCES_SQL = {
    "item": (
        "select i.id::text as id, i.title, left(i.text, 1500) as body, i.canonical_url as url, i.published_at as at "
        "from items i where i.status in ('enriched','new') and i.duplicate_of is null",
        "i",
    ),
    "story": (
        "select s.id::text as id, s.title, si.what_happened as body, null as url, s.last_updated as at "
        "from stories s join lateral (select what_happened from story_insights x where x.story_id = s.id "
        "order by version desc limit 1) si on true where s.status = 'active'",
        "s",
    ),
    "note": (
        "select n.id::text as id, left(n.text, 80) as title, n.text as body, null as url, n.created_at as at "
        "from notes n where true",
        "n",
    ),
    "idea": (
        "select d.id::text as id, d.title, d.one_liner || ' ' || d.problem || ' ' || d.solution as body, null as url, "
        "d.created_at as at from ideas d where d.status <> 'killed'",
        "d",
    ),
    "build_log": (
        "select b.id::text as id, 'Build log' as title, b.text as body, null as url, b.logged_at as at "
        "from build_logs b where true",
        "b",
    ),
    "explainer": (
        "select e.id::text as id, e.topic || ' (' || e.depth || ')' as title, left(e.body, 1500) as body, "
        "null as url, e.created_at as at from explainers e where true",
        "e",
    ),
}


async def retrieve(
    session: AsyncSession,
    query: str,
    now: datetime,
    k: int = 8,
    since: datetime | None = None,
    kinds: tuple[str, ...] | None = None,
) -> list[Chunk]:
    [vec] = await get_embedder().embed([query])
    v = str(list(vec))
    lists: list[list[Chunk]] = []
    tsq = re.sub(r"[^\w\s-]", " ", query)
    for kind, (sql, _a) in SOURCES_SQL.items():
        if kinds and kind not in kinds:
            continue
        where_time = " and at >= :since" if since else ""
        base = f"select * from ({sql}) q where body is not null{where_time}"
        params: dict[str, Any] = {"q": tsq, "since": since}
        fts = (
            await session.execute(
                text(
                    f"select *, ts_rank(to_tsvector('english', coalesce(title,'') || ' ' || body), websearch_to_tsquery("
                    f"'english', :q)) as r from ({base}) z where to_tsvector('english', coalesce(title,'') || ' ' || body) @@ "
                    f"websearch_to_tsquery('english', :q) order by r desc limit 20"
                ),
                params,
            )
        ).all()
        lists.append([Chunk(r.id, kind, r.title or "", r.body or "", r.url, r.at, float(r.r)) for r in fts])
    vec_rows = (
        await session.execute(
            text(
                "select i.id::text as id, i.title, left(i.text, 1500) as body, i.canonical_url as url, i.published_at as at, "
                "1 - (i.embedding <=> cast(:v as vector)) as sim from items i where i.embedding is not null and "
                "i.duplicate_of is null and i.status in ('enriched','new')"
                + (" and i.published_at >= :since" if since else "")
                + " order by i.embedding <=> cast(:v as vector) limit 20"
            ),
            {"v": v, "since": since},
        )
    ).all()
    if not kinds or "item" in kinds:
        floor = 0.55 if get_embedder().name == "fastembed" else 0.12
        lists.append(
            [
                Chunk(r.id, "item", r.title, r.body or "", r.url, r.at, float(r.sim))
                for r in vec_rows
                if float(r.sim) >= floor
            ]
        )
    fused: dict[str, Chunk] = {}
    for lst in lists:
        for rank, c in enumerate(lst):
            if c.id in fused:
                fused[c.id].score += 1 / (RRF_K + rank)
            else:
                c.score = 1 / (RRF_K + rank)
                fused[c.id] = c
    return sorted(fused.values(), key=lambda c: -c.score)[:k]


async def answer(
    session: AsyncSession, question: str, thread_id: uuid.UUID | None, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    q = question.strip()
    if not q:
        raise ValueError("empty question")
    mode, arg = "ask", q
    m = SLASH.match(q)
    if m:
        mode, arg = m.group(1).lower(), m.group(2).strip()
    if mode == "explain":
        from signal_core.gym.service import explainer

        ex, cards = await explainer(session, arg, "engineer")
        return await _save(
            session,
            thread_id,
            q,
            ex.body,
            [],
            {"mode": "explain", "explainer_id": str(ex.id), "cards": len(cards)},
        )
    since, clean = time_window(arg, now)
    retrieval_q = clean
    if mode == "compare":
        retrieval_q = re.sub(r"\bvs\.?\b|\bversus\b", " ", clean, flags=re.I)
    chunks = await retrieve(session, retrieval_q, now, since=since)
    if mode == "timeline":
        chunks = sorted(chunks, key=lambda c: c.at or now)
    if not chunks:
        return await _save(
            session,
            thread_id,
            q,
            f"{NOT_IN_KB} I couldn't find anything about that in your sources"
            + (f" since {since.date().isoformat()}" if since else "")
            + ". Want me to create a watch for it?",
            [],
            {"mode": mode, "not_in_kb": True, "offer_watch": clean},
        )
    history: list[Msg] = []
    if thread_id:
        prev = list(
            (
                await session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.thread_id == thread_id)
                    .order_by(ChatMessage.created_at)
                )
            ).scalars()
        )[-6:]
        history = [Msg("user" if p.role == "user" else "assistant", p.content) for p in prev]
    use_mcp = not get_settings().is_mock and await flag(session, "ask.mcp_tools")
    r = await llm.call(
        "ask",
        {
            "question": q,
            "mode": mode,
            "since": since.date().isoformat() if since else None,
            "chunks": [
                {
                    "id": c.id,
                    "kind": c.kind,
                    "title": c.title,
                    "text": c.text[:1200],
                    "date": c.at.date().isoformat() if c.at else "",
                }
                for c in chunks
            ],
        },
        session=session,
        user_initiated=True,
        messages=history or None,
        use_mcp=use_mcp,
    )
    allowed = {c.id for c in chunks}
    body = strip_unknown_citations(r.output.answer, allowed)
    rep = check_citations(body, allowed, require_every_sentence=False)
    used = sorted({x for x in CITE.findall(body) if x in allowed})
    if r.output.insufficient or not used:
        body = body + ("" if used else f"\n\n{NOT_IN_KB}")
    by_id = {c.id: c for c in chunks}
    cites = [
        {
            "id": i,
            "kind": by_id[i].kind,
            "title": by_id[i].title,
            "url": by_id[i].url,
            "date": _iso_date(by_id[i].at),
        }
        for i in used
    ]
    extra = {"offer_watch": clean} if not used else {}
    return await _save(
        session,
        thread_id,
        q,
        body,
        cites,
        {
            "mode": mode,
            "not_in_kb": not used,
            **extra,
            "unknown_ids_removed": rep.unknown_ids,
            "prompt_version": r.prompt_version,
        },
    )


async def _save(
    session: AsyncSession,
    thread_id: uuid.UUID | None,
    q: str,
    body: str,
    cites: list[dict[str, Any]],
    meta: dict[str, Any],
) -> dict[str, Any]:
    if thread_id is None:
        t = ChatThread(title=q[:120])
        session.add(t)
        await session.flush()
        thread_id = t.id
    session.add(ChatMessage(thread_id=thread_id, role="user", content=q))
    msg = ChatMessage(thread_id=thread_id, role="assistant", content=body, citations=cites)
    session.add(msg)
    await session.flush()
    return {
        "thread_id": str(thread_id),
        "message_id": str(msg.id),
        "answer": body,
        "citations": cites,
        **meta,
    }


async def threads(session: AsyncSession) -> list[ChatThread]:
    return list(
        (await session.execute(select(ChatThread).order_by(desc(ChatThread.updated_at)).limit(50))).scalars()
    )
