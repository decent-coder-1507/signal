"""Benchmark builder (ADR-026): samples real items from a SCRATCH copy of the database and labels them with Claude.

Run once, in live mode, against a restored copy (never the main `signal` database):
    SIGNAL_DATABASE_URL=…/signal_bench SIGNAL_MODE=live SIGNAL_EMBEDDING_PROVIDER=fastembed \\
    python -m signal_core.ops.bench build all
Every LLM call goes through llm.router.call (Claude Runner, ledger, cache). Outputs land in fixtures/bench/.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import uuid
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from signal_core.config import get_config
from signal_core.db.models import Item, ItemEnrichment, Source
from signal_core.db.session import session_scope
from signal_core.llm import router as llm
from signal_core.ops.bench.data import (
    FIXTURE_DIR,
    BenchItem,
    Label,
    Pair,
    Question,
    load,
    save_items,
    save_meta,
    save_pairs,
    save_questions,
    write_jsonl,
)
from signal_core.settings import get_settings

T = TypeVar("T")
SEED = 26
META_KEYS = ("hn_points_per_hour", "gh_stars_period", "hf_likes", "hf_upvotes", "also_from")
PAIR_BINS = [(0.62, 0.70), (0.70, 0.76), (0.76, 0.80), (0.80, 0.84), (0.84, 0.88), (0.88, 0.95)]
CONCURRENCY = 4


def guard_db() -> str:
    """Refuse to touch anything but a scratch benchmark database."""
    name = make_url(get_settings().database_url).database or ""
    if not name.startswith("signal_bench"):
        raise SystemExit(f"bench build only runs against a scratch DB named signal_bench* (got {name!r})")
    return name


def split_of(item_id: str) -> str:
    return "train" if int(hashlib.sha1(item_id.encode()).hexdigest(), 16) % 2 == 0 else "test"


async def gather_limited[T](fns: list[Callable[[], Awaitable[T]]], n: int = CONCURRENCY) -> list[T]:
    sem = asyncio.Semaphore(n)

    async def run(f: Callable[[], Awaitable[T]]) -> T:
        async with sem:
            return await f()

    return list(await asyncio.gather(*(run(f) for f in fns)))


async def call(task: str, inputs: dict[str, Any], **kw: Any) -> Any:
    async with session_scope() as s:
        return await llm.call(task, inputs, session=s, **kw)


# ---------------------------------------------------------------- reset
async def reset() -> dict[str, Any]:
    """Drop the MOCK enrichments/stories/insights/ledger rows the restored copy carries, reopen those items, and
    rebuild the profile vectors with the live embedder."""
    from signal_core.db.models import Profile
    from signal_core.services.seed import rebuild_profile_vectors

    guard_db()
    async with session_scope() as s:
        before: dict[str, int] = dict(
            (await s.execute(text("select status, count(*) from items group by 1"))).tuples().all()
        )
        await s.execute(
            text(
                "truncate story_insights, story_items, stories, item_entities, entities, item_enrichments, "
                "llm_calls, llm_cache cascade"
            )
        )
        await s.execute(text("update items set status = 'new' where status = 'enriched'"))
        p = (await s.execute(select(Profile))).scalar_one()
        await rebuild_profile_vectors(s, p)
        after: dict[str, int] = dict(
            (await s.execute(text("select status, count(*) from items group by 1"))).tuples().all()
        )
    return {"before": before, "after": after}


# ---------------------------------------------------------------- corpus
ROW_SQL = """
select i.id::text as id, s.name as source, s.type as source_type, s.tier, s.ring as source_ring, i.title,
       left(i.text, 1200) as text, i.published_at, i.content_type, i.status, i.signal_meta,
       i.embedding::text as emb
