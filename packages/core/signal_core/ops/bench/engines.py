"""Engine evaluations on the real-data benchmark (ADR-026).

Each evaluation runs the product code (prefilter(), compatible()/entity_tags(), apply_scores(), ask.retrieve()) on the
committed fixture. The clustering simulation mirrors cluster.assign_item/merge_pass in memory (same thresholds, entity
rule, top-8 candidates, window); the LLM tie-breaker for borderline merges is treated as "not the same event".
"""

from __future__ import annotations

import hashlib
import math
import random
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.config.schemas import AskCfg, ClusterCfg, ScoringCfg
from signal_core.db.models import Story
from signal_core.embeddings import MockEmbeddingProvider
from signal_core.llm.provider import EmbeddingProvider
from signal_core.ops.bench import metrics as M
from signal_core.ops.bench.data import Bench, BenchItem, FixtureEmbedder, load
from signal_core.radar.cluster import compatible
from signal_core.radar.prefilter import CENTROID, ProfileVec, prefilter
from signal_core.radar.scoring import ScoreContext, apply_scores
from signal_core.services.seed import profile_vector_rows

RELEVANT = 2  # label â‰¥ 2 counts as relevant
POOL_SIZE, POOLS, POOL_SEED = 40, 50, 7

# Engine settings before ADR-026, so `run --baseline` can always re-measure the starting point.
BASELINE: dict[str, Any] = {
    "profile_embedder": "mock",  # what the live DB actually had: profile vectors seeded in mock mode
    "prefilter_min": 0.25,
    "prefilter_hybrid": None,
    "cluster": {"join_threshold": 0.82, "merge_threshold": 0.88},
    "weights": {
        "relevance": 0.25,
        "impact": 0.15,
        "signal": 0.15,
        "novelty": 0.10,
        "credibility": 0.10,
        "durability": 0.10,
        "actionability": 0.10,
        "learned": 0.05,
        "momentum": 0.0,
    },
    "ask": {"rerank": False, "fts_mode": "all", "query_prefix": ""},
}


@dataclass
class Variant:
    name: str
    scoring: ScoringCfg
    profile_embedder: str = "fastembed"
    legacy_entity_rule: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def cluster(self) -> ClusterCfg:
        return self.scoring.cluster_for("fastembed")

    @property
    def ask(self) -> AskCfg:
        return self.scoring.ask


def current_variant() -> Variant:
    return Variant("current", get_config().scoring)


def baseline_variant() -> Variant:
    sc = get_config().scoring
    cl = sc.cluster.model_copy(update=BASELINE["cluster"])
    upd: dict[str, Any] = {
        "prefilter_min": BASELINE["prefilter_min"],
        "prefilter_hybrid": BASELINE["prefilter_hybrid"],
        "prefilter_min_by_embedder": {},
        "cluster": cl,
        "cluster_overrides": {k: v for k, v in sc.cluster_overrides.items() if k != "fastembed"},
        "weights": sc.weights.model_copy(update=BASELINE["weights"]),
        "relevance_centroid_scale": {},
        "ask": sc.ask.model_copy(update=BASELINE["ask"]),
    }
    return Variant(
        "baseline",
        sc.model_copy(update=upd),
        profile_embedder=BASELINE["profile_embedder"],
        legacy_entity_rule=True,
    )


def legacy_compatible(a: list[str], b: list[str], min_overlap: int) -> bool:
    """cluster.compatible before ADR-026 (raw tags, exact specific-entity match), kept to re-measure the baseline."""
    sa, sb = set(a), set(b)
    spec_a = {t for t in sa if t.split(":", 1)[0] in ("model", "product", "repo", "paper")}
    spec_b = {t for t in sb if t.split(":", 1)[0] in ("model", "product", "repo", "paper")}
    if spec_a and spec_b:
        return bool(spec_a & spec_b)
    if not sa or not sb:
        return True
    return len(sa & sb) >= min_overlap


# ---------------------------------------------------------------- profile vectors
CENTROID_KEY = "__centroid__:"


