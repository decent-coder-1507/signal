"""Benchmark fixture format (fixtures/bench/) and the committed embedding cache.

Labels are model judgements (Claude, see meta.json), never facts: they are used only to measure engines, never shown
as product output. Embeddings are the real fastembed (bge-small) vectors, stored as base64 float16 keyed by a hash of
the embedded text, so the benchmark and its pytest regression run offline and deterministically.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from signal_core.llm.provider import EmbeddingProvider
from signal_core.settings import REPO_ROOT

FIXTURE_DIR = REPO_ROOT / "fixtures" / "bench"
EMBED_CLIP = 1200  # FastEmbedProvider clips texts to 1,200 characters (ADR-015)


@dataclass
class Label:
    relevance: int  # 0 irrelevant · 1 tangential · 2 relevant · 3 must-read
    ring: str  # core | adjacent | wide | none
    reason: str


@dataclass
class BenchItem:
    id: str
    source: str
    source_type: str
    tier: int
    source_ring: str
    title: str
    text: str
    published_at: datetime
    content_type: str
    stratum: str  # rejected | passed (keyword prefilter outcome at build time) | pair (pair-only item)
    split: str  # train | test (by id hash; used to fit and to report)
    signal_meta: dict[str, Any] = field(default_factory=dict)
    entities: list[str] = field(
        default_factory=list
    )  # entity tags from the real enrichment (cluster.entity_tags)
    enrich: dict[str, Any] | None = None  # ring, tech_relevance, summary_1line from the real enrichment
    label: Label | None = None
    neighbours: list[dict[str, Any]] = field(default_factory=list)  # corpus items near this one (story proxy)

    @property
    def embed_text(self) -> str:
        """Exactly what ingest embeds: f"{title}\\n{text[:2000]}", clipped to 1,200 characters by fastembed."""
        return f"{self.title}\n{self.text}"[:EMBED_CLIP]

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["published_at"] = self.published_at.isoformat()
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> BenchItem:
        d = dict(d)
        d["published_at"] = datetime.fromisoformat(d["published_at"])
        d["label"] = Label(**d["label"]) if d.get("label") else None
        return cls(**d)


@dataclass
class Pair:
    id: str
    a: str
    b: str
    cosine: float
    kind: str  # knn (high similarity) | random (same week)
    same_event: bool | None = None
    reason: str = ""


@dataclass
class Question:
    id: str
    question: str
    item_id: str


@dataclass
class Bench:
    items: dict[str, BenchItem]
    pairs: list[Pair]
    questions: list[Question]
    judge: dict[str, dict[str, Any]]
    meta: dict[str, Any]
    cache: EmbeddingCache

    @property
    def labelled(self) -> list[BenchItem]:
        return [i for i in self.items.values() if i.label is not None]

    def vec(self, item: BenchItem) -> list[float]:
        v = self.cache.get(item.embed_text)
        if v is None:
            raise KeyError(f"no cached embedding for item {item.id}")
        return v

    def restrict(self, item_ids: set[str], pair_ids: set[str], question_ids: set[str]) -> Bench:
        """A smaller benchmark over the given ids (the pytest regression subset)."""
        keep = {i: it for i, it in self.items.items() if i in item_ids}
        return Bench(
            items=keep,
            pairs=[p for p in self.pairs if p.id in pair_ids and p.a in keep and p.b in keep],
            questions=[q for q in self.questions if q.id in question_ids and q.item_id in keep],
            judge={k: v for k, v in self.judge.items() if k in keep},
            meta=self.meta,
            cache=self.cache,
        )


def text_key(text: str) -> str:
    return hashlib.sha1(text[:EMBED_CLIP].encode("utf-8")).hexdigest()[:16]


class EmbeddingCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, str] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.dirty = False

    def get(self, text: str) -> list[float] | None:
        b = self.data.get(text_key(text))
        if b is None:
            return None
        v = np.frombuffer(base64.b64decode(b), dtype=np.float16).astype(np.float64)
        return [float(x) for x in v]

    def put(self, text: str, vec: list[float]) -> None:
        self.data[text_key(text)] = base64.b64encode(np.asarray(vec, dtype=np.float16).tobytes()).decode()
        self.dirty = True

    def save(self) -> None:
        if self.dirty:
            self.path.write_text(json.dumps(self.data, sort_keys=True, indent=0) + "\n", encoding="utf-8")
            self.dirty = False


class FixtureEmbedder:
    """Serves cached embeddings; misses go to `fallback` (fastembed) and are added to the cache, or raise."""

    def __init__(
        self, cache: EmbeddingCache, fallback: EmbeddingProvider | None = None, name: str = "fastembed"
    ) -> None:
        self.cache = cache
        self.fallback = fallback
        self.name = name
        self.dim = 384

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float] | None] = [self.cache.get(t) for t in texts]
        miss = [i for i, v in enumerate(out) if v is None]
        if miss:
            if self.fallback is None:
                raise KeyError(
                    f"{len(miss)} texts are not in the embedding cache "
                    f"(run `python -m signal_core.ops.bench run --update-cache` with fastembed installed); "
                    f"first: {texts[miss[0]][:80]!r}"
                )
            vecs = await self.fallback.embed([texts[i] for i in miss])
            for i, v in zip(miss, vecs, strict=True):
                self.cache.put(texts[i], v)
                out[i] = self.cache.get(texts[i])  # round-trip through float16 so hits and misses agree
        return [v for v in out if v is not None]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8"
    )


def load(root: Path = FIXTURE_DIR) -> Bench:
    items = {d["id"]: BenchItem.from_json(d) for d in _read_jsonl(root / "items.jsonl")}
    pairs = [Pair(**d) for d in _read_jsonl(root / "pairs.jsonl")]
    questions = [Question(**d) for d in _read_jsonl(root / "questions.jsonl")]
    judge = {d["item_id"]: d["judge"] for d in _read_jsonl(root / "judge.jsonl")}
    meta_path = root / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return Bench(items, pairs, questions, judge, meta, EmbeddingCache(root / "embeddings.json"))


def save_items(bench: Bench, root: Path = FIXTURE_DIR) -> None:
    rows = sorted((i.to_json() for i in bench.items.values()), key=lambda d: d["id"])
    write_jsonl(root / "items.jsonl", rows)


def save_pairs(pairs: list[Pair], root: Path = FIXTURE_DIR) -> None:
    write_jsonl(root / "pairs.jsonl", [asdict(p) for p in pairs])


def save_questions(qs: list[Question], root: Path = FIXTURE_DIR) -> None:
    write_jsonl(root / "questions.jsonl", [asdict(q) for q in qs])


def save_meta(meta: dict[str, Any], root: Path = FIXTURE_DIR) -> None:
    (root / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
