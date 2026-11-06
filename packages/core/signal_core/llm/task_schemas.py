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


register(
    EnrichBatch, StoryInsightOut, StoryJudgeOut, StoryTitleOut, TieBreakOut, BriefToplineOut, WatchCheckOut
)