async def profile_vecs(embedder: EmbeddingProvider, bench: Bench | None = None) -> list[ProfileVec]:
    """The profile vectors seed.rebuild_profile_vectors would store, plus the keyword-seeded topic centroids that
    seed.rebuild_topic_centroids computed from the full corpus at build time (stored in the embedding cache)."""
    p = get_config().profile
    topics = {
        ring: [t.model_dump() for t in getattr(p.topics, ring)] for ring in ("core", "adjacent", "wide")
    }
    rows = profile_vector_rows(topics, p.owner.goals, p.owner.stack)
    vecs = await embedder.embed([r[4] for r in rows])
    kw = {t["name"]: list(t.get("keywords") or []) for ring in topics.values() for t in ring}
    out = [
        ProfileVec(label, ring, weight, v, kw.get(label, []), kind)
        for (kind, label, ring, weight, _t), v in zip(rows, vecs, strict=True)
    ]
    if bench is not None:
        for ring, ts in topics.items():
            for t in ts:
                c = bench.cache.get(CENTROID_KEY + t["name"])
                if c is not None:
                    out.append(ProfileVec(t["name"], ring, float(t["weight"]), c, kw[t["name"]], CENTROID))
    return out


# ---------------------------------------------------------------- prefilter
def prefilter_scores(
    bench: Bench, items: list[BenchItem], pvs: list[ProfileVec], v: Variant
) -> dict[str, tuple[float, bool]]:
    tp = get_config().profile.topics
    out: dict[str, tuple[float, bool]] = {}
    for it in items:
        r = prefilter(
            bench.vec(it),
            it.title,
            it.text,
            pvs,
            tp.blocked_keywords,
            tp.blocked_entities,
            v.scoring,
            "fastembed",
        )
        out[it.id] = (r.score, (not r.blocked) and r.score >= v.scoring.prefilter_min_for("fastembed"))
    return out


def _weights(bench: Bench, items: list[BenchItem]) -> list[float]:
    pop, smp = bench.meta.get("population", {}), bench.meta.get("sample", {})
    return [
        (pop.get(i.stratum, 1) / max(1, smp.get(i.stratum, 1)))
        if i.stratum in ("rejected", "passed")
        else 1.0
        for i in items
    ]


def prefilter_metrics(bench: Bench, items: list[BenchItem], passed: list[bool]) -> dict[str, float]:
    rel = [bool(i.label and i.label.relevance >= RELEVANT) for i in items]
    p = M.prf(passed, rel)
    w = _weights(bench, items)
    wp = sum(wi for wi, a in zip(w, passed, strict=True) if a)
    wtp = sum(wi for wi, a, r in zip(w, passed, rel, strict=True) if a and r)
    wrel = sum(wi for wi, r in zip(w, rel, strict=True) if r)
    return {
        "recall": round(p.recall, 4),
        "precision": round(p.precision, 4),
        "f1": round(p.f1, 4),
        "pass_rate_sample": round(sum(passed) / max(1, len(passed)), 4),
        # population estimates (strata re-weighted to the 6.9k-item corpus)
        "recall_pop": round(wtp / wrel, 4) if wrel else 0.0,
        "precision_pop": round(wtp / wp, 4) if wp else 0.0,
        "pass_rate_pop": round(wp / sum(w), 4) if w else 0.0,
    }


async def eval_prefilter(bench: Bench, v: Variant, emb: EmbeddingProvider) -> dict[str, Any]:
    items = bench.labelled
    pv_emb: EmbeddingProvider = MockEmbeddingProvider() if v.profile_embedder == "mock" else emb
    pvs = await profile_vecs(pv_emb, bench)
    sc = prefilter_scores(bench, items, pvs, v)
    res = prefilter_metrics(bench, items, [sc[i.id][1] for i in items])
    rel = [bool(i.label and i.label.relevance >= RELEVANT) for i in items]
    res["auc"] = round(M.roc_auc([sc[i.id][0] for i in items], rel), 4)
    res["n"] = len(items)
    res["relevant"] = sum(rel)
    return res


# ---------------------------------------------------------------- clustering
@dataclass
class _Story:
    members: list[str]
    vecs: list[np.ndarray]
    centroid: np.ndarray
    first: datetime
    last: datetime
    tags: list[str]
    sources: set[str] = field(default_factory=set)
    gone: bool = False


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n else v


