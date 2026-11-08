"""Evals (§15.6): golden cases (≥ 30 per core task) + user "wrong/inaccurate" reports; nightly sample run.

Metrics & targets:
- enrichment: JSON validity and quote-span accuracy ≥ 98% (facts whose quote_span is verbatim before validation)
- clustering purity on the labelled set ≥ 0.9 (stories whose items carry fixture labels)
- fact-check recall on seeded false claims ≥ 90% (numbers deliberately altered), precision on true claims
- banned-phrase rate in AI drafts = 0 (after the gate; measured on stored AI versions)
- relevance NDCG@10 of the story ranking vs explicit feedback (reported; no hard target)
Regressions vs the previous run mark the report failed (blocks prompt-version promotion).
"""

from __future__ import annotations

import math
import random
import re
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.config import get_config
from signal_core.db.models import DraftVersion, EvalCase, EvalRun, Feedback, Item, Story, StoryItem
from signal_core.fixtures_corpus import ALL_ITEMS, ITEMS, F
from signal_core.llm import router as llm
from signal_core.llm.provider import BudgetExceeded, LLMError
from signal_core.radar.normalise import canonical_url
from signal_core.truth import is_verbatim

TARGETS = {
    "enrich_json_valid": 0.98,
    "enrich_quote_span_accuracy": 0.98,
    "cluster_purity": 0.9,
    "factcheck_recall": 0.9,
    "banned_phrase_rate": 0.0,
}
MIN_CASES = 30


def _mutate_number(s: str, rng: random.Random) -> str | None:
    nums = re.findall(r"\d+(?:[.,]\d+)?", s)
    if not nums:
        return None
    n = rng.choice(nums)
    try:
        v = float(n.replace(",", ""))
    except ValueError:
        return None
    new = v * rng.choice([2, 3, 0.5]) + (1 if v < 2 else 0)
    rep = f"{new:.1f}" if "." in n else f"{int(new):,}" if "," in n else str(int(new))
    return s.replace(n, rep, 1) if rep != n else None


async def seed_golden(session: AsyncSession) -> dict[str, int]:
    """Idempotent: ≥ 30 golden cases each for enrich_items and factcheck from the fictional fixture corpus."""
    have = dict(
        (
            await session.execute(
                select(EvalCase.task, func.count()).where(EvalCase.origin == "golden").group_by(EvalCase.task)
            )
        ).all()
    )
    rng = random.Random(7)
    added: Counter[str] = Counter()
    if have.get("enrich_items", 0) < MIN_CASES:
        for i, it in enumerate([*ITEMS, *ITEMS][:MIN_CASES]):
            session.add(
                EvalCase(
                    task="enrich_items",
                    origin="golden",
                    label=it.event,
                    input={
                        "item_id": f"golden-{i}",
                        "title": it.title,
                        "text": it.body,
                        "source": it.source,
                        "tier": 2,
                        "ring": "core",
                        "content_type": "article",
                    },
                    expected={"verbatim_spans": True},
                )
            )
            added["enrich_items"] += 1
    if have.get("factcheck", 0) < MIN_CASES:
        facts = [f for fs in F.values() for f in fs]
        n = 0
        for f in facts:
            bad = _mutate_number(f, rng)
            session.add(
                EvalCase(
                    task="factcheck",
                    origin="golden",
                    label="true",
                    input={"claim": f, "source": f},
                    expected={"verdict": "supported"},
                )
            )
            n += 1
            if bad:
                session.add(
                    EvalCase(
                        task="factcheck",
                        origin="golden",
                        label="false",
                        input={"claim": bad, "source": f},
                        expected={"verdict": "unsupported"},
                    )
                )
                n += 1
        added["factcheck"] += n
    await session.flush()
    return dict(added)


async def _enrich_metrics(session: AsyncSession, cases: list[EvalCase]) -> dict[str, float]:
    valid = facts = verbatim = 0
    for k in range(0, len(cases), 15):
        batch = cases[k : k + 15]
        try:
            r = await llm.call(
                "enrich_items",
                {"topics": [], "items": [c.input for c in batch]},
                session=session,
                use_cache=False,
            )
        except (LLMError, BudgetExceeded):
            continue
        by = {o.item_id: o for o in r.output.items}
        for c in batch:
            o = by.get(c.input["item_id"])
            if o is None:
                continue
            valid += 1
            for f in o.key_facts:
                facts += 1
                verbatim += is_verbatim(f.quote_span, c.input["text"])
    return {
        "enrich_json_valid": round(valid / max(len(cases), 1), 4),
        "enrich_quote_span_accuracy": round(verbatim / facts, 4) if facts else 1.0,
    }