from items i join sources s on s.id = i.source_id
where i.status <> 'duplicate' and i.duplicate_of is null and i.embedding is not null
"""


async def corpus() -> list[Any]:
    async with session_scope() as s:
        return list((await s.execute(text(ROW_SQL))).all())


def to_item(r: Any, stratum: str) -> BenchItem:
    meta = {k: v for k, v in (r.signal_meta or {}).items() if k in META_KEYS}
    return BenchItem(
        id=r.id,
        source=r.source,
        source_type=r.source_type,
        tier=int(r.tier),
        source_ring=r.source_ring,
        title=r.title,
        text=r.text or "",
        published_at=r.published_at.astimezone(UTC),
        content_type=r.content_type,
        stratum=stratum,
        split=split_of(r.id),
        signal_meta=meta,
    )


def round_robin(rows: list[Any], n: int, rng: random.Random) -> list[Any]:
    by_src: dict[str, list[Any]] = defaultdict(list)
    for r in rows:
        by_src[r.source].append(r)
    for v in by_src.values():
        rng.shuffle(v)
    srcs = sorted(by_src)
    rng.shuffle(srcs)
    out: list[Any] = []
    while len(out) < n and any(by_src[s] for s in srcs):
        for s in srcs:
            if by_src[s] and len(out) < n:
                out.append(by_src[s].pop())
    return out


async def sample(n_rejected: int = 120, n_passed: int = 180) -> dict[str, Any]:
    guard_db()
    rows = await corpus()
    rng = random.Random(SEED)
    rejected = [r for r in rows if r.status == "prefiltered_out"]
    passed = [r for r in rows if r.status != "prefiltered_out"]
    bench = load()
    bench.items = {}
    for r in round_robin(rejected, n_rejected, rng):
        bench.items[r.id] = to_item(r, "rejected")
    for r in round_robin(passed, n_passed, rng):
        bench.items[r.id] = to_item(r, "passed")
    for r in rows:
        if r.id in bench.items:
            bench.cache.put(bench.items[r.id].embed_text, json.loads(r.emb))
    bench.meta["population"] = {"rejected": len(rejected), "passed": len(passed), "corpus": len(rows)}
    bench.meta["sample"] = dict(Counter(i.stratum for i in bench.items.values()))
    bench.meta["built_at"] = datetime.now(UTC).date().isoformat()
    save_items(bench)
    bench.cache.save()
    save_meta(bench.meta)
    return bench.meta


def _matrix(rows: list[Any]) -> tuple[np.ndarray, np.ndarray]:
    e = np.asarray([json.loads(r.emb) for r in rows], dtype=np.float32)
    e /= np.linalg.norm(e, axis=1, keepdims=True)
    t = np.asarray([r.published_at.timestamp() for r in rows], dtype=np.float64)
    return e, t


async def pairs(
    per_bin: int = 20,
    n_random: int = 30,
    window_days: int = 7,
    bins: list[tuple[float, float]] | None = None,
    append: bool = False,
    seed: int = SEED,
) -> list[Pair]:
    """Candidate same-event pairs: cosine-stratified nearest pairs within a week (mostly cross-source), plus random
    same-week pairs. `append` adds to the existing pairs (new ids, no repeats)."""
    guard_db()
    bins = bins or PAIR_BINS
    existing = load().pairs if append else []
    have = {frozenset((p.a, p.b)) for p in existing}
    rows = await corpus()
    e, t = _matrix(rows)
    win = window_days * 86400
    rng = random.Random(seed)
    cand: dict[int, list[tuple[int, int, float]]] = defaultdict(list)
    seen_per_bin: Counter[int] = Counter()
    for start in range(0, len(rows), 1000):
        sims = e[start : start + 1000] @ e.T
        for bi, (lo, hi) in enumerate(bins):
            ii, jj = np.nonzero((sims >= lo) & (sims < hi))
            for i, j in zip(ii.tolist(), jj.tolist(), strict=True):
                gi = start + i
                if j <= gi or abs(t[gi] - t[j]) > win or frozenset((rows[gi].id, rows[j].id)) in have:
                    continue
                seen_per_bin[bi] += 1
                # reservoir sample (cap memory: some feeds have thousands of near-identical posts)
                if len(cand[bi]) < 4000:
                    cand[bi].append((gi, j, float(sims[i, j])))
                else:
                    k = rng.randrange(seen_per_bin[bi])
                    if k < 4000:
                        cand[bi][k] = (gi, j, float(sims[i, j]))
    out: list[Pair] = list(existing)
    used: Counter[int] = Counter()
    for bi in range(len(bins)):
        pool = cand[bi]
        rng.shuffle(pool)
        combo: Counter[tuple[str, str]] = Counter()
        picked: list[tuple[int, int, float]] = []
        # 60% cross-source first, then fill with same-source pairs
        for cross in (True, False):
            want = int(per_bin * 0.6) if cross else per_bin
            for i, j, sim in pool:
                if len(picked) >= want:
                    break
                a, b = rows[i], rows[j]
                if (a.source != b.source) != cross or used[i] >= 2 or used[j] >= 2:
                    continue
                key = (min(a.source, b.source), max(a.source, b.source))
                if combo[key] >= 3 or (i, j, sim) in picked:
                    continue
                combo[key] += 1
                used[i] += 1
                used[j] += 1
                picked.append((i, j, sim))
        out += [
            Pair(f"p{len(out) + k:03d}", rows[i].id, rows[j].id, round(s, 4), "knn")
            for k, (i, j, s) in enumerate(picked)
        ]
    order = np.argsort(t)
    pos = {int(ix): k for k, ix in enumerate(order)}
    n_random += sum(1 for p in existing if p.kind == "random")
    while sum(1 for p in out if p.kind == "random") < n_random:
        i = rng.randrange(len(rows))
        k = pos[i] + rng.randint(-40, 40)
        if not 0 <= k < len(rows):
            continue
        j = int(order[k])
        if i == j or abs(t[i] - t[j]) > win:
            continue
        sim = float(e[i] @ e[j])
        if sim >= 0.95:
            continue
        out.append(Pair(f"p{len(out):03d}", rows[i].id, rows[j].id, round(sim, 4), "random"))
    # pair-only items join the fixture (unlabelled for relevance)
    bench = load()
    by_id = {r.id: r for r in rows}
    for p in out:
        for x in (p.a, p.b):
            if x not in bench.items:
                bench.items[x] = to_item(by_id[x], "pair")
                bench.cache.put(bench.items[x].embed_text, json.loads(by_id[x].emb))
    save_items(bench)
    save_pairs(out)
    bench.cache.save()
    return out


# ---------------------------------------------------------------- labelling
def profile_brief() -> dict[str, Any]:
    p = get_config().profile

    def fmt(ts: list[Any]) -> list[str]:
        return [f"{t.name} ({', '.join(t.keywords[:8])})" for t in ts]

    return {
        "role": p.owner.role,
        "goals": p.owner.goals,
        "stack": p.owner.stack,
        "core": fmt(p.topics.core),
        "adjacent": fmt(p.topics.adjacent),
    }


def _brief_item(it: BenchItem, alias: str, chars: int) -> dict[str, Any]:
    return {
        "id": alias,
        "title": it.title,
        "source": it.source,
        "date": it.published_at.date().isoformat(),
        "text": " ".join(it.text.split())[:chars],
    }


async def label_items(
    items: list[BenchItem], tier: str | None = None, batch: int = 15, use_cache: bool = True
) -> dict[str, tuple[Label, str]]:
    prof = profile_brief()
    batches = [items[k : k + batch] for k in range(0, len(items), batch)]

    async def one(b: list[BenchItem]) -> dict[str, tuple[Label, str]]:
        alias = {f"i{n + 1}": it for n, it in enumerate(b)}
        inputs = {"profile": prof, "items": [_brief_item(it, a, 700) for a, it in alias.items()]}
        r = await call("bench_label_items", inputs, tier=tier, use_cache=use_cache)
        out = {}
        for lab in r.output.labels:
            it = alias.get(lab.id)
            if it is not None:
                out[it.id] = (Label(lab.relevance, lab.ring, lab.reason.strip()), r.model)
        return out

    got: dict[str, tuple[Label, str]] = {}
    for d in await gather_limited([lambda b=b: one(b) for b in batches]):  # type: ignore[misc]
        got.update(d)
    missing = [it for it in items if it.id not in got]
    if missing:  # one retry round for items the model skipped
        for d in await gather_limited(
            [lambda b=b: one(b) for b in [missing[k : k + batch] for k in range(0, len(missing), batch)]]  # type: ignore[misc]
        ):
            got.update(d)
    return got


async def label() -> dict[str, Any]:
    bench = load()
    todo = [i for i in bench.items.values() if i.stratum in ("rejected", "passed") and i.label is None]
    got = await label_items(todo)
    models: Counter[str] = Counter()
    for iid, (lab, model) in got.items():
        bench.items[iid].label = lab
        models[model] += 1
    bench.meta.setdefault("labeller", {})["items"] = {"task": "bench_label_items/v1", "models": dict(models)}
    save_items(bench)
    save_meta(bench.meta)
    return {"labelled": len(got), "of": len(todo)}


async def agreement(n: int = 60) -> dict[str, Any]:
    """Second, independent labeller (deep tier) on a random subset: how far can the labels be trusted?"""
    bench = load()
    rng = random.Random(SEED + 1)
    pool = sorted(bench.labelled, key=lambda i: i.id)
    rng.shuffle(pool)
    sub = pool[:n]
    got = await label_items(sub, tier="deep", use_cache=False)
    rows = [
        {
            "item_id": i.id,
            "primary": i.label.relevance if i.label else None,
            "second": got[i.id][0].relevance,
            "second_ring": got[i.id][0].ring,
            "second_reason": got[i.id][0].reason,
            "second_model": got[i.id][1],
        }
        for i in sub
        if i.id in got
    ]
    write_jsonl(FIXTURE_DIR / "agreement.jsonl", rows)
    return {"rows": len(rows)}


async def label_pairs(batch: int = 15) -> dict[str, Any]:
    bench = load()
    todo = [p for p in bench.pairs if p.same_event is None]
    batches = [todo[k : k + batch] for k in range(0, len(todo), batch)]

    def side(it: BenchItem) -> dict[str, Any]:
        return {
            "title": it.title,
            "source": it.source,
            "date": it.published_at.date().isoformat(),
            "text": " ".join(it.text.split())[:450],
        }

    async def one(b: list[Pair]) -> dict[str, tuple[bool, str, str]]:
        inputs = {
            "pairs": [{"id": p.id, "a": side(bench.items[p.a]), "b": side(bench.items[p.b])} for p in b]
        }
        r = await call("bench_label_pairs", inputs)
        return {x.id: (x.same_event, x.reason.strip(), r.model) for x in r.output.pairs}

    got: dict[str, tuple[bool, str, str]] = {}
    for d in await gather_limited([lambda b=b: one(b) for b in batches]):  # type: ignore[misc]
        got.update(d)
    models: Counter[str] = Counter()
    for p in bench.pairs:
        if p.id in got:
            p.same_event, p.reason, m = got[p.id]
            models[m] += 1
    bench.meta.setdefault("labeller", {})["pairs"] = {"task": "bench_label_pairs/v1", "models": dict(models)}
    save_pairs(bench.pairs)
    save_meta(bench.meta)
    return {"labelled": len(got), "of": len(todo)}


# ---------------------------------------------------------------- enrichment (real P1 → entities, ring, tech)
async def enrich() -> dict[str, Any]:
    """Run the real enrich_items task on every benchmark item: LLM calls run in parallel to pre-warm the cache,
    then enrich_pending applies them in order (cache hits) with the product's validators."""
    from signal_core.radar.cluster import entity_tags
    from signal_core.radar.enrich import BATCH, enrich_inputs, enrich_pending, enrich_topics

    guard_db()
    bench = load()
    ids = sorted(bench.items)
    async with session_scope() as s:
        done = {
            str(x)
            for x in (await s.execute(select(ItemEnrichment.item_id))).scalars()
            if str(x) in bench.items
        }
        todo_ids = [uuid.UUID(i) for i in ids if i not in done]
        items = list((await s.execute(select(Item).where(Item.id.in_(todo_ids)))).scalars())
        items.sort(key=lambda i: str(i.id))
        sources = {x.id: x for x in (await s.execute(select(Source))).scalars()}
        topics = enrich_topics()
        payloads = [enrich_inputs(items[k : k + BATCH], sources, topics) for k in range(0, len(items), BATCH)]

    async def warm(p: dict[str, Any]) -> None:
        try:
            await call("enrich_items", p)
        except Exception as e:  # applied (and retried) sequentially below
            print("warm failed:", str(e)[:200])

    await gather_limited([lambda p=p: warm(p) for p in payloads])  # type: ignore[misc]
    async with session_scope() as s:
        items = list((await s.execute(select(Item).where(Item.id.in_(todo_ids)))).scalars())
        items.sort(key=lambda i: str(i.id))
        st = await enrich_pending(s, datetime.now(UTC), items=items)
    async with session_scope() as s:
        rows = (
            await s.execute(
                select(ItemEnrichment).where(ItemEnrichment.item_id.in_([uuid.UUID(i) for i in ids]))
            )
        ).scalars()
        for e in rows:
            it = bench.items[str(e.item_id)]
            it.entities = entity_tags(e.entities or {})
            it.enrich = {
                "ring": e.ring,
                "tech_relevance": e.tech_relevance,
                "summary_1line": e.summary_1line,
                "is_primary_source": e.is_primary_source,
                "model": e.model,
            }
    save_items(bench)
    return {
        "enriched": st.enriched,
        "batches": st.batches,
        "with_enrichment": sum(1 for i in bench.items.values() if i.enrich),
    }


