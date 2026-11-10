"""Unit tests for the ADR-026 engine changes (pure functions; the benchmark regression is tests/integration/test_bench.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from signal_core.ask.service import fts_query
from signal_core.config import get_config
from signal_core.config.schemas import PrefilterHybridCfg
from signal_core.radar.cluster import compatible, norm_tag
from signal_core.radar.prefilter import CENTROID, ProfileVec, keyword_centroids, prefilter
from signal_core.radar.scoring import momentum


def _unit(i: int, n: int = 4) -> list[float]:
    return [1.0 if k == i else 0.0 for k in range(n)]


def test_hybrid_prefilter_combines_centroid_cosine_and_keywords() -> None:
    cfg = get_config().scoring.model_copy(
        update={
            "prefilter_hybrid": PrefilterHybridCfg(
                embedding_weight=0.6, cosine_scale={"fastembed": (0.6, 0.8)}
            )
        }
    )
    pvs = [
        ProfileVec("rag", "core", 1.0, _unit(1), ["retrieval", "RAG"]),
        ProfileVec("rag", "core", 1.0, _unit(0), ["retrieval", "RAG"], CENTROID),
    ]
    on_topic = prefilter(_unit(0), "RAG retrieval tricks", "", pvs, [], [], cfg, "fastembed")
    # 0.6·scale(1.0) + 0.4·min(1, 2·0.45 title keyword score)
    assert on_topic.score == 0.96 and on_topic.best_label == "rag"
    emb_only = prefilter(_unit(0), "Something else", "", pvs, [], [], cfg, "fastembed")
    assert emb_only.score == 0.6
    neither = prefilter(_unit(2), "Something else", "", pvs, [], [], cfg, "fastembed")
    assert neither.score == 0.0
    # embedders without a hybrid scale keep the legacy max(cosine, keyword) score and ignore centroids
    legacy = prefilter(_unit(0), "Something else", "", pvs, [], [], cfg, "mock")
    assert legacy.score == 0.0
    blocked = prefilter(_unit(0), "celebrity RAG", "", pvs, ["celebrity"], [], cfg, "fastembed")
    assert blocked.blocked


def test_keyword_centroids_need_enough_matching_items() -> None:
    rows = [("RAG and retrieval", "", _unit(0))] * 3 + [("cooking", "", _unit(1))] * 5
    topics = [("rag", "core", 1.0, ["RAG", "retrieval"]), ("chips", "adjacent", 0.5, ["GPU"])]
    assert keyword_centroids(rows, topics, min_items=3) == {"rag": [1.0, 0.0, 0.0, 0.0]}
    assert keyword_centroids(rows, topics, min_items=4) == {}


def test_entity_tags_normalise_spelling_variants() -> None:
    assert norm_tag("model:GPT‑6 Cyber") == "model:gpt 6 cyber"
    assert norm_tag("model:openai/gpt-live-1") == "model:gpt live 1"
    assert norm_tag("company:eMudhra Limited") == "company:emudhra"
    assert norm_tag("repo:fastapi/fastapi") == "repo:fastapi/fastapi"
    assert compatible(["model:gpt‑live‑1"], ["model:openai/gpt-live-1"], 1)
    assert compatible(["model:gemini 3.8 live"], ["model:google/gemini-3.8-live-extended"], 1)
    # different specific entities stay apart unless two other entities are shared
    assert not compatible(["company:nimbus", "model:nimbus-4"], ["company:nimbus", "model:nimbus-3"], 1)
    assert compatible(
        ["company:shiprocket", "company:zepto", "product:aitlas"],
        ["company:shiprocket", "company:zepto", "product:other"],
        1,
    )
    assert not compatible(["model:python"], ["model:python 3.15"], 1)


def test_momentum_counts_new_sources() -> None:
    now = datetime(2026, 11, 9, 12, tzinfo=UTC)

    def m(src: str, hours_ago: float) -> dict[str, object]:
        return {"name": src, "published_at": now - timedelta(hours=hours_ago)}

    assert momentum([m("a", 1)], now) == 0.75
    assert momentum([m("a", 1), m("b", 2), m("c", 3)], now) == 1.0
    assert momentum([m("a", 30)], now) == 0.25
    assert momentum([m("a", 1), m("b", 30)], now) == 0.5


def test_fts_query_modes() -> None:
    assert fts_query("what is RAG, really?", "all") == "what is RAG really"
    assert fts_query("what is RAG or not", "any") == "what or is or RAG or not"
