"""All tables from spec §12 (plus llm_cache, jobs, moat_radars, api tokens on users)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from signal_core.db.base import Base, Row, uuid7, vec

J = JSONB
Arr = ARRAY(String)


def fk(table: str, nullable: bool = False, ondelete: str = "CASCADE") -> Any:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{table}.id", ondelete=ondelete), nullable=nullable, index=True
    )


def hnsw(table: str, col: str = "embedding") -> Index:
    return Index(
        f"ix_{table}_{col}_hnsw", col, postgresql_using="hnsw", postgresql_ops={col: "vector_cosine_ops"}
    )


# ---------------- users / settings / profile ----------------
class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    api_token_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Setting(Row):
    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[Any] = mapped_column(J)


class Profile(Row):
    __tablename__ = "profiles"
    role: Mapped[str] = mapped_column(Text, default="")
    goals: Mapped[list[str]] = mapped_column(Arr, default=list)
    stack: Mapped[list[str]] = mapped_column(Arr, default=list)
    topics: Mapped[Any] = mapped_column(J, default=dict)
    blocked_entities: Mapped[list[str]] = mapped_column(Arr, default=list)
    blocked_keywords: Mapped[list[str]] = mapped_column(Arr, default=list)
    vanco_context: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)


class ProfileVector(Row):
    __tablename__ = "profile_vectors"
    __table_args__ = (hnsw("profile_vectors"),)
    profile_id: Mapped[uuid.UUID] = fk("profiles")
    kind: Mapped[str] = mapped_column(String(16), default="topic")  # topic|goal|stack
    label: Mapped[str] = mapped_column(String(255))
    ring: Mapped[str] = mapped_column(String(16), default="core")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    embedding: Mapped[Any] = mapped_column(vec())


# ---------------- RADAR ----------------
class Source(Row):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(Text)
    tier: Mapped[int] = mapped_column(Integer, default=2)
    ring: Mapped[str] = mapped_column(String(16), default="core")
    topics: Mapped[list[str]] = mapped_column(Arr, default=list)
    fetch_every: Mapped[int] = mapped_column(Integer, default=60)  # minutes
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auth_ref: Mapped[str | None] = mapped_column(String(128))
    params: Mapped[Any] = mapped_column(J, default=dict)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    health: Mapped[Any] = mapped_column(J, default=dict)
    usefulness: Mapped[float] = mapped_column(Float, default=0.0)
    terms_note: Mapped[str] = mapped_column(Text, default="")


class FetchLog(Row):
    __tablename__ = "fetch_logs"
    source_id: Mapped[uuid.UUID] = fk("sources")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))  # ok|error|not_modified
    items_found: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class Item(Row):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id"),
        UniqueConstraint("user_id", "url_hash"),
        Index("ix_items_status_published", "status", "published_at"),
        Index("ix_items_tsv", "tsv", postgresql_using="gin"),
        hnsw("items"),
    )
    source_id: Mapped[uuid.UUID] = fk("sources")
    external_id: Mapped[str] = mapped_column(String(512))
    canonical_url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    content_type: Mapped[str] = mapped_column(String(32), default="article")
    language: Mapped[str] = mapped_column(String(8), default="en")
    text: Mapped[str] = mapped_column(Text, default="")
    text_hash: Mapped[str] = mapped_column(String(64), default="")
    simhash: Mapped[int | None] = mapped_column(BigInteger)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    raw: Mapped[Any] = mapped_column(J, default=dict)
    duplicate_of: Mapped[uuid.UUID | None] = fk("items", nullable=True, ondelete="SET NULL")
    primary_source: Mapped[bool] = mapped_column(Boolean, default=False)
    prefilter_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        String(24), default="new"
    )  # new|prefiltered_out|enriched|archived|duplicate
    is_capture: Mapped[bool] = mapped_column(Boolean, default=False)
    capture_intent: Mapped[str | None] = mapped_column(String(16))
    signal_meta: Mapped[Any] = mapped_column(J, default=dict)  # points, stars, likes velocity
    embedding: Mapped[Any] = mapped_column(vec(), nullable=True)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(title,'') || ' ' || coalesce(text,''))", persisted=True),
    )


class ItemEnrichment(Row):
    __tablename__ = "item_enrichments"
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), unique=True
    )
    summary_1line: Mapped[str] = mapped_column(Text)
    summary_short: Mapped[str] = mapped_column(Text)
    key_facts: Mapped[Any] = mapped_column(J, default=list)
    entities: Mapped[Any] = mapped_column(J, default=dict)
    topics: Mapped[list[str]] = mapped_column(Arr, default=list)
    ring: Mapped[str] = mapped_column(String(16), default="core")
    enrich_content_type: Mapped[str] = mapped_column(String(32), default="other")
    tech_relevance: Mapped[float] = mapped_column(Float, default=0.0)
    claims: Mapped[Any] = mapped_column(J, default=list)
    is_primary_source: Mapped[bool] = mapped_column(Boolean, default=False)
    rejected_facts: Mapped[int] = mapped_column(Integer, default=0)
    prompt_version: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))


class Entity(Row):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("user_id", "type", "name"),)
    type: Mapped[str] = mapped_column(String(16))  # company|person|product|model|repo|paper
    name: Mapped[str] = mapped_column(String(255))
    aliases: Mapped[list[str]] = mapped_column(Arr, default=list)
    embedding: Mapped[Any] = mapped_column(vec(), nullable=True)


class ItemEntity(Row):
    __tablename__ = "item_entities"
    __table_args__ = (UniqueConstraint("item_id", "entity_id"),)
    item_id: Mapped[uuid.UUID] = fk("items")
    entity_id: Mapped[uuid.UUID] = fk("entities")


class Story(Row):
    __tablename__ = "stories"
    __table_args__ = (
        Index("ix_stories_score_updated", "final_score", "last_updated"),
        Index("ix_stories_tsv", "tsv", postgresql_using="gin"),
        hnsw("stories", "centroid"),
    )
    title: Mapped[str] = mapped_column(Text)
    centroid: Mapped[Any] = mapped_column(vec(), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|dormant|merged
    merged_into: Mapped[uuid.UUID | None] = fk("stories", nullable=True, ondelete="SET NULL")
    followed: Mapped[bool] = mapped_column(Boolean, default=False)
    scores: Mapped[Any] = mapped_column(J, default=dict)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    ring: Mapped[str] = mapped_column(String(16), default="core")
    topics: Mapped[list[str]] = mapped_column(Arr, default=list)
    entity_names: Mapped[list[str]] = mapped_column(Arr, default=list)
    durability: Mapped[str | None] = mapped_column(String(16))
    hype_verdict: Mapped[str | None] = mapped_column(String(16))
    last_shown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    material_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    what_changed: Mapped[str | None] = mapped_column(Text)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', coalesce(title,''))", persisted=True)
    )


class StoryItem(Row):
    __tablename__ = "story_items"
    __table_args__ = (UniqueConstraint("story_id", "item_id"),)
    story_id: Mapped[uuid.UUID] = fk("stories")
    item_id: Mapped[uuid.UUID] = fk("items")
    role: Mapped[str] = mapped_column(String(16), default="report")  # primary|report|reaction|followup


class StoryInsight(Row):
    __tablename__ = "story_insights"
    __table_args__ = (UniqueConstraint("story_id", "version"),)
    story_id: Mapped[uuid.UUID] = fk("stories")
    version: Mapped[int] = mapped_column(Integer, default=1)
    what_happened: Mapped[str] = mapped_column(Text)
    why_you: Mapped[str] = mapped_column(Text)
    what_changes: Mapped[str] = mapped_column(Text)
    hype_verdict: Mapped[str] = mapped_column(String(16))
    hype_reasons: Mapped[Any] = mapped_column(J, default=list)
    durability: Mapped[str] = mapped_column(String(16))
    durability_reason: Mapped[str] = mapped_column(Text, default="")
    moat_note: Mapped[str] = mapped_column(Text, default="")
    open_questions: Mapped[Any] = mapped_column(J, default=list)
    actions: Mapped[Any] = mapped_column(J, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    confidence_reason: Mapped[str] = mapped_column(Text, default="")
    reading_time: Mapped[int] = mapped_column(Integer, default=0)
    uncertainty_labels: Mapped[list[str]] = mapped_column(Arr, default=list)
    citations: Mapped[Any] = mapped_column(J, default=list)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt_version: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))


class Feedback(Row):
    __tablename__ = "feedback"
    __table_args__ = (Index("ix_feedback_target", "target_type", "target_id"),)
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(
        String(16)
    )  # useful|not_for_me|more|less|wrong|known|opened|dwell|used|saved
    value: Mapped[float] = mapped_column(Float, default=1.0)
    context: Mapped[Any] = mapped_column(J, default=dict)


class PreferenceModel(Row):
    __tablename__ = "preference_models"
    version: Mapped[int] = mapped_column(Integer)
    features: Mapped[Any] = mapped_column(J, default=list)
    weights: Mapped[Any] = mapped_column(J, default=dict)
    metrics: Mapped[Any] = mapped_column(J, default=dict)


class Watch(Row):
    __tablename__ = "watches"
    query: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(vec(), nullable=True)
    filters: Mapped[Any] = mapped_column(J, default=dict)
    urgency: Mapped[str] = mapped_column(String(16), default="digest")  # instant|digest
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WatchHit(Row):
    __tablename__ = "watch_hits"
    __table_args__ = (UniqueConstraint("watch_id", "story_id"),)
    watch_id: Mapped[uuid.UUID] = fk("watches")
    story_id: Mapped[uuid.UUID] = fk("stories")
    explanation: Mapped[str] = mapped_column(Text, default="")
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    in_brief_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Brief(Row):
    __tablename__ = "briefs"
    routine_run_id: Mapped[uuid.UUID | None] = fk("runs", nullable=True, ondelete="SET NULL")
    kind: Mapped[str] = mapped_column(String(16))  # daily|weekly|monthly|custom|catchup
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content: Mapped[Any] = mapped_column(J, default=dict)
    rendered_md: Mapped[str] = mapped_column(Text, default="")
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Routine(Row):
    __tablename__ = "routines"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    name: Mapped[str] = mapped_column(String(128))
    cron: Mapped[str] = mapped_column(String(64))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    steps: Mapped[Any] = mapped_column(J, default=list)
    channels: Mapped[list[str]] = mapped_column(Arr, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    params: Mapped[Any] = mapped_column(J, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Run(Row):
    __tablename__ = "runs"
    routine_id: Mapped[uuid.UUID | None] = fk("routines", nullable=True, ondelete="SET NULL")
    name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|ok|error|degraded
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    outputs: Mapped[Any] = mapped_column(J, default=dict)
    log: Mapped[str] = mapped_column(Text, default="")


# ---------------- STUDIO ----------------
class VoiceProfile(Row):
    __tablename__ = "voice_profiles"
    version: Mapped[int] = mapped_column(Integer)
    rules: Mapped[Any] = mapped_column(J, default=dict)
    banned_phrases: Mapped[list[str]] = mapped_column(Arr, default=list)
    emoji_set: Mapped[list[str]] = mapped_column(Arr, default=list)
    platform_overrides: Mapped[Any] = mapped_column(J, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")


class ReferencePost(Row):
    __tablename__ = "reference_posts"
    __table_args__ = (hnsw("reference_posts"),)
    platform: Mapped[str] = mapped_column(String(24))
    text: Mapped[str] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[Any] = mapped_column(J, default=dict)
    embedding: Mapped[Any] = mapped_column(vec(), nullable=True)
    is_own: Mapped[bool] = mapped_column(Boolean, default=True)


class RawMaterial(Row):
    __tablename__ = "raw_materials"
    __table_args__ = (hnsw("raw_materials"),)
    kind: Mapped[str] = mapped_column(String(16))  # story|quote|number|failure|mentor|opinion
    text: Mapped[str] = mapped_column(Text)
    people: Mapped[list[str]] = mapped_column(Arr, default=list)
    date: Mapped[date | None] = mapped_column(Date)
    can_name: Mapped[bool] = mapped_column(Boolean, default=False)
    confidentiality: Mapped[str] = mapped_column(String(16), default="public")  # public|vague-only|private
    origin: Mapped[str] = mapped_column(String(24), default="manual")  # manual|ask_me|build_log
    embedding: Mapped[Any] = mapped_column(vec(), nullable=True)


class Series(Row):
    __tablename__ = "series"
    name: Mapped[str] = mapped_column(String(255))
    platform: Mapped[str] = mapped_column(String(24))
    cadence: Mapped[str] = mapped_column(String(64))  # cron
    template: Mapped[str] = mapped_column(Text, default="")
    slot: Mapped[str] = mapped_column(String(64), default="")


class ContentIdea(Row):
    __tablename__ = "content_ideas"
    seed_type: Mapped[str] = mapped_column(String(24))  # story|build_log|gym|moat|raw|free_text|series
    seed_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    seed_text: Mapped[str] = mapped_column(Text, default="")
    angle_type: Mapped[str] = mapped_column(String(32))
    thesis: Mapped[str] = mapped_column(Text)
    credibility: Mapped[str] = mapped_column(Text, default="")
    needs_input: Mapped[Any] = mapped_column(J, default=list)
    platform_suggestions: Mapped[list[str]] = mapped_column(Arr, default=list)
    risk: Mapped[str] = mapped_column(String(16), default="low")
    status: Mapped[str] = mapped_column(String(16), default="idea")
    source_ids: Mapped[Any] = mapped_column(J, default=list)
    embedding: Mapped[Any] = mapped_column(vec(), nullable=True)


class Draft(Row):
    __tablename__ = "drafts"
    content_idea_id: Mapped[uuid.UUID | None] = fk("content_ideas", nullable=True, ondelete="SET NULL")
    platform: Mapped[str] = mapped_column(String(24))
    format: Mapped[str] = mapped_column(String(24))  # post|thread|carousel|reel|article|doc_carousel
    status: Mapped[str] = mapped_column(String(16), default="drafting")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    series_id: Mapped[uuid.UUID | None] = fk("series", nullable=True, ondelete="SET NULL")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timeliness_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_override: Mapped[Any] = mapped_column(J, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evergreen: Mapped[bool] = mapped_column(Boolean, default=False)
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending_questions: Mapped[Any] = mapped_column(J, default=list)
    parent_draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class DraftVersion(Row):
    __tablename__ = "draft_versions"
    __table_args__ = (UniqueConstraint("draft_id", "version"),)
    draft_id: Mapped[uuid.UUID] = fk("drafts")
    version: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(64), default="A")
    body: Mapped[str] = mapped_column(Text, default="")
    slides: Mapped[Any] = mapped_column(J, nullable=True)
    script: Mapped[Any] = mapped_column(J, nullable=True)
    thread: Mapped[Any] = mapped_column(J, nullable=True)
    first_comment: Mapped[str] = mapped_column(Text, default="")
    claims: Mapped[Any] = mapped_column(J, default=list)
    grade: Mapped[Any] = mapped_column(J, nullable=True)
    factcheck: Mapped[Any] = mapped_column(J, nullable=True)
    aitell: Mapped[Any] = mapped_column(J, nullable=True)
    checks: Mapped[Any] = mapped_column(J, nullable=True)  # originality, safety, attribution
    voice_version: Mapped[int] = mapped_column(Integer, default=1)
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    author: Mapped[str] = mapped_column(String(8), default="ai")  # ai|human


class Asset(Row):
    __tablename__ = "assets"
    draft_id: Mapped[uuid.UUID | None] = fk("drafts", nullable=True)
    kind: Mapped[str] = mapped_column(String(8))  # png|pdf|svg|md|zip
    path: Mapped[str] = mapped_column(Text)
    meta: Mapped[Any] = mapped_column(J, default=dict)


class Publication(Row):
    __tablename__ = "publications"
    __table_args__ = (hnsw("publications"),)
    draft_id: Mapped[uuid.UUID | None] = fk("drafts", nullable=True, ondelete="SET NULL")
    platform: Mapped[str] = mapped_column(String(24))
    url: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    text: Mapped[str] = mapped_column(Text, default="")
    variables: Mapped[Any] = mapped_column(J, default=dict)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding: Mapped[Any] = mapped_column(vec(), nullable=True)


class Metric(Row):
    __tablename__ = "metrics"
    publication_id: Mapped[uuid.UUID] = fk("publications")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizon: Mapped[str] = mapped_column(String(8))  # 48h|7d|custom
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    reactions: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    reposts: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    profile_views: Mapped[int] = mapped_column(Integer, default=0)
    followers_gained: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(8), default="manual")  # manual|csv|api


class Experiment(Row):
    __tablename__ = "experiments"
    name: Mapped[str] = mapped_column(String(255))
    variable: Mapped[str] = mapped_column(String(64))
    variants: Mapped[Any] = mapped_column(J, default=list)
    start: Mapped[date] = mapped_column(Date)
    end: Mapped[date | None] = mapped_column(Date)
    result: Mapped[Any] = mapped_column(J, nullable=True)


# ---------------- LAB ----------------
class Idea(Row):
    __tablename__ = "ideas"
    type: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(Text)
    one_liner: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[Any] = mapped_column(J, default=list)
    problem: Mapped[str] = mapped_column(Text, default="")
    persona: Mapped[str] = mapped_column(Text, default="")
    why_now: Mapped[str] = mapped_column(Text, default="")
    solution: Mapped[str] = mapped_column(Text, default="")
    mvp_scope: Mapped[Any] = mapped_column(J, default=list)
    not_in_mvp: Mapped[Any] = mapped_column(J, default=list)
    stack: Mapped[Any] = mapped_column(J, default=list)
    effort: Mapped[Any] = mapped_column(J, default=dict)
    risks: Mapped[Any] = mapped_column(J, default=list)
    moat: Mapped[str] = mapped_column(Text, default="")
    validation_plan: Mapped[Any] = mapped_column(J, default=list)
    learning_skills: Mapped[list[str]] = mapped_column(Arr, default=list)
    content_plan: Mapped[Any] = mapped_column(J, default=list)
    scores: Mapped[Any] = mapped_column(J, default=dict)
    lab_score: Mapped[float] = mapped_column(Float, default=0.0)
    prior_art: Mapped[Any] = mapped_column(J, default=list)
    status: Mapped[str] = mapped_column(String(16), default="spark")
    kill_reason: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(16), default="spark")  # spark|manual
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(64), default="")


class IdeaEvidence(Row):
    __tablename__ = "idea_evidence"
    idea_id: Mapped[uuid.UUID] = fk("ideas")
    story_id: Mapped[uuid.UUID | None] = fk("stories", nullable=True, ondelete="SET NULL")
    item_id: Mapped[uuid.UUID | None] = fk("items", nullable=True, ondelete="SET NULL")
    note: Mapped[str] = mapped_column(Text, default="")


class BuildLog(Row):
    __tablename__ = "build_logs"
    idea_id: Mapped[uuid.UUID] = fk("ideas")
    text: Mapped[str] = mapped_column(Text)
    attachments: Mapped[Any] = mapped_column(J, default=list)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BuildBrief(Row):
    __tablename__ = "build_briefs"
    idea_id: Mapped[uuid.UUID] = fk("ideas")
    files: Mapped[Any] = mapped_column(J, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(64), default="")


# ---------------- GYM ----------------
class Skill(Row):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    parent_id: Mapped[uuid.UUID | None] = fk("skills", nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    durability: Mapped[str] = mapped_column(String(16), default="evolving")
    prereqs: Mapped[list[str]] = mapped_column(Arr, default=list)
    target_level: Mapped[float] = mapped_column(Float, default=4)
    current_level: Mapped[float] = mapped_column(Float, default=1)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    market_signal: Mapped[float] = mapped_column(Float, default=0.0)
    market_trend: Mapped[float] = mapped_column(Float, default=1.0)
    resources: Mapped[Any] = mapped_column(J, default=list)


class SkillEvent(Row):
    __tablename__ = "skill_events"
    skill_id: Mapped[uuid.UUID] = fk("skills")
    kind: Mapped[str] = mapped_column(String(16))  # quiz|build|self|card_retention
    delta: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(Text, default="")


class Explainer(Row):
    __tablename__ = "explainers"
    __table_args__ = (UniqueConstraint("user_id", "topic", "depth"),)
    topic: Mapped[str] = mapped_column(String(255))
    depth: Mapped[str] = mapped_column(String(16))  # plain|engineer|deep
    body: Mapped[str] = mapped_column(Text)
    citations: Mapped[Any] = mapped_column(J, default=list)
    skill_ids: Mapped[Any] = mapped_column(J, default=list)
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(64), default="")


class Card(Row):
    __tablename__ = "cards"
    __table_args__ = (Index("ix_cards_due", "due_at"),)
    skill_id: Mapped[uuid.UUID | None] = fk("skills", nullable=True, ondelete="SET NULL")
    source_type: Mapped[str] = mapped_column(String(24), default="manual")
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(16), default="qa")  # qa|cloze|one_line|scenario|code
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    durability: Mapped[str] = mapped_column(String(16), default="fundamental")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fsrs_state: Mapped[Any] = mapped_column(J, default=dict)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CardReview(Row):
    __tablename__ = "card_reviews"
    card_id: Mapped[uuid.UUID] = fk("cards")
    rating: Mapped[int] = mapped_column(Integer)  # 1 again 2 hard 3 good 4 easy
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)


class Quiz(Row):
    __tablename__ = "quizzes"
    title: Mapped[str] = mapped_column(String(255), default="Weekly quiz")
    questions: Mapped[Any] = mapped_column(J, default=list)


class QuizAttempt(Row):
    __tablename__ = "quiz_attempts"
    quiz_id: Mapped[uuid.UUID] = fk("quizzes")
    answers: Mapped[Any] = mapped_column(J, default=list)
    score: Mapped[float] = mapped_column(Float, default=0.0)


class MoatRadar(Row):
    __tablename__ = "moat_radars"
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    topic: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[Any] = mapped_column(J, default=dict)
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(64), default="")


class Prediction(Row):
    __tablename__ = "predictions"
    text: Mapped[str] = mapped_column(Text)
    made_on: Mapped[date] = mapped_column(Date)
    revisit_on: Mapped[date] = mapped_column(Date)
    outcome: Mapped[str | None] = mapped_column(String(16))  # right|wrong|unclear
    evidence: Mapped[Any] = mapped_column(J, default=list)
    origin: Mapped[str] = mapped_column(String(16), default="moat_radar")


# ---------------- library / ask ----------------
class Note(Row):
    __tablename__ = "notes"
    __table_args__ = (Index("ix_notes_tsv", "tsv", postgresql_using="gin"), hnsw("notes"))
    kind: Mapped[str] = mapped_column(String(16), default="note")  # note|highlight
    text: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str | None] = mapped_column(String(24))
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    tags: Mapped[list[str]] = mapped_column(Arr, default=list)
    collection: Mapped[str | None] = mapped_column(String(128))
    embedding: Mapped[Any] = mapped_column(vec(), nullable=True)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', coalesce(text,''))", persisted=True)
    )


class ChatThread(Row):
    __tablename__ = "chat_threads"
    title: Mapped[str] = mapped_column(String(255), default="New thread")


class ChatMessage(Row):
    __tablename__ = "chat_messages"
    thread_id: Mapped[uuid.UUID] = fk("chat_threads")
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[Any] = mapped_column(J, default=list)
    meta: Mapped[Any] = mapped_column(J, default=dict, server_default="{}")  # mode, not_in_kb, offer_watch


# ---------------- ops ----------------
class LLMCall(Row):
    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_created", "created_at"),)
    task: Mapped[str] = mapped_column(String(64))
    tier: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(24), default="mock")
    prompt_version: Mapped[str] = mapped_column(String(32))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16))  # ok|invalid|error|cached|budget_blocked
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    error: Mapped[str | None] = mapped_column(Text)


class LLMCache(Base):
    __tablename__ = "llm_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    task: Mapped[str] = mapped_column(String(64))
    output: Mapped[Any] = mapped_column(J)
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Job(Row):
    """Job attempts and dead letters (§16.4)."""

    __tablename__ = "jobs"
    name: Mapped[str] = mapped_column(String(128))
    key: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(16))  # queued|ok|error|dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[Any] = mapped_column(J, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class Notification(Row):
    __tablename__ = "notifications"
    channel: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[Any] = mapped_column(J, default=dict)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|sent|suppressed|failed
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HabitDay(Row):
    __tablename__ = "habit_days"
    __table_args__ = (UniqueConstraint("user_id", "date"),)
    date: Mapped[date] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(16), default="missed")  # full|minimum|freeze|missed
    steps: Mapped[Any] = mapped_column(J, default=dict)


class EvalCase(Row):
    __tablename__ = "eval_cases"
    task: Mapped[str] = mapped_column(String(64))
    input: Mapped[Any] = mapped_column(J)
    expected: Mapped[Any] = mapped_column(J, default=dict)
    label: Mapped[str] = mapped_column(String(64), default="")
    origin: Mapped[str] = mapped_column(String(16), default="golden")  # user_report|golden


class EvalRun(Row):
    __tablename__ = "eval_runs"
    report: Mapped[Any] = mapped_column(J, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean, default=True)
