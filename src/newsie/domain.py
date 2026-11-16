"""Domain models — single source of truth for article/story/digest shapes."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, computed_field


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


class Spectrum(StrEnum):
    """Fixed placement vocabulary. One value per source, with a written basis."""

    LEFT = "left"
    CENTRE_LEFT = "centre-left"
    CENTRE = "centre"
    CENTRE_RIGHT = "centre-right"
    RIGHT = "right"
    REGIONAL = "regional"
    OFFICIAL = "official"
    PARTY = "party"


class ClaimType(StrEnum):
    FACT = "fact"
    ATTRIBUTED = "attributed_statement"
    OPINION = "opinion"


class Stance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    SILENT = "silent"


class EvidenceLabel(StrEnum):
    CORROBORATED = "corroborated"
    CONTESTED = "contested"
    SINGLE_ORIGIN = "single_origin"
    OFFICIAL_ONLY = "official_only"
    CIRCULATING = "circulating_unverified"


class Source(BaseModel):
    id: str
    name: str
    homepage_url: str
    feed_url: str | None = None
    adapter: AdapterKind = AdapterKind.RSS
    tier: SourceTier = SourceTier.REPORTING
    spectrum: Spectrum = Spectrum.CENTRE
    spectrum_basis: str = ""
    publisher_group: str | None = None
    language: str = "de"
    enabled: bool = True
    reliability_score: float = 1.0
    owner_preference: float = 1.0
    strike_count: int = 0
    trust_state: TrustState = TrustState.TRUSTED
    rate_limit_per_hour: int = 60

    @computed_field  # type: ignore[prop-decorator]
    @property
    def spectrum_tags(self) -> list[str]:
        """Single placement, exposed as a list so older readers keep working."""
        return [self.spectrum.value]


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
    full_text: str | None = None
    origin_id: str | None = None
    agency_credit: str | None = None
    extraction_method: str | None = None
    partial: bool = False

    def body_text(self) -> str:
        """Visible text claims may be drawn from. Never past a paywall cut."""
        return self.full_text or self.content_text


class ArticleEmbedding(BaseModel):
    article_id: UUID
    embedding: list[float]
    embedding_model: str
    embedding_dim: int
    embedded_at: datetime


class Story(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    # Stable unique token for the row. Not membership, and not recomputed when articles join.
    fingerprint: str = ""
    first_seen_at: datetime
    last_seen_at: datetime
    title_hint: str
    status: str = "active"
    article_ids: list[UUID] = Field(default_factory=list)
    centroid: list[float] | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    independent_origin_count: int = 0
    # Retired. Ranking uses independent_origin_count. Kept so older rows still load.
    corroboration_score: float = 0.0


class StoryArticle(BaseModel):
    story_id: UUID
    article_id: UUID
    similarity: float


class Claim(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    article_id: UUID
    text: str
    type: ClaimType
    speaker: str | None = None
    span_start: int
    span_end: int


class ClaimCluster(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    canonical_text: str
    label: EvidenceLabel
    origin_count: int = 0
    contradict_count: int = 0
    cross_spectrum: bool = False


class ClaimEvidence(BaseModel):
    claim_cluster_id: UUID
    article_id: UUID
    origin_id: str
    stance: Stance
    quote: str
    judge_model: str
    confidence: float = 1.0


class CitationRef(BaseModel):
    article_id: UUID
    url: str
    quote: str
    span_start: int | None = None
    span_end: int | None = None


class DigestSentence(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    draft_id: UUID | None = None
    story_id: UUID | None = None
    section: str
    text: str
    claim_cluster_id: UUID | None = None
    citations: list[CitationRef] = Field(default_factory=list)
    support_verdict: str = "unchecked"
    owner_flag: str | None = None


class PerspectiveBrief(BaseModel):
    party_label: str
    summary: str
    citation_urls: list[str] = Field(default_factory=list)
    story_id: UUID | None = None


class PoliticalEvent(BaseModel):
    title: str
    when: str | None = None
    where: str | None = None
    citation_urls: list[str] = Field(default_factory=list)
    story_id: UUID | None = None


class DigestDraft(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    story_ids: list[UUID]
    spine_md: str
    perspectives: list[PerspectiveBrief]
    divergence_md: str
    events: list[PoliticalEvent]
    citations: list[str] = Field(default_factory=list)
    sentences: list[DigestSentence] = Field(default_factory=list)
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


class SocialPost(BaseModel):
    """Raw post text is untrusted data. It never counts as evidence."""

    id: UUID = Field(default_factory=uuid4)
    platform: str
    external_id: str
    author_handle: str
    text: str
    reach: int = 0
    topic: str
    retrieved_at: datetime


class TrendPoint(BaseModel):
    topic: str
    window_start: datetime
    post_count: int
    baseline: float
    burst: bool


class StoryAttention(BaseModel):
    story_id: UUID
    topic: str
    attention: float
    marker: str


class FlagEvent(BaseModel):
    sentence_id: UUID
    draft_id: UUID
    flag: str
    recorded_at: datetime
