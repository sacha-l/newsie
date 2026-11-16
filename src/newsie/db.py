"""SQLAlchemy models + engine factory (SQLite local / Postgres Supabase)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class SourceRow(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    homepage_url: Mapped[str] = mapped_column(String)
    feed_url: Mapped[str | None] = mapped_column(String, nullable=True)
    adapter: Mapped[str] = mapped_column(String, default="rss")
    tier: Mapped[str] = mapped_column(String, default="reporting")
    spectrum_tags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    language: Mapped[str] = mapped_column(String, default="de")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reliability_score: Mapped[float] = mapped_column(Float, default=1.0)
    strike_count: Mapped[int] = mapped_column(Integer, default=0)
    trust_state: Mapped[str] = mapped_column(String, default="trusted")
    rate_limit_per_hour: Mapped[int] = mapped_column(Integer, default=60)
    spectrum: Mapped[str] = mapped_column(String, default="centre")
    spectrum_basis: Mapped[str] = mapped_column(Text, default="")
    publisher_group: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_preference: Mapped[float] = mapped_column(Float, default=1.0)


class ArticleRow(Base):
    __tablename__ = "articles"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    canonical_url: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    byline: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String, unique=True)
    lang: Mapped[str] = mapped_column(String, default="de")
    tier_at_ingest: Mapped[str] = mapped_column(String)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quarantine_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_id: Mapped[str | None] = mapped_column(String, nullable=True)
    agency_credit: Mapped[str | None] = mapped_column(String, nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String, nullable=True)
    partial: Mapped[bool] = mapped_column(Boolean, default=False)


class EmbeddingRow(Base):
    __tablename__ = "article_embeddings"
    article_id: Mapped[str] = mapped_column(String, primary_key=True)
    # Store as JSON list for SQLite portability; Postgres can later use vector column via migration
    embedding: Mapped[list[float]] = mapped_column(JSON)
    embedding_model: Mapped[str] = mapped_column(String)
    embedding_dim: Mapped[int] = mapped_column(Integer)
    embedded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StoryRow(Base):
    __tablename__ = "stories"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String, unique=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    corroboration_score: Mapped[float] = mapped_column(Float, default=0.0)
    title_hint: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active")
    article_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    centroid: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    independent_origin_count: Mapped[int] = mapped_column(Integer, default=0)


class DigestRunRow(Base):
    __tablename__ = "digest_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String)
    kill_switch_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    budget_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DigestDraftRow(Base):
    __tablename__ = "digest_drafts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String)
    story_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    spine_md: Mapped[str] = mapped_column(Text)
    perspectives_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    divergence_md: Mapped[str] = mapped_column(Text)
    events_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    citations_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    english_render_md: Mapped[str] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PublicationRow(Base):
    __tablename__ = "publications"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    draft_id: Mapped[str] = mapped_column(String)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    telegram_message_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    immutable_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class StoryArticleRow(Base):
    __tablename__ = "story_articles"
    story_id: Mapped[str] = mapped_column(String, primary_key=True)
    article_id: Mapped[str] = mapped_column(String, primary_key=True)
    similarity: Mapped[float] = mapped_column(Float, default=0.0)


class ClaimRow(Base):
    __tablename__ = "claims"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    article_id: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String)
    speaker: Mapped[str | None] = mapped_column(String, nullable=True)
    span_start: Mapped[int] = mapped_column(Integer, default=0)
    span_end: Mapped[int] = mapped_column(Integer, default=0)


class ClaimClusterRow(Base):
    __tablename__ = "claim_clusters"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    story_id: Mapped[str] = mapped_column(String)
    canonical_text: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String)
    origin_count: Mapped[int] = mapped_column(Integer, default=0)
    contradict_count: Mapped[int] = mapped_column(Integer, default=0)
    cross_spectrum: Mapped[bool] = mapped_column(Boolean, default=False)


class ClaimEvidenceRow(Base):
    __tablename__ = "claim_evidence"
    claim_cluster_id: Mapped[str] = mapped_column(String, primary_key=True)
    article_id: Mapped[str] = mapped_column(String, primary_key=True)
    origin_id: Mapped[str] = mapped_column(String)
    stance: Mapped[str] = mapped_column(String)
    quote: Mapped[str] = mapped_column(Text, default="")
    judge_model: Mapped[str] = mapped_column(String, default="heuristic")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class DigestSentenceRow(Base):
    __tablename__ = "digest_sentences"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    draft_id: Mapped[str] = mapped_column(String)
    story_id: Mapped[str | None] = mapped_column(String, nullable=True)
    section: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    claim_cluster_id: Mapped[str | None] = mapped_column(String, nullable=True)
    citations_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    support_verdict: Mapped[str] = mapped_column(String, default="unchecked")
    owner_flag: Mapped[str | None] = mapped_column(String, nullable=True)


class ClaimVectorRow(Base):
    """JSON claim vectors for SQLite. Postgres also has claim_embeddings vector(512)."""

    __tablename__ = "claim_vectors"
    claim_id: Mapped[str] = mapped_column(String, primary_key=True)
    story_id: Mapped[str] = mapped_column(String)
    embedding: Mapped[list[float]] = mapped_column(JSON)


class FlagEventRow(Base):
    __tablename__ = "flag_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sentence_id: Mapped[str] = mapped_column(String)
    draft_id: Mapped[str] = mapped_column(String)
    flag: Mapped[str] = mapped_column(String)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SocialPostRow(Base):
    __tablename__ = "social_posts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    platform: Mapped[str] = mapped_column(String)
    external_id: Mapped[str] = mapped_column(String)
    author_handle: Mapped[str] = mapped_column(String, default="")
    text: Mapped[str] = mapped_column(Text)
    reach: Mapped[int] = mapped_column(Integer, default=0)
    topic: Mapped[str] = mapped_column(String, default="")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TrendPointRow(Base):
    __tablename__ = "trend_points"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(String)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    post_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline: Mapped[float] = mapped_column(Float, default=0.0)
    burst: Mapped[bool] = mapped_column(Boolean, default=False)


class StoryAttentionRow(Base):
    __tablename__ = "story_attention"
    story_id: Mapped[str] = mapped_column(String, primary_key=True)
    topic: Mapped[str] = mapped_column(String, primary_key=True)
    attention: Mapped[float] = mapped_column(Float, default=0.0)
    marker: Mapped[str] = mapped_column(String, default="")


class SourceRatingRow(Base):
    __tablename__ = "source_ratings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String)
    score: Mapped[float] = mapped_column(Float)
    rated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def make_engine(database_url: str) -> Any:
    url = database_url
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite:///"):
        connect_args["check_same_thread"] = False
    # Supabase often provides postgres:// — SQLAlchemy wants postgresql+psycopg://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, future=True, connect_args=connect_args)


def _sqlite_add_columns(engine: Any) -> None:
    """create_all does not alter existing SQLite files. Add the claim-layer columns."""
    if engine.dialect.name != "sqlite":
        return
    wanted: dict[str, list[tuple[str, str]]] = {
        "sources": [
            ("spectrum", "text not null default 'centre'"),
            ("spectrum_basis", "text not null default ''"),
            ("publisher_group", "text"),
            ("owner_preference", "float not null default 1.0"),
        ],
        "articles": [
            ("full_text", "text"),
            ("origin_id", "text"),
            ("agency_credit", "text"),
            ("extraction_method", "text"),
            ("partial", "boolean not null default 0"),
        ],
        "stories": [
            ("centroid", "text"),
            ("window_start", "datetime"),
            ("window_end", "datetime"),
            ("independent_origin_count", "integer not null default 0"),
        ],
        "claim_evidence": [
            ("confidence", "float not null default 1.0"),
        ],
    }
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in wanted.items():
            if table not in inspector.get_table_names():
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            for name, ddl in columns:
                if name in present:
                    continue
                conn.execute(text(f"alter table {table} add column {name} {ddl}"))


def init_db(database_url: str) -> sessionmaker[Session]:
    engine = make_engine(database_url)
    Base.metadata.create_all(engine)
    _sqlite_add_columns(engine)
    return sessionmaker(engine, expire_on_commit=False, future=True)


def new_id() -> str:
    return str(uuid4())
