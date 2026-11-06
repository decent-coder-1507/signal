"""M2 acceptance: purity ≥ 0.9, 3-source event → 1 story, insights cited, quote spans validated, feedback works."""

from collections import Counter, defaultdict
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.db.models import Item, ItemEnrichment, Source, Story, StoryInsight, StoryItem
from signal_core.demo import fixture_client, seed_fixture_sources
from signal_core.fixtures_corpus import labels
from signal_core.llm import router as llm
from signal_core.llm.mock import GENERATORS, MockProvider
from signal_core.llm.provider import LLMUnavailable
from signal_core.radar.jobs import ingest_all_due
from signal_core.radar.normalise import canonical_url
from signal_core.radar.pipeline import process
from signal_core.radar.preference import retrain
from signal_core.radar.scoring import score_stories
from signal_core.truth import check_citations

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


async def run_all(db: AsyncSession) -> dict:  # type: ignore[type-arg]
    await seed_fixture_sources(db, include_broken=False)
    await db.commit()
    await ingest_all_due(NOW, fixture_client(NOW))
    out = await process(db, NOW)
    await db.commit()
    return out


async def clusters(db: AsyncSession) -> dict:  # type: ignore[type-arg]
    lab = {canonical_url(u): e for u, e in labels().items()}
    rows = (
        await db.execute(
            select(StoryItem.story_id, Item.canonical_url)
            .join(Item, Item.id == StoryItem.item_id)
            .join(Story, Story.id == StoryItem.story_id)
            .where(Story.status == "active")
        )
    ).all()
    out: dict = defaultdict(list)  # type: ignore[type-arg]
    for sid, url in rows:
        out[sid].append(lab[url])
    return out


async def test_cluster_purity_and_three_source_event(seeded: AsyncSession) -> None:
    await run_all(seeded)
    cl = await clusters(seeded)
    total = sum(len(v) for v in cl.values())
    purity = sum(Counter(v).most_common(1)[0][1] for v in cl.values()) / total
    assert purity >= 0.9, purity
    injection = [v for v in cl.values() if "injection" in v]
    assert len(injection) == 1 and len(injection[0]) == 3  # same event from 3 sources → one story
    nimbus = [v for v in cl.values() if "nimbus4" in v]
    assert len(nimbus) == 1 and len(nimbus[0]) == 4
    assert not any({"nimbus4", "nimbusprice"} <= set(v) for v in cl.values())  # related ≠ same event


async def test_insights_populated_with_valid_citations(seeded: AsyncSession) -> None:
    out = await run_all(seeded)
    assert out["insights"] >= 10
    rows = (
        await seeded.execute(select(StoryInsight, Story).join(Story, Story.id == StoryInsight.story_id))
    ).all()
    for ins, story in rows:
        members = {
            str(i)
            for i in (
                await seeded.execute(select(StoryItem.item_id).where(StoryItem.story_id == story.id))
            ).scalars()
        }
        rep = check_citations(ins.what_happened, members)
        assert rep.ok, (story.title, rep)
        for field in ("what_happened", "why_you", "what_changes", "hype_verdict", "durability", "moat_note"):
            assert getattr(ins, field), (story.title, field)
        assert ins.open_questions and ins.actions and 0 <= ins.confidence <= 1
        assert {a["type"] for a in ins.actions} <= {"post", "build", "learn", "watch", "try", "ignore"}
        assert all(c["id"] in members for c in ins.citations)
        assert ins.prompt_version == "v1" and ins.model