def _same_source_blocked(sim: float, a: set[str], b: set[str], cfg: ClusterCfg) -> bool:
    t = cfg.same_source_join_threshold
    return t is not None and len(a) == 1 and a == b and sim < t


def simulate_clusters(
    items: list[BenchItem],
    vecs: dict[str, np.ndarray],
    cfg: ClusterCfg,
    entities: bool = True,
    compat: Callable[[list[str], list[str], int], bool] = compatible,
) -> dict[str, int]:
    """In-memory replay of cluster.assign_item (in published order) followed by one merge_pass."""
    stories: list[_Story] = []
    win = timedelta(days=cfg.window_days)
    for it in sorted(items, key=lambda i: (i.published_at, i.id)):
        v = vecs[it.id]
        tags = it.entities if entities else []
        cands = sorted(
            (
                (float(st.centroid @ v), st)
                for st in stories
                if not st.gone and st.last >= it.published_at - win
            ),
            key=lambda x: -x[0],
        )[:8]
        best = None
        for sim, st in cands:
            if sim < cfg.join_threshold:
                break
            if _same_source_blocked(sim, st.sources, {it.source}, cfg):
                continue
            if compat(tags, st.tags, cfg.min_entity_overlap):
                best = st
                break
        if best is None:
            stories.append(
                _Story([it.id], [v], v, it.published_at, it.published_at, sorted(set(tags))[:40], {it.source})
            )
        else:
            best.members.append(it.id)
            best.vecs.append(v)
            best.centroid = _unit(np.mean(best.vecs, axis=0))
            best.first, best.last = min(best.first, it.published_at), max(best.last, it.published_at)
            best.tags = sorted({*best.tags, *tags})[:40]
            best.sources.add(it.source)
    for a_i, a in enumerate(stories):
        for b in stories[a_i + 1 :]:
            if a.gone or b.gone:
                continue
            if b.first - a.last > win or a.first - b.last > win:
                continue
            sim = float(a.centroid @ b.centroid)
            if (
                sim >= cfg.merge_threshold
                and not _same_source_blocked(sim, a.sources, b.sources, cfg)
                and compat(a.tags, b.tags, cfg.min_entity_overlap)
            ):
                a.members += b.members
                a.vecs += b.vecs
                a.centroid = _unit(np.mean(a.vecs, axis=0))
                a.first, a.last = min(a.first, b.first), max(a.last, b.last)
                a.tags = sorted({*a.tags, *b.tags})[:40]
                a.sources |= b.sources
                b.gone = True
    return {m: k for k, st in enumerate(stories) if not st.gone for m in st.members}


def _vecs(bench: Bench, items: list[BenchItem]) -> dict[str, np.ndarray]:
    return {i.id: _unit(np.asarray(bench.vec(i), dtype=np.float64)) for i in items}


def cluster_metrics(
    bench: Bench, cfg: ClusterCfg, entities: bool = True, legacy: bool = False
) -> dict[str, float]:
    pairs = [p for p in bench.pairs if p.same_event is not None]
    ids = {x for p in pairs for x in (p.a, p.b)}
    items = [i for i in bench.items.values() if i.id in ids]
    assign = simulate_clusters(
        items, _vecs(bench, items), cfg, entities, legacy_compatible if legacy else compatible
    )
    pred = [assign[p.a] == assign[p.b] for p in pairs]
    gold = [bool(p.same_event) for p in pairs]
    r = M.prf(pred, gold)
    return {**r.as_dict(), "pairs": len(pairs), "positives": sum(gold)}


def pair_curve(bench: Bench, entities: bool = True) -> list[dict[str, float]]:
    """Pairwise classifier: same event iff cosine â‰¥ t (and entity-compatible): the raw separability."""
    pairs = [p for p in bench.pairs if p.same_event is not None]
    vec = _vecs(bench, [bench.items[x] for p in pairs for x in (p.a, p.b)])
    gold = [bool(p.same_event) for p in pairs]
    out = []
    for t in np.arange(0.70, 0.951, 0.01):
        pred = [
            float(vec[p.a] @ vec[p.b]) >= t
            and (not entities or compatible(bench.items[p.a].entities, bench.items[p.b].entities, 1))
            for p in pairs
        ]
        out.append({"t": round(float(t), 2), **M.prf(pred, gold).as_dict()})
    return out