async def _factcheck_metrics(session: AsyncSession, cases: list[EvalCase]) -> dict[str, float]:
    tp = fn = fp = tn = 0
    claims = [
        {"sentence": c.input["claim"], "sources": [{"id": "s", "text": c.input["source"]}]} for c in cases
    ]
    for k in range(0, len(claims), 20):
        try:
            r = await llm.call("factcheck", {"claims": claims[k : k + 20]}, session=session, use_cache=False)
        except (LLMError, BudgetExceeded):
            continue
        for c, res in zip(cases[k : k + 20], r.output.results, strict=False):
            flagged = res.verdict != "supported"
            if c.label == "false":
                tp, fn = tp + flagged, fn + (not flagged)
            else:
                fp, tn = fp + flagged, tn + (not flagged)
    return {
        "factcheck_recall": round(tp / (tp + fn), 4) if tp + fn else 1.0,
        "factcheck_precision": round(tp / (tp + fp), 4) if tp + fp else 1.0,
    }


async def _cluster_purity(session: AsyncSession) -> float | None:
    lab = {canonical_url(i.url): i.event for i in ALL_ITEMS}
    rows = (
        await session.execute(
            select(StoryItem.story_id, Item.canonical_url)
            .join(Item, Item.id == StoryItem.item_id)
            .join(Story, Story.id == StoryItem.story_id)
            .where(Story.status == "active")
        )
    ).all()
    groups: dict[uuid.UUID, list[str]] = {}
    for sid, url in rows:
        if url in lab:
            groups.setdefault(sid, []).append(lab[url])
    total = sum(len(v) for v in groups.values())
    if not total:
        return None
    return round(sum(Counter(v).most_common(1)[0][1] for v in groups.values()) / total, 4)


async def _banned_rate(session: AsyncSession) -> float:
    banned = [b.lower() for b in get_config().voice.banned_phrases]
    rows = list(
        (
            await session.execute(
                select(DraftVersion.body)
                .where(DraftVersion.author == "ai")
                .order_by(desc(DraftVersion.created_at))
                .limit(200)
            )
        ).scalars()
    )
    if not rows:
        return 0.0
    bad = sum(1 for b in rows if any(p in (b or "").lower() for p in banned) or "—" in (b or ""))
    return round(bad / len(rows), 4)


async def _ndcg(session: AsyncSession, k: int = 10) -> float | None:
    gains = {
        "useful": 3,
        "more": 3,
        "used": 3,
        "saved": 2,
        "opened": 1,
        "known": 0,
        "less": 0,
        "not_for_me": 0,
    }
    fb = dict(
        (
            await session.execute(
                select(Feedback.target_id, Feedback.kind).where(Feedback.target_type == "story")
            )
        ).all()
    )
    if len(fb) < 3:
        return None
    ranked = list(
        (
            await session.execute(
                select(Story.id).where(Story.id.in_(list(fb))).order_by(desc(Story.final_score))
            )
        ).scalars()
    )
    rel = [gains.get(fb[s], 0) for s in ranked][:k]
    dcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(rel))
    ideal = sorted((gains.get(v, 0) for v in fb.values()), reverse=True)[:k]
    idcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return round(dcg / idcg, 4) if idcg else None


async def run(session: AsyncSession, sample: int | None = None) -> EvalRun:
    await seed_golden(session)
    cases = list((await session.execute(select(EvalCase))).scalars())
    rng = random.Random(datetime.now(UTC).toordinal())
    enrich = [c for c in cases if c.task == "enrich_items"]
    fc = [c for c in cases if c.task == "factcheck"]
    if sample:
        enrich = rng.sample(enrich, min(sample, len(enrich)))
        fc = rng.sample(fc, min(sample, len(fc)))
    metrics: dict[str, Any] = {}
    metrics.update(await _enrich_metrics(session, enrich))
    metrics.update(await _factcheck_metrics(session, fc))
    purity = await _cluster_purity(session)
    if purity is not None:
        metrics["cluster_purity"] = purity
    metrics["banned_phrase_rate"] = await _banned_rate(session)
    nd = await _ndcg(session)
    if nd is not None:
        metrics["relevance_ndcg@10"] = nd
    report: dict[str, Any] = {}
    for name, value in metrics.items():
        target = TARGETS.get(name)
        ok = (
            True if target is None else (value <= target if name == "banned_phrase_rate" else value >= target)
        )
        report[name] = {"value": value, "target": target, "passed": ok}
    prev = (
        (await session.execute(select(EvalRun).order_by(desc(EvalRun.created_at)).limit(1))).scalars().first()
    )
    regressions = []
    if prev:
        for name, r in report.items():
            pv = (prev.report.get("metrics", {}).get(name) or {}).get("value")
            if pv is not None and name != "banned_phrase_rate" and r["value"] < pv - 0.02:
                regressions.append(name)
    passed = all(r["passed"] for r in report.values()) and not regressions
    er = EvalRun(
        report={
            "metrics": report,
            "regressions": regressions,
            "cases": {"enrich": len(enrich), "factcheck": len(fc)},
            "user_reports": sum(1 for c in cases if c.origin == "user_report"),
            "provider": llm.get_provider().name,
        },
        passed=passed,
    )
    session.add(er)
    await session.flush()
    return er