# ---------------------------------------------------------------- neighbours (story proxy for signal/momentum)
async def neighbours(min_sim: float = 0.78, before_days: int = 7, after_days: int = 2) -> dict[str, Any]:
    guard_db()
    rows = await corpus()
    e, t = _matrix(rows)
    bench = load()
    idx = {r.id: k for k, r in enumerate(rows)}
    n = 0
    for it in bench.labelled:
        k = idx.get(it.id)
        if k is None:
            continue
        sims = e @ e[k]
        dt = t - t[k]
        ok = np.nonzero((sims >= min_sim) & (dt >= -before_days * 86400) & (dt <= after_days * 86400))[0]
        nb = []
        for j in sorted(ok.tolist(), key=lambda j: -sims[j])[:30]:
            if j == k:
                continue
            r = rows[j]
            nb.append(
                {
                    "source": r.source,
                    "tier": int(r.tier),
                    "type": r.source_type,
                    "published_at": r.published_at.astimezone(UTC).isoformat(),
                    "sim": round(float(sims[j]), 4),
                    "signal_meta": {k2: v for k2, v in (r.signal_meta or {}).items() if k2 in META_KEYS},
                }
            )
        it.neighbours = nb
        n += len(nb)
    save_items(bench)
    return {"neighbours": n}