def cluster_sweep(bench: Bench, base: ClusterCfg) -> list[dict[str, float]]:
    rows = []
    for j in np.arange(0.70, 0.951, 0.01):
        for dm in (0.0, 0.02, 0.04, 0.06, 0.08):
            m = min(0.98, j + dm)
            cfg = base.model_copy(
                update={"join_threshold": round(float(j), 2), "merge_threshold": round(m, 2)}
            )
            r = cluster_metrics(bench, cfg)
            rows.append({"join": cfg.join_threshold, "merge": cfg.merge_threshold, **r})
    return rows


# ---------------------------------------------------------------- ranking
def _member(it: BenchItem, prefilter_score: float) -> dict[str, Any]:
    e = it.enrich or {}
    return {
        "role": "primary" if it.tier == 1 or e.get("is_primary_source") else "report",
        "title": it.title,
        "signal_meta": it.signal_meta,
        "prefilter_score": prefilter_score,
        "is_capture": False,
        "published_at": it.published_at,
        "name": it.source,
        "tier": it.tier,
        "type": it.source_type,
        "tech_relevance": e.get("tech_relevance", 0.0),
        "summary_1line": e.get("summary_1line"),
        "topics": [],
    }


def story_for(
    bench: Bench, it: BenchItem, prefilter_score: float, cfg: ClusterCfg, judge: dict[str, Any] | None = None
) -> tuple[Story, list[dict[str, Any]], datetime]:
    """A labelled item as the story it would anchor: its corpus neighbours (cosine â‰¥ join, published by `now`)
    stand in for the other members (sources, tiers, engagement, timing)."""
    now = it.published_at + timedelta(hours=12)
    ms = [_member(it, prefilter_score)]
    for nb in it.neighbours:
        at = datetime.fromisoformat(nb["published_at"])
        if nb["sim"] >= cfg.join_threshold and at <= now:
            ms.append(
                {
                    "role": "report",
                    "title": "",
                    "signal_meta": nb.get("signal_meta") or {},
                    "prefilter_score": 0.0,
                    "is_capture": False,
                    "published_at": at,
                    "name": nb["source"],
                    "tier": nb["tier"],
                    "type": nb["type"],
                    "tech_relevance": 0.0,
                    "summary_1line": None,
                    "topics": [],
                }
            )
    s = Story(
        title=it.title,
        centroid=bench.vec(it),
        ring=(it.enrich or {}).get("ring") or "core",
        followed=False,
        scores={"judge": judge} if judge else {},
        durability=(judge or {}).get("durability"),
        entity_names=it.entities,
    )
    return s, ms, now


async def final_scores(
    bench: Bench, items: list[BenchItem], v: Variant, emb: EmbeddingProvider, with_judge: bool = False
) -> dict[str, float]:
    pv_emb: EmbeddingProvider = MockEmbeddingProvider() if v.profile_embedder == "mock" else emb
    pvs_pf = await profile_vecs(pv_emb, bench)
    pf = prefilter_scores(bench, items, pvs_pf, v)
    # mirrors score_stories: centroids (with their own scale) when configured, else the text vectors
    pvs_sc = [p for p in pvs_pf if p.kind != CENTROID]
    lo, hi = v.scoring.relevance_scale("fastembed")
    cscale = v.scoring.relevance_centroid_scale.get("fastembed")
    cents = [p for p in pvs_pf if p.kind == CENTROID]
    if cscale is not None and cents and v.profile_embedder != "mock":
        pvs_sc, (lo, hi) = cents, cscale
    tp = get_config().profile.topics
    ctx = ScoreContext(
        weights=v.scoring.weights_for("fastembed").model_dump(),
        pvs=[(p.label, "topic", p.weight, p.vec) for p in pvs_sc],
        lo=lo,
        hi=hi,
        blocked_kw=[k.lower() for k in tp.blocked_keywords],
        blocked_ent=[e.lower() for e in tp.blocked_entities],
        adjacent_tech_min=v.scoring.adjacent_tech_relevance_min,
        momentum_window_hours=v.scoring.momentum_window_hours,
    )
    out = {}
    for it in items:
        j = bench.judge.get(it.id) if with_judge else None
        s, ms, now = story_for(bench, it, pf[it.id][0], v.cluster, j)
        apply_scores(s, ms, ctx, 0.5, now)
        out[it.id] = float(s.final_score)
    return out


