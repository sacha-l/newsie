"""Domain models — single source of truth for article/story/digest shapes."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl


class SourceTier(StrEnum):
    REPORTING = "reporting"
    OFFICIAL = "official"
    OPINION = "opinion"
    SOCIAL_SIGNAL = "social_signal"
    AGENT_DERIVED = "agent_derived"


class AdapterKind(StrEnum):
    RSS = "rss"
    HTTP = "http"
    PLAYWRIGHT = "playwright"
    AGENT = "agent"
    FIXTURE = "fixture"


class TrustState(StrEnum):
    QUARANTINE = "quarantine"
    PROBATION = "probation"
    TRUSTED = "trusted"
    DISABLED = "disabled"


class Source(BaseModel):
    id: str
    name: str
    homepage_url: str
    feed_url: str | None = None
    adapter: AdapterKind = AdapterKind.RSS
    tier: SourceTier = SourceTier.REPORTING
    spectrum_tags: list[str] = Field(default_factory=list)
    language: str = "de"
    enabled: bool = True
    reliability_score: float = 1.0
    strike_count: int = 0
    trust_state: TrustState = TrustState.TRUSTED
    rate_limit_per_hour: int = 60


class ArticleCandidate(BaseModel):
    url: str
    title: str
    content_text: str
    published_at: datetime | None = None
    byline: str | None = None
    language: str = "de"
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class Article(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_id: str
    url: str
    canonical_url: str
    title: str
    byline: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    content_text: str
    content_hash: str
    lang: str = "de"
    tier_at_ingest: SourceTier
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    quarantine_reason: str | None = None


class ArticleEmbedding(BaseModel):
    article_id: UUID
    embedding: list[float]
    embedding_model: str
    embedding_dim: int
    embedded_at: datetime


class Story(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    fingerprint: str
    first_seen_at: datetime
    last_seen_at: datetime
    corroboration_score: float = 0.0
    title_hint: str
    status: str = "active"
    article_ids: list[UUID] = Field(default_factory=list)


class PerspectiveBrief(BaseModel):
    party_label: str
    summary: str
    citation_urls: list[str] = Field(default_factory=list)


class PoliticalEvent(BaseModel):
    title: str
    when: str | None = None
    where: str | None = None
    citation_urls: list[str] = Field(default_factory=list)


class DigestDraft(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    story_ids: list[UUID]
    spine_md: str
    perspectives: list[PerspectiveBrief]
    divergence_md: str
    events: list[PoliticalEvent]
    citations: list[str]
    english_render_md: str
    validation_status: str = "pending"
    created_at: datetime


class DigestRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    scheduled_for: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str = "pending"
    kill_switch_hit: bool = False
    budget_snapshot: dict[str, Any] = Field(default_factory=dict)


class Publication(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    draft_id: UUID
    approved_at: datetime
    telegram_message_ids: list[str] = Field(default_factory=list)
    immutable_snapshot: dict[str, Any] = Field(default_factory=dict)


class AgentRegistration(BaseModel):
    id: str
    name: str
    token_hash: str
    trust_state: TrustState = TrustState.QUARANTINE
    budget_caps: dict[str, int] = Field(default_factory=dict)


class Provenance(BaseModel):
    collector: str
    retrieved_at: datetime
    content_hash: str


class IngestArticlePayload(BaseModel):
    url: HttpUrl | str
    title: str
    content_text: str
    published_at: datetime | None = None
    language: str = "de"
    provenance: Provenance