async def test_invalid_quote_spans_are_rejected(
    seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signal_core.llm.mock_generators import enrich_items

    def lying(inputs):  # type: ignore[no-untyped-def]
        out = enrich_items(inputs)
        for it in out["items"]:
            it["key_facts"].append(
                {"fact": "It costs nothing", "quote_span": "The model is completely free forever"}
            )
        return out

    monkeypatch.setitem(GENERATORS, "enrich_items", lying)
    out = await run_all(seeded)
    assert out["rejected_facts"] >= out["enriched"]
    facts = [f for (kf,) in (await seeded.execute(select(ItemEnrichment.key_facts))).all() for f in kf]
    assert facts and all("completely free" not in f["quote_span"] for f in facts)


async def test_scores_explain_why(seeded: AsyncSession) -> None:
    await run_all(seeded)
    s = (
        (await seeded.execute(select(Story).where(Story.final_score > 0).order_by(Story.final_score.desc())))
        .scalars()
        .first()
    )
    assert s is not None
    for k in (
        "relevance",
        "impact",
        "signal",
        "novelty",
        "credibility",
        "durability",
        "actionability",
        "learned",
    ):
        assert 0.0 <= s.scores[k] <= 1.0
    assert s.scores["judge"]["reason"]
    excluded = (await seeded.execute(select(Story).where(Story.final_score == -1.0))).scalars().all()
    assert all(x.scores.get("excluded") for x in excluded)


async def test_feedback_changes_rankings(seeded: AsyncSession) -> None:
    from signal_core.db.models import Feedback

    await run_all(seeded)
    ranked = await score_stories(seeded, NOW, judge=False)
    order_before = [s.id for s in ranked if s.final_score > 0]
    target = ranked[0]  # demote the current #1 via consistent negative feedback on its features
    target_before = target.final_score
    src_names = set(target.scores["sources"])
    neg, pos = [], []
    for s in ranked:
        (neg if src_names & set(s.scores.get("sources", [])) else pos).append(s)
    for s in neg[:4]:
        seeded.add(Feedback(target_type="story", target_id=s.id, kind="not_for_me"))
    for s in pos[:4]:
        seeded.add(Feedback(target_type="story", target_id=s.id, kind="useful"))
    await seeded.flush()
    pm = await retrain(seeded)
    assert pm is not None and pm.metrics["examples"] >= 6
    after = await score_stories(seeded, NOW, judge=False)
    t_after = next(s for s in after if s.id == target.id)
    assert t_after.scores["learned"] < 0.5
    assert [s.id for s in after if s.final_score > 0] != order_before
    assert t_after.final_score < target_before  # learned preference is a gentle 0.05-weight signal (§6.5)


async def test_primary_source_tracing(seeded: AsyncSession) -> None:
    from signal_core.radar.cluster import trace_primary_sources

    await run_all(seeded)
    official = (
        await seeded.execute(
            select(Item).where(Item.canonical_url == "https://nimbus.example/blog/nimbus-3-price-cut")
        )
    ).scalar_one()
    si = (await seeded.execute(select(StoryItem).where(StoryItem.item_id == official.id))).scalar_one()
    await seeded.delete(si)  # detach the official post, then let a re-write that links to it bring it back
    rewrite = (
        await seeded.execute(
            select(Item).where(
                Item.canonical_url == "https://technews-a.example/2026/11/nimbus-halves-prices"
            )
        )
    ).scalar_one()
    rewrite.text += " Source: https://nimbus.example/blog/nimbus-3-price-cut?utm_source=newsletter"
    await seeded.flush()
    assert await trace_primary_sources(seeded) >= 1
    back = (await seeded.execute(select(StoryItem).where(StoryItem.item_id == official.id))).scalar_one()
    assert back.role == "primary" and official.primary_source


async def test_llm_outage_degrades_without_crashing(seeded: AsyncSession) -> None:
    p = MockProvider()
    p.fail_with = LLMUnavailable("Claude CLI not authenticated")
    llm.set_provider(p)
    out = await run_all(seeded)
    assert out["llm_unavailable"] and out["enriched"] == 0
    n_new = len((await seeded.execute(select(Item).where(Item.status == "new"))).scalars().all())
    assert n_new > 0  # items wait for the next run instead of being lost


async def test_sources_tier_drive_primary_roles(seeded: AsyncSession) -> None:
    await run_all(seeded)
    rows = (
        await seeded.execute(
            select(StoryItem.role, Source.tier)
            .join(Item, Item.id == StoryItem.item_id)
            .join(Source, Source.id == Item.source_id)
        )
    ).all()
    assert all(role == "primary" for role, tier in rows if tier == 1)