# ---------------------------------------------------------------- Ask questions
async def questions(n: int = 30) -> dict[str, Any]:
    bench = load()
    rng = random.Random(SEED + 2)
    pool = [i for i in bench.labelled if i.label and i.label.relevance >= 2 and len(i.text) >= 300]
    chosen = round_robin(pool, n, rng)  # BenchItem has .source like the DB rows
    batches = [chosen[k : k + 15] for k in range(0, len(chosen), 15)]

    async def one(b: list[BenchItem]) -> list[Question]:
        alias = {f"i{k + 1}": it for k, it in enumerate(b)}
        r = await call("bench_questions", {"items": [_brief_item(it, a, 900) for a, it in alias.items()]})
        return [
            Question(f"q-{alias[q.id].id[-12:]}", q.question.strip(), alias[q.id].id)
            for q in r.output.questions
            if q.id in alias
        ]

    qs: list[Question] = []
    for lst in await gather_limited([lambda b=b: one(b) for b in batches]):  # type: ignore[misc]
        qs += lst
    save_questions(sorted(qs, key=lambda q: q.id))
    return {"questions": len(qs)}


# ---------------------------------------------------------------- LLM judge on a small subset
async def judge(n: int = 40) -> dict[str, Any]:
    bench = load()
    rng = random.Random(SEED + 3)
    by_rel: dict[int, list[BenchItem]] = defaultdict(list)
    for i in sorted(bench.labelled, key=lambda i: i.id):
        if i.split == "test" and i.label is not None:
            by_rel[i.label.relevance].append(i)
    chosen: list[BenchItem] = []
    for rel in (3, 2, 1, 0):
        rng.shuffle(by_rel[rel])
    while len(chosen) < n and any(by_rel.values()):
        for rel in (3, 2, 1, 0):
            if by_rel[rel] and len(chosen) < n:
                chosen.append(by_rel[rel].pop())
    p = get_config().profile
    pinfo = {
        "role": p.owner.role,
        "goals": p.owner.goals,
        "stack": p.owner.stack,
        "topics": [t.name for ring in ("core", "adjacent", "wide") for t in getattr(p.topics, ring)],
    }

    async def one(it: BenchItem) -> dict[str, Any]:
        summary = (it.enrich or {}).get("summary_1line") or it.title
        r = await call(
            "relevance_judge", {"profile": pinfo, "story": {"title": it.title, "summaries": [summary]}}
        )
        return {"item_id": it.id, "judge": r.output.model_dump(), "model": r.model}

    rows = await gather_limited([lambda it=it: one(it) for it in chosen])  # type: ignore[misc]
    write_jsonl(FIXTURE_DIR / "judge.jsonl", sorted(rows, key=lambda r: r["item_id"]))
    return {"judged": len(rows)}


