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


def init_db(database_url: str) -> sessionmaker[Session]:
    engine = make_engine(database_url)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False, future=True)


def new_id() -> str:
    return str(uuid4())
