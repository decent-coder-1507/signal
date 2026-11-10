"""Real-data benchmark regression (ADR-026).

Runs the product engines (prefilter, clustering, scoring, Ask retrieval) on a committed subset of the labelled
benchmark, in mock mode, with the committed fastembed embeddings (no model, no network, no LLM) and asserts the metrics
stay at or above the floors in fixtures/bench/regression.json. Refresh the floors deliberately with
`python -m signal_core.ops.bench subset` when an engine change is measured to be better on the full benchmark.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from signal_core.ops.bench import engines
from signal_core.ops.bench.data import FIXTURE_DIR, Bench, FixtureEmbedder, load

REG: dict[str, Any] = json.loads((FIXTURE_DIR / engines.REGRESSION_FILE).read_text(encoding="utf-8"))


def subset() -> Bench:
    return load().restrict(set(REG["items"]), set(REG["pairs"]), set(REG["questions"]))


@pytest.fixture(scope="module")
def bench() -> Bench:
    return subset()


async def test_offline_engines_stay_at_or_above_floor(bench: Bench) -> None:
    res = await engines.evaluate(bench, engines.current_variant(), FixtureEmbedder(bench.cache))
    for key, path in engines.FLOOR_KEYS.items():
        if path[0] == "ask":
            continue
        got = engines.pick(res, path)
        assert got >= REG["floors"][key] - 1e-9, f"{key} regressed: {got:.4f} < floor {REG['floors'][key]}"


async def test_ask_retrieval_stays_at_or_above_floor(db: AsyncSession, bench: Bench) -> None:
    res = await engines.eval_ask(
        db, bench, engines.current_variant(), FixtureEmbedder(bench.cache), rerank=False
    )
    assert res["recall@5"] >= REG["floors"]["ask_recall5"] - 1e-9
    assert res["mrr"] >= REG["floors"]["ask_mrr"] - 1e-9


async def test_current_engines_beat_the_pre_adr026_baseline(bench: Bench) -> None:
    emb = FixtureEmbedder(bench.cache)
    cur = await engines.evaluate(bench, engines.current_variant(), emb)
    base = await engines.evaluate(bench, engines.baseline_variant(), emb)
    assert cur["prefilter"]["recall"] > base["prefilter"]["recall"]
    assert cur["cluster"]["f1"] >= base["cluster"]["f1"]


def test_metric_functions() -> None:
    from signal_core.ops.bench import metrics as M

    assert M.ndcg_at_k([3, 2, 1], [3, 2, 0], 3) == pytest.approx(1.0)
    assert M.ndcg_at_k([1, 2, 3], [3, 2, 0], 3) < 1.0
    assert M.precision_at_k([0.9, 0.8, 0.1], [True, False, True], 2) == 0.5
    p = M.prf([True, True, False, False], [True, False, True, False])
    assert (p.precision, p.recall) == (0.5, 0.5)
    assert M.roc_auc([0.9, 0.1], [True, False]) == 1.0
    assert M.reciprocal_rank(["a", "b"], "b") == 0.5
