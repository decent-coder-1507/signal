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
)
