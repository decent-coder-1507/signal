"""Task output schemas (§6.4, §6.7, §15.5). Extended milestone by milestone."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from signal_core.llm.schemas import Out, register

# ---------------- P1 enrich_items (§6.4) ----------------
EnrichContentType = Literal[
    "release",
    "research",
    "funding",
    "policy",
    "opinion",
    "tutorial",
    "benchmark",
    "incident",
    "launch",
    "other",
]


class KeyFact(Out):
    fact: str
    quote_span: str = Field(description="exact, verbatim substring of the item text that supports the fact")


class Entities(Out):
    companies: list[str] = []
    people: list[str] = []
    products: list[str] = []
    models: list[str] = []
    repos: list[str] = []
    papers: list[str] = []


class ItemEnrichmentOut(Out):
    item_id: str
    summary_1line: str = Field(description="≤ 25 words, factual, no hype words")
    summary_short: str = Field(description="3–5 sentences")
    key_facts: list[KeyFact] = []
    entities: Entities = Entities()
    topics: list[str] = []
    ring: Literal["core", "adjacent", "wide"] = "core"
    content_type: EnrichContentType = "other"
    tech_relevance: float = Field(0.0, ge=0, le=1)
    claims_needing_verification: list[str] = []
    is_primary_source: bool = False
    language: str = "en"


class EnrichBatch(Out):
    items: list[ItemEnrichmentOut]


# ---------------- P2 story_insight (§6.7) ----------------
ActionType = Literal["post", "build", "learn", "watch", "try", "ignore"]


class StoryAction(Out):
    type: ActionType
    label: str = Field(description="specific: platform+angle, skill name, idea one-liner, watch query…")
    platform: str | None = None
    angle: str | None = None
    skill: str | None = None
    detail: str | None = None


class StoryInsightOut(Out):
    what_happened: str = Field(description="3–5 neutral sentences; every factual sentence cites [item_id]")
    why_it_matters_to_you: str
    what_changes: str
    hype_verdict: Literal["substance", "mixed", "mostly_hype", "too_early"]
    hype_reasons: list[str] = []
    durability: Literal["fundamental", "trend", "churn"]
    durability_reason: str = ""
    moat_note: str = ""
    open_questions: list[str] = []
    actions: list[StoryAction] = []
    confidence: float = Field(0.5, ge=0, le=1)
    confidence_reason: str = ""
    reading_time: int = Field(3, ge=0, le=240)
    uncertainty_labels: list[str] = []


# ---------------- P3 relevance_judge (+ impact/durability/potentials, ADR-015) ----------------
class StoryJudgeOut(Out):
    relevance: float = Field(ge=0, le=1)
    reason: str
    matched_goals: list[str] = []
    matched_topics: list[str] = []
    impact: float = Field(0.5, ge=0, le=1, description="who is affected × magnitude × reversibility")
    durability: Literal["fundamental", "trend", "churn"] = "trend"
    content_potential: float = Field(0.5, ge=0, le=1)
    build_potential: float = Field(0.3, ge=0, le=1)
    learn_potential: float = Field(0.3, ge=0, le=1)


class StoryTitleOut(Out):
    title: str = Field(description="neutral, specific, no clickbait, ≤ 16 words")


class TieBreakOut(Out):
    same_event: bool
    reason: str = ""


class BriefToplineOut(Out):
    topline: str = Field(description="one sentence, ≤ 30 words: the day in one line")


class WatchCheckOut(Out):
    triggered: bool
    explanation: str = ""


# ---------------- STUDIO (§7.3–7.8) ----------------
AngleType = Literal[
    "explainer",
    "practitioner",
    "contrarian",
    "personal_story",
    "how_to",
    "prediction",
    "question",
    "india_lens",
    "build_in_public",
]
PlatformName = Literal["linkedin", "x", "x_thread", "instagram_carousel", "instagram_reel", "hashnode"]


class NeedInput(Out):
    question: str = Field(description="short question asking for a real personal detail")
    why: str = ""


class Angle(Out):
    angle_type: AngleType
    thesis: str = Field(description="one-line thesis")
    credibility: str = Field(description="why the author is credible to say it")
    needs_input: list[NeedInput] = []
    platforms: list[PlatformName] = []
    risk: Literal["low", "medium", "high"] = "low"


class AnglesOut(Out):
    angles: list[Angle] = Field(min_length=1, max_length=5)


class Claim(Out):
    sentence: str
    source_ids: list[str] = Field(description="item ids or r:<raw material id>; empty only for opinion")


class DraftVersionOut(Out):
    label: str = "A"
    body: str = ""
    thread: list[str] = []
    first_comment: str = ""


class WriterOut(Out):
    versions: list[DraftVersionOut] = Field(min_length=1, max_length=3)
    claims: list[Claim] = []


class CriterionScore(Out):
    points: float
    why: str = ""


class GradeOut(Out):
    scores: dict[str, CriterionScore]
    total: float = Field(ge=0, le=10)
    ai_phrases: list[str] = []
    top_edits: list[str] = Field(default=[], max_length=3)
    verdict: str = ""


class ClaimVerdict(Out):
    sentence: str
    verdict: Literal["supported", "partially", "unsupported"]
    evidence_span: str = ""
    fix_suggestion: str = ""


class FactCheckOut(Out):
    results: list[ClaimVerdict]


class SafetyFlag(Out):
    type: Literal["confidential", "accusation", "political", "legal_financial_advice", "overclaim", "other"]
    text: str
    severity: Literal["low", "medium", "high"] = "medium"
    note: str = ""


class SafetyOut(Out):
    flags: list[SafetyFlag] = []


# ---------------- STUDIO visual & long-form (§7.6–7.7, M5) ----------------
class Slide(Out):
    title: str
    body: str = ""
    code: str | None = None
    mermaid: str | None = None
    steps: list[str] = []
    visual_hint: str = ""
    alt: str = ""


class CarouselOut(Out):
    template: Literal["carousel-minimal", "carousel-code", "carousel-diagram"] = "carousel-minimal"
    slides: list[Slide] = Field(min_length=3, max_length=20)
    caption: str = ""
    hashtags: list[str] = []
    claims: list[Claim] = []


class ReelBeat(Out):
    t_start: float = Field(ge=0)
    t_end: float = Field(gt=0)
    voiceover: str
    on_screen: str = ""
    shot: str = Field("", description="B-roll / screen-recording shot")


class ReelOut(Out):
    hook: ReelBeat
    beats: list[ReelBeat] = Field(min_length=2)
    caption: str = ""
    cover_text: str = ""
    hashtags: list[str] = []
    audio_mood: str = ""
    claims: list[Claim] = []


class ArticleRef(Out):
    title: str
    url: str


class ArticleOut(Out):
    seo_title: str
    subtitle: str = ""
    tldr: str
    body_md: str = Field(description="Markdown body with ## sections and fenced code blocks")
    tags: list[str] = Field(default=[], max_length=5)
    references: list[ArticleRef] = []
    cover_title: str = ""
    claims: list[Claim] = []


# ---------------- LAB (§8) ----------------
IdeaType = Literal[
    "practical", "experiment", "poc", "weekend_build", "product", "oss_contribution", "teardown", "vanco"
]


class Evidence(Out):
    ref: str = Field(description="story id or item id from the provided list")
    why: str


class IdeaScores(Out):
    impact: float = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=10)
    ease: float = Field(ge=0, le=10)
    personal_fit: float = Field(ge=0, le=10)
    learning_value: float = Field(ge=0, le=10)
    content_value: float = Field(ge=0, le=10)
    novelty: float = Field(ge=0, le=10)


class IdeaCard(Out):
    type: IdeaType
    title: str
    one_liner: str
    evidence: list[Evidence] = Field(min_length=1)
    problem: str
    persona: str
    why_now: str
    solution: str
    mvp_scope: list[str] = []
    not_in_mvp: list[str] = []
    stack: list[str] = []
    effort: dict[str, str | float] = {}
    risks: list[str] = []
    moat: str = ""
    validation_plan: list[str] = []
    learning_skills: list[str] = []
    content_plan: list[str] = []
    scores: IdeaScores
    prior_art_refs: list[str] = []


class SparkOut(Out):
    ideas: list[IdeaCard] = Field(default=[], max_length=3)


class BuildBriefOut(Out):
    brief_md: str
    claude_md: str
    experiment_md: str = ""


register(
    EnrichBatch,
    StoryInsightOut,
    StoryJudgeOut,
    StoryTitleOut,
    TieBreakOut,
    BriefToplineOut,
    WatchCheckOut,
    AnglesOut,
    WriterOut,
    GradeOut,
    FactCheckOut,
    SafetyOut,
    CarouselOut,
    ReelOut,
    ArticleOut,
    SparkOut,
    BuildBriefOut,
)


# ---------------- GYM (§9) ----------------
class LearnPlan(Out):
    explainer_topic: str
    resources: list[str] = Field(default=[], description="ids from the RESOURCES list only")
    practical: str = ""
    time_estimate: str = ""
    done_definition: str = ""


class LearnItem(Out):
    skill: str = Field(description="exact skill name from the list")
    why: str = Field(description="why this, why now; cites [story_id] markers")
    evidence: list[str] = Field(default=[], description="story ids from the list")
    ignore_instead: str = ""
    plan: LearnPlan


class LearnNextOut(Out):
    items: list[LearnItem] = Field(min_length=1, max_length=3)
    ignore: list[str] = []


class CardDraft(Out):
    type: Literal["qa", "cloze", "one_line", "scenario", "code"] = "qa"
    front: str
    back: str


class ExplainerOut(Out):
    body_md: str
    connects_to: str = ""
    citations: list[str] = []
    cards: list[CardDraft] = Field(min_length=3, max_length=5)


# ---------------- MOAT RADAR (§6.11) ----------------
class MoatPoint(Out):
    claim: str
    evidence: list[str] = Field(default=[], description="story ids")
    reasoning: str = ""


class MoatForYou(Out):
    know: list[MoatPoint] = Field(default=[], max_length=3)
    learn: list[MoatPoint] = Field(default=[], max_length=3)
    stop: list[MoatPoint] = Field(default=[], max_length=1)


class PredictionOut(Out):
    text: str
    revisit_in_days: int = Field(90, ge=7, le=730)


class PredictionReview(Out):
    id: str
    outcome: Literal["right", "wrong", "unclear"]
    evidence: list[str] = []
    note: str = ""


class MoatRadarOut(Out):
    commoditising: list[MoatPoint] = []
    appreciating: list[MoatPoint] = []
    for_you: MoatForYou = MoatForYou()
    for_builders: list[MoatPoint] = []
    predictions: list[PredictionOut] = []
    prediction_reviews: list[PredictionReview] = []


register(LearnNextOut, ExplainerOut, MoatRadarOut)


class ReviewSummaryOut(Out):
    summary: str = Field(description="4-6 calm sentences; cite [story_id] for facts")


register(ReviewSummaryOut)


class LearningsOut(Out):
    findings: list[str] = Field(description="what worked / didn't, each with sample size and caution")
    voice_rule_changes: dict[str, str | int | float | bool | list[str]] = {}
    add_banned_phrases: list[str] = []
    best_times: dict[str, list[str]] = {}
    angle_preferences: list[str] = []
    caveats: str = ""


register(LearningsOut)


class AskOut(Out):
    answer: str = Field(description="cite [chunk_id] after every factual sentence")
    insufficient: bool = Field(False, description="true when the chunks do not answer the question")


register(AskOut)