def pools(
    items: list[BenchItem], n: int = POOLS, size: int = POOL_SIZE, seed: int = POOL_SEED
) -> list[list[BenchItem]]:
    rng = random.Random(seed)
    srt = sorted(items, key=lambda i: i.id)
    return [rng.sample(srt, min(size, len(srt))) for _ in range(n)]


def ranking_metrics(items_pools: list[list[BenchItem]], scores: dict[str, float]) -> dict[str, float]:
    nd, p7 = [], []
    for pool in items_pools:
        sc = [scores[i.id] for i in pool]
        gains = [float(i.label.relevance if i.label else 0) for i in pool]
        nd.append(M.ndcg_at_k(sc, gains, 10))
        p7.append(M.precision_at_k(sc, [g >= RELEVANT for g in gains], 7))
    return {
        "ndcg@10": round(float(np.mean(nd)), 4),
        "p@7": round(float(np.mean(p7)), 4),
        "pools": len(items_pools),
    }


async def eval_ranking(bench: Bench, v: Variant, emb: EmbeddingProvider) -> dict[str, Any]:
    test = [i for i in bench.labelled if i.split == "test"]
    scores = await final_scores(bench, test, v, emb)
    out: dict[str, Any] = {"test": ranking_metrics(pools(test), scores)}
    judged = [i for i in test if i.id in bench.judge]
    if judged:
        no_j = await final_scores(bench, judged, v, emb)
        with_j = await final_scores(bench, judged, v, emb, with_judge=True)
        out["judge_subset"] = {
            "n": len(judged),
            "without_judge": ranking_metrics([judged], no_j),
            "with_judge": ranking_metrics([judged], with_j),
        }
    return out


# ---------------------------------------------------------------- Ask retrieval
async def load_ask_corpus(session: AsyncSession, bench: Bench) -> None:
    from signal_core.db.base import OWNER_ID
    from signal_core.db.models import Item, Source, User

    if await session.get(User, OWNER_ID) is None:  # rows need their owner; rolled back with everything else
        session.add(User(id=OWNER_ID, email="bench@localhost", password_hash="-"))
        await session.flush()
    srcs: dict[str, Source] = {}
    for it in sorted(bench.items.values(), key=lambda i: i.id):
        if it.source not in srcs:
            srcs[it.source] = Source(type=it.source_type, name=it.source, tier=it.tier, ring=it.source_ring)
            session.add(srcs[it.source])
    await session.flush()
    for it in sorted(bench.items.values(), key=lambda i: i.id):
        session.add(
            Item(
                id=uuid.UUID(it.id),
                source_id=srcs[it.source].id,
                external_id=it.id,
                canonical_url=f"https://bench.invalid/{it.id}",
                url_hash=hashlib.sha256(it.id.encode()).hexdigest(),
                title=it.title,
                text=it.text,
                published_at=it.published_at,
                content_type=it.content_type,
                status="new",
                prefilter_score=1.0,
                embedding=bench.vec(it),
            )
        )
    await session.flush()


async def eval_ask(
    session: AsyncSession, bench: Bench, v: Variant, emb: EmbeddingProvider, rerank: bool | None = None
) -> dict[str, Any]:
    """Recall@5 / MRR of ask.retrieve over the fixture corpus (all items searchable). Caller rolls back."""
    from signal_core.ask.service import retrieve, time_window
    from signal_core.embeddings import get_embedder, set_embedder

    prev = get_embedder()
    set_embedder(emb)
    try:
        await load_ask_corpus(session, bench)
        now = max(i.published_at for i in bench.items.values()) + timedelta(days=1)
        r5, r1, rr, per_q = [], [], [], []
        cfg = v.ask if rerank is None else v.ask.model_copy(update={"rerank": rerank})
        for q in bench.questions:
            since, clean = time_window(q.question, now)
            chunks = await retrieve(session, clean, now, since=since, cfg=cfg)
            ids = [c.id for c in chunks]
            r5.append(M.recall_at_k(ids, q.item_id, 5))
            r1.append(M.recall_at_k(ids, q.item_id, 1))
            rr.append(M.reciprocal_rank(ids, q.item_id))
            per_q.append({"id": q.id, "rank": ids.index(q.item_id) + 1 if q.item_id in ids else None})
        return {
            "recall@5": round(float(np.mean(r5)), 4) if r5 else 0.0,
            "recall@1": round(float(np.mean(r1)), 4) if r1 else 0.0,
            "mrr": round(float(np.mean(rr)), 4) if rr else 0.0,
            "questions": len(r5),
            "per_question": per_q,
        }
    finally:
        set_embedder(prev)