# ---------------------------------------------------------------- spot check
def spotcheck(n: int = 30) -> str:
    bench = load()
    rng = random.Random(SEED + 4)
    pool = sorted(bench.labelled, key=lambda i: i.id)
    rng.shuffle(pool)
    names = {0: "0 irrelevant", 1: "1 tangential", 2: "2 relevant", 3: "3 must-read"}

    def cell(s: str) -> str:
        return " ".join(s.replace("|", "/").split())

    lines = [
        "# Benchmark label spot check (ADR-026)",
        "",
        "Thirty randomly chosen relevance labels written by Claude (`bench_label_items`, balanced tier) for the "
        "real-data benchmark. They are model judgements used only to measure SIGNAL's engines and are never shown as "
        "facts in the product. Please mark each row `y` (you agree) or `n` (you don't), and add a note if useful. "
        "If more than about 5 of 30 are `n`, the labeller prompt needs work before the benchmark numbers are trusted.",
        "",
        "Scale: 3 must-read · 2 relevant · 1 tangential · 0 irrelevant. Ring: core / adjacent / wide / none.",
        "",
        "| # | Item title | Source | Date | Label | Ring | Labeller's reason | agree? (y/n) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for k, it in enumerate(pool[:n], 1):
        assert it.label is not None
        lines.append(
            f"| {k} | {cell(it.title)[:110]} | {cell(it.source)} | {it.published_at.date().isoformat()} | "
            f"{names[it.label.relevance]} | {it.label.ring} | {cell(it.label.reason)} |  |"
        )
    out = "\n".join(lines) + "\n"
    (FIXTURE_DIR / "SPOTCHECK.md").write_text(out, encoding="utf-8", newline="\n")
    return out


async def ledger() -> dict[str, Any]:
    async with session_scope() as s:
        rows = (
            await s.execute(
                text("select task, status, model, count(*) from llm_calls group by 1, 2, 3 order by 1, 2")
            )
        ).all()
    return {"calls": [list(r) for r in rows], "total_live": sum(r[3] for r in rows if r[1] != "cached")}


async def pairs_more() -> dict[str, Any]:
    """More high-similarity candidates around the join/merge thresholds (the first round had 30 positives)."""
    before = len(load().pairs)
    out = await pairs(
        per_bin=15,
        n_random=0,
        bins=[(0.78, 0.82), (0.82, 0.86), (0.86, 0.90), (0.90, 0.95)],
        append=True,
        seed=SEED + 10,
    )
    return {"added": len(out) - before, "total": len(out)}


async def refresh_text() -> dict[str, Any]:
    """Store up to 4,000 characters of text (what the prefilter's keyword pass reads)."""
    guard_db()
    bench = load()
    async with session_scope() as s:
        rows = (
            await s.execute(
                text(
                    "select id::text as id, left(text, 4000) as body from items where id = any(cast(:ids as uuid[]))"
                ),
                {"ids": list(bench.items)},
            )
        ).all()
    for r in rows:
        it = bench.items[r.id]
        emb_text = it.embed_text
        it.text = r.body or ""
        assert it.embed_text == emb_text
    save_items(bench)
    return {"items": len(rows)}


async def centroids() -> dict[str, Any]:
    """Keyword-seeded topic centroids from the whole corpus, via the product code (seed.rebuild_topic_centroids)."""
    from signal_core.db.models import Profile, ProfileVector
    from signal_core.ops.bench.engines import CENTROID_KEY
    from signal_core.services.seed import rebuild_topic_centroids

    guard_db()
    bench = load()
    async with session_scope() as s:
        p = (await s.execute(select(Profile))).scalar_one()
        p.topics = {
            ring: [t.model_dump() for t in getattr(get_config().profile.topics, ring)]
            for ring in ("core", "adjacent", "wide")
        }
        n = await rebuild_topic_centroids(s, p)
        rows = (await s.execute(select(ProfileVector).where(ProfileVector.kind == "centroid"))).scalars()
        for r in rows:
            bench.cache.put(CENTROID_KEY + r.label, list(r.embedding))
    bench.cache.save()
    return {"centroids": n}


async def ask_distractors(per_question: int = 25) -> dict[str, Any]:
    """Hard negatives for Ask: each question target's nearest corpus items (any status) join the fixture as
    unlabelled 'distractor' items, so retrieval is not measured on an easy 600-item corpus."""
    guard_db()
    rows = await corpus()
    e, _t = _matrix(rows)
    bench = load()
    idx = {r.id: k for k, r in enumerate(rows)}
    added = 0
    for q in bench.questions:
        k = idx[q.item_id]
        sims = e @ e[k]
        for j in np.argsort(-sims)[1 : per_question + 1].tolist():
            r = rows[j]
            if r.id not in bench.items:
                bench.items[r.id] = to_item(r, "distractor")
                bench.cache.put(bench.items[r.id].embed_text, json.loads(r.emb))
                added += 1
    async with session_scope() as s:  # full 4,000-character text, like refresh_text
        got = (
            await s.execute(
                text(
                    "select id::text as id, left(text, 4000) as body from items where id = any(cast(:ids as uuid[]))"
                ),
                {"ids": [i for i, it in bench.items.items() if it.stratum == "distractor"]},
            )
        ).all()
    for r in got:
        bench.items[r.id].text = r.body or ""
    save_items(bench)
    bench.cache.save()
    return {"added": added, "items": len(bench.items)}


STEPS: dict[str, Callable[[], Awaitable[Any]]] = {
    "ask-distractors": ask_distractors,
    "refresh-text": refresh_text,
    "centroids": centroids,
    "pairs-more": pairs_more,
    "reset": reset,
    "sample": sample,
    "pairs": pairs,
    "label": label,
    "label-pairs": label_pairs,
    "enrich": enrich,
    "neighbours": neighbours,
    "questions": questions,
    "judge": judge,
    "agreement": agreement,
    "ledger": ledger,
}
ALL = ["sample", "pairs", "label", "label-pairs", "enrich", "neighbours", "questions", "judge", "agreement"]


async def run_step(name: str) -> Any:
    if name == "spotcheck":
        return spotcheck()
    if name == "all":
        out = {}
        for n in ALL:
            out[n] = await STEPS[n]()
            print(n, json.dumps(out[n], default=str)[:300], flush=True)
        spotcheck()
        return out
    return await STEPS[name]()
