"""Pydantic schemas for config/*.yaml. Invalid config fails fast with a clear error (M0)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Ring = Literal["core", "adjacent", "wide"]
Tier = Literal["fast", "balanced", "deep"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- profile.yaml ----------
class Owner(Strict):
    name: str
    role: str
    company: str = ""
    timezone: str = "Asia/Kolkata"
    goals: list[str] = Field(min_length=1)
    stack: list[str] = []
    vanco_context: str = ""
    confidential_keywords: list[str] = []

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"unknown time zone {v!r}") from e
        return v


class Topic(Strict):
    name: str
    weight: float = Field(ge=0, le=2)
    keywords: list[str] = []
    regions: list[str] = []


class Topics(Strict):
    core: list[Topic]
    adjacent: list[Topic] = []
    wide: list[Topic] = []
    blocked_entities: list[str] = []
    blocked_keywords: list[str] = []


class BriefCfg(Strict):
    max_stories: int = Field(7, ge=1, le=15)
    quick_hits: int = Field(8, ge=0, le=20)
    min_score: float = Field(0.55, ge=0, le=1)
    catchup_after_days: int = 2
    catchup_max_stories: int = 10


class ProfileCfg(Strict):
    owner: Owner
    topics: Topics
    brief: BriefCfg = BriefCfg()


# ---------- sources.yaml ----------
SourceType = Literal[
    "rss",
    "hn",
    "arxiv",
    "hf",
    "github",
    "github_trending",
    "reddit",
    "youtube",
    "podcast",
    "email_in",
    "producthunt",
    "x",
    "capture",
    "jobs",
]


class SourceCfg(BaseModel):
    model_config = ConfigDict(extra="allow")  # adapter-specific keys (endpoint, repos, categories…)
    type: SourceType
    name: str
    url: str | None = None
    tier: int = Field(2, ge=1, le=3)
    ring: Ring = "core"
    topics: list[str] = []
    fetch_every: str = "60m"
    enabled: bool = True
    terms_note: str = ""

    @field_validator("fetch_every")
    @classmethod
    def _every(cls, v: str) -> str:
        if not v[:-1].isdigit() or v[-1] not in "mhd":
            raise ValueError("fetch_every must look like 30m, 6h or 1d")
        return v

    @model_validator(mode="after")
    def _needs_url(self) -> SourceCfg:
        if self.type in ("rss", "youtube", "podcast") and not self.url:
            raise ValueError(f"source '{self.name}' of type {self.type} needs a url")
        return self

    @property
    def fetch_every_minutes(self) -> int:
        n, unit = int(self.fetch_every[:-1]), self.fetch_every[-1]
        return n * {"m": 1, "h": 60, "d": 1440}[unit]


class SourcesCfg(Strict):
    sources: list[SourceCfg]

    @model_validator(mode="after")
    def _unique(self) -> SourcesCfg:
        names = [s.name for s in self.sources]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate source names: {sorted(dupes)}")
        return self


# ---------- scoring.yaml ----------
class Weights(Strict):
    relevance: float
    impact: float
    signal: float
    novelty: float
    credibility: float
    durability: float
    actionability: float
    learned: float
    momentum: float = 0.0  # source-count growth over the last 24 h vs the 24 h before (ADR-026)

    @model_validator(mode="after")
    def _sum(self) -> Weights:
        total = sum(self.model_dump().values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"scoring weights must sum to 1.0 (got {total:.3f})")
        return self


class DedupeCfg(Strict):
    simhash_max_distance: int = 3
    embedding_cosine: float = 0.95
    window_hours: int = 72


class ClusterCfg(Strict):
    join_threshold: float = 0.82
    merge_threshold: float = 0.88
    window_days: int = 7
    min_entity_overlap: int = 1
    # A story whose items all come from one feed only takes another item of that feed above this cosine: one feed
    # rarely reports one event twice, but its series (releases, changelogs, papers) look alike (ADR-026).
    same_source_join_threshold: float | None = None


class PrefilterHybridCfg(Strict):
    """Hybrid prefilter (ADR-026): score = w·scale(cos to keyword-seeded topic centroids) + (1−w)·min(1, 2·keyword).

    Embedders without a `cosine_scale` entry (e.g. mock) keep the legacy max(cosine, keyword) score."""

    embedding_weight: float = Field(0.6, ge=0, le=1)
    cosine_scale: dict[str, tuple[float, float]] = {"fastembed": (0.6, 0.8)}
    centroid_min_items: int = 20  # a topic needs this many keyword-matched items before it gets a centroid
    centroid_days: int = 180


class AskCfg(Strict):
    """Ask retrieval (§11.1): RRF over FTS + vector lists, then an optional local cross-encoder re-rank (ADR-026)."""

    rerank: bool = True
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_candidates: int = Field(20, ge=1, le=100)
    vector_floor: dict[str, float] = {"fastembed": 0.55, "mock": 0.12}
    fts_mode: Literal["all", "any"] = "all"
    query_prefix: str = ""  # e.g. the BGE retrieval instruction; must match how items were embedded (none)


class ScoringCfg(Strict):
    weights: Weights
    prefilter_min: float = Field(0.25, ge=0, le=1)
    prefilter_min_by_embedder: dict[
        str, float
    ] = {}  # hybrid scores live on another scale than the legacy ones
    prefilter_hybrid: PrefilterHybridCfg | None = None
    ask: AskCfg = AskCfg()
    momentum_window_hours: int = 24
    dedupe: DedupeCfg = DedupeCfg()
    cluster: ClusterCfg = ClusterCfg()
    cluster_overrides: dict[str, dict[str, float]] = {}
    relevance_cosine_scale: dict[str, tuple[float, float]] = {"fastembed": (0.45, 0.8), "mock": (0.0, 0.45)}
    # When set for the embedder and topic centroids exist, relevance uses the centroids with this scale (ADR-026).
    relevance_centroid_scale: dict[str, tuple[float, float]] = {}
    adjacent_tech_relevance_min: float = 0.6
    mmr_lambda: float = Field(0.7, ge=0, le=1)
    novelty_window_days: int = 14
    insight_top_n: int = 25
    llm_relevance_top_n: int = 60
    exploration_slot: bool = True
    feedback_max_weight_shift_per_month: float = 0.2
    lab_spark_threshold: float = 6.5

    def cluster_for(self, embedder: str) -> ClusterCfg:
        return self.cluster.model_copy(update=self.cluster_overrides.get(embedder, {}))

    def prefilter_min_for(self, embedder: str) -> float:
        return self.prefilter_min_by_embedder.get(embedder, self.prefilter_min)

    def relevance_scale(self, embedder: str) -> tuple[float, float]:
        return tuple(self.relevance_cosine_scale.get(embedder, (0.0, 1.0)))  # type: ignore[return-value]


# ---------- routines.yaml ----------
class RoutineCfg(Strict):
    name: str
    cron: str
    steps: list[str] = Field(min_length=1)
    channels: list[Literal["app", "telegram", "email", "push"]] = []
    params: dict[str, Any] = {}
    enabled: bool = True

    @field_validator("cron")
    @classmethod
    def _cron(cls, v: str) -> str:
        from croniter import croniter

        if not croniter.is_valid(v):
            raise ValueError(f"invalid cron expression: {v!r}")
        return v


class NotificationsCfg(Strict):
    max_per_day: int = 4
    quiet_hours: tuple[str, str] = ("22:30", "07:00")


class HabitCfg(Strict):
    streak_freezes_per_month: int = 2


class RoutinesCfg(Strict):
    routines: list[RoutineCfg]
    notifications: NotificationsCfg = NotificationsCfg()
    habit: HabitCfg = HabitCfg()


# ---------- voice.yaml ----------
class VoiceCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    base: str
    rules: dict[str, Any]
    hook_types: list[str] = []
    banned_phrases: list[str]
    banned_patterns: list[str] = []
    banned_chars: list[str] = []
    target_score: float = Field(8, ge=0, le=10)
    max_revise_loops: int = 2
    platforms: dict[str, dict[str, Any]]
    goals_per_week: dict[str, int] = {}


# ---------- platforms.yaml ----------
class PlatformsCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    linkedin: dict[str, Any]
    x: dict[str, Any]
    instagram: dict[str, Any]
    hashnode: dict[str, Any]
    ai_disclosure: dict[str, bool] = {}


# ---------- budget.yaml ----------
class Price(Strict):
    input: float
    output: float
    cache_read: float = 0.0
    cache_write: float = 0.0


class BudgetCfg(Strict):
    monthly_usd: float = Field(gt=0)
    soft_limit_pct: float = Field(80, gt=0, lt=100)
    provider: Literal["claude_runner", "mock"] = "claude_runner"
    models: dict[Tier, str]
    model_ids: dict[str, str] = {}
    prices_per_mtok: dict[str, Price]
    cache_ttl_hours: int = 168
    max_calls_per_day: int = 600
    use_batch_api_for: list[str] = []
    task_max_tokens: dict[str, int] = {}

    @model_validator(mode="after")
    def _tiers(self) -> BudgetCfg:
        missing = {"fast", "balanced", "deep"} - set(self.models)
        if missing:
            raise ValueError(f"models must define tiers {sorted(missing)}")
        for alias in self.models.values():
            mid = self.model_ids.get(alias, alias)
            if mid not in self.prices_per_mtok:
                raise ValueError(f"no price for model '{mid}' (tier alias '{alias}')")
        return self

    def model_id(self, alias: str) -> str:
        return self.model_ids.get(alias, alias)


# ---------- skills.yaml ----------
class SkillNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    durability: Literal["fundamental", "evolving", "tool-specific"] = "evolving"
    prereqs: list[str] = []
    target_level: int = Field(4, ge=0, le=5)
    current_level: int = Field(1, ge=0, le=5)
    resources: list[dict[str, str]] = []
    children: list[SkillNode] = []


class SkillsCfg(Strict):
    domains: list[SkillNode]


class AppConfig(BaseModel):
    profile: ProfileCfg
    sources: SourcesCfg
    scoring: ScoringCfg
    routines: RoutinesCfg
    voice: VoiceCfg
    platforms: PlatformsCfg
    budget: BudgetCfg
    skills: SkillsCfg