async def ask_session() -> Any:
    """A dedicated, migrated scratch database for the Ask part (signal_bench_run); the caller rolls back."""
    import asyncio

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from signal_core.settings import REPO_ROOT, get_settings

    url = make_url(get_settings().database_url).set(database="signal_bench_run")
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        if not (
            await c.execute(text("select 1 from pg_database where datname = 'signal_bench_run'"))
        ).scalar():
            await c.execute(text('create database "signal_bench_run"'))
    await admin.dispose()
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "packages/core/signal_core/db/migrations"))
    cfg.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    await asyncio.to_thread(command.upgrade, cfg, "head")
    engine = create_async_engine(url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------- all
def fastembed_available() -> bool:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return False
    return True


async def evaluate(
    bench: Bench,
    v: Variant,
    emb: EmbeddingProvider,
    session: AsyncSession | None = None,
    rerank: bool | None = None,
) -> dict[str, Any]:
    res: dict[str, Any] = {
        "variant": v.name,
        "prefilter": await eval_prefilter(bench, v, emb),
        "cluster": cluster_metrics(bench, v.cluster, legacy=v.legacy_entity_rule),
        "cluster_thresholds": {"join": v.cluster.join_threshold, "merge": v.cluster.merge_threshold},
        "ranking": await eval_ranking(bench, v, emb),
    }
    if session is not None and bench.questions:
        res["ask"] = await eval_ask(session, bench, v, emb, rerank)
        await session.rollback()
    return res


async def run_all(
    sweep: bool = False, update_cache: bool = False, ask: bool = True, baseline: bool = False
) -> dict[str, Any]:
    from signal_core.embeddings import FastEmbedProvider

    bench = load()
    emb = FixtureEmbedder(bench.cache, FastEmbedProvider() if update_cache else None)
    v = baseline_variant() if baseline else current_variant()
    rerank = None if fastembed_available() else False
    engine = maker = None
    if ask:
        engine, maker = await ask_session()
    try:
        session = maker() if maker else None
        res = await evaluate(bench, v, emb, session, rerank)
        if session is not None:
            await session.close()
        res["labels"] = label_summary(bench)
        if sweep:
            res["sweep"] = {
                "pair_curve": pair_curve(bench),
                "cluster": cluster_sweep(bench, v.scoring.cluster),
            }
    finally:
        if engine is not None:
            await engine.dispose()
        bench.cache.save()
    return res


def label_summary(bench: Bench) -> dict[str, Any]:
    rel: dict[int, int] = defaultdict(int)
    for i in bench.labelled:
        assert i.label is not None
        rel[i.label.relevance] += 1
    pairs = [p for p in bench.pairs if p.same_event is not None]
    return {
        "items": len(bench.labelled),
        "relevance": dict(sorted(rel.items())),
        "pairs": len(pairs),
        "same_event": sum(1 for p in pairs if p.same_event),
        "questions": len(bench.questions),
        "judged": len(bench.judge),
    }


def print_report(res: dict[str, Any]) -> None:
    pf, cl, rk = res["prefilter"], res["cluster"], res["ranking"]
    print(f"variant: {res['variant']}   labels: {res.get('labels')}")
    print(
        f"prefilter  recall {pf['recall']:.3f}  precision {pf['precision']:.3f}  AUC {pf['auc']:.3f}  "
        f"pass(sample) {pf['pass_rate_sample']:.3f}  | population est: recall {pf['recall_pop']:.3f}  "
        f"precision {pf['precision_pop']:.3f}  pass {pf['pass_rate_pop']:.3f}"
    )
    print(
        f"cluster    join {res['cluster_thresholds']['join']} merge {res['cluster_thresholds']['merge']}  "
        f"P {cl['precision']:.3f}  R {cl['recall']:.3f}  F1 {cl['f1']:.3f}  ({cl['positives']}/{cl['pairs']} same)"
    )
    t = rk["test"]
    print(
        f"ranking    NDCG@10 {t['ndcg@10']:.3f}  P@7 {t['p@7']:.3f}  ({t['pools']} pools of {POOL_SIZE}, test split)"
    )
    if "judge_subset" in rk:
        j = rk["judge_subset"]
        print(
            f"           judge subset n={j['n']}: without NDCG@10 {j['without_judge']['ndcg@10']:.3f} "
            f"P@7 {j['without_judge']['p@7']:.3f} | with NDCG@10 {j['with_judge']['ndcg@10']:.3f} "
            f"P@7 {j['with_judge']['p@7']:.3f}"
        )
    if "ask" in res:
        a = res["ask"]
        print(
            f"ask        recall@5 {a['recall@5']:.3f}  recall@1 {a['recall@1']:.3f}  MRR {a['mrr']:.3f}  (n={a['questions']})"
        )
    if "sweep" in res:
        best = max(res["sweep"]["cluster"], key=lambda r: (r["f1"], r["precision"]))
        print(f"cluster sweep best: {best}")


# ---------------------------------------------------------------- pytest regression subset
REGRESSION_FILE = "regression.json"
FLOOR_KEYS = {
    "prefilter_recall": ("prefilter", "recall"),
    "prefilter_auc": ("prefilter", "auc"),
    "cluster_f1": ("cluster", "f1"),
    "ranking_ndcg10": ("ranking", "test", "ndcg@10"),
    "ranking_p7": ("ranking", "test", "p@7"),
    "ask_recall5": ("ask", "recall@5"),
    "ask_mrr": ("ask", "mrr"),
}


def pick(res: dict[str, Any], path: tuple[str, ...]) -> float:
    x: Any = res
    for k in path:
        x = x[k]
    return float(x)


def _h(s: str, mod: int) -> int:
    return int(hashlib.sha1(s.encode()).hexdigest(), 16) % mod


def regression_ids(bench: Bench) -> tuple[set[str], set[str], set[str]]:
    """Deterministic small subset: ~1/3 of the labelled items, ~1/2 of the pairs, every question."""
    pairs = {p.id for p in bench.pairs if p.same_event is not None and _h(p.id, 2) == 0}
    qs = {q.id for q in bench.questions}
    items = {i.id for i in bench.labelled if _h(i.id, 3) == 0}
    items |= {x for p in bench.pairs if p.id in pairs for x in (p.a, p.b)}
    items |= {q.item_id for q in bench.questions}
    return items, pairs, qs


async def write_regression(session: AsyncSession) -> dict[str, Any]:
    """Measure current and baseline engines on the subset (no cross-encoder) and commit the floors."""
    import json

    from signal_core.ops.bench.data import FIXTURE_DIR

    full = load()
    ids = regression_ids(full)
    sub = full.restrict(*ids)
    emb = FixtureEmbedder(full.cache)
    cur = await evaluate(sub, current_variant(), emb, session, rerank=False)
    base = await evaluate(sub, baseline_variant(), emb, session, rerank=False)
    out = {
        "note": "ADR-026 pytest regression subset; floors = current engines on this subset (no cross-encoder)",
        "items": sorted(ids[0]),
        "pairs": sorted(ids[1]),
        "questions": sorted(ids[2]),
        "floors": {k: math.floor(pick(cur, p) * 1000) / 1000 for k, p in FLOOR_KEYS.items()},
        "baseline": {k: round(pick(base, p), 4) for k, p in FLOOR_KEYS.items()},
    }
    (FIXTURE_DIR / REGRESSION_FILE).write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    return {"floors": out["floors"], "baseline": out["baseline"], "items": len(out["items"])}


async def run_regression_writer() -> dict[str, Any]:
    engine, maker = await ask_session()
    try:
        async with maker() as s:
            return dict(await write_regression(s))
    finally:
        await engine.dispose()
