"""Persistent store (SQLite / Postgres) with MemoryStore-compatible API."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsie.db import (
    ArticleRow,
    DigestDraftRow,
    DigestRunRow,
    EmbeddingRow,
    PublicationRow,
    SourceRatingRow,
    SourceRow,
    StoryRow,
    init_db,
)
from newsie.domain import (
    AdapterKind,
    Article,
    ArticleEmbedding,
    DigestDraft,
    DigestRun,
    PerspectiveBrief,
    PoliticalEvent,
    Publication,
    Source,
    SourceTier,
    Story,
    TrustState,
)


class SqlStore:
    def __init__(self, database_url: str) -> None:
        self._Session = init_db(database_url)

    def _session(self) -> Session:
        return self._Session()

    def upsert_source(self, source: Source) -> None:
        with self._session() as s:
            row = s.get(SourceRow, source.id)
            data = dict(
                id=source.id,
                name=source.name,
                homepage_url=source.homepage_url,
                feed_url=source.feed_url,
                adapter=source.adapter.value,
                tier=source.tier.value,
                spectrum_tags=source.spectrum_tags,
                language=source.language,
                enabled=source.enabled,
                reliability_score=source.reliability_score,
                strike_count=source.strike_count,
                trust_state=source.trust_state.value,
                rate_limit_per_hour=source.rate_limit_per_hour,
            )
            if row is None:
                s.add(SourceRow(**data))
            else:
                for k, v in data.items():
                    setattr(row, k, v)
            s.commit()

    def list_enabled_sources(self) -> list[Source]:
        with self._session() as s:
            rows = s.scalars(select(SourceRow).where(SourceRow.enabled.is_(True))).all()
            return [self._to_source(r) for r in rows]

    @property
    def sources(self) -> dict[str, Source]:
        with self._session() as s:
            rows = s.scalars(select(SourceRow)).all()
            return {r.id: self._to_source(r) for r in rows}

    def get_article_by_hash(self, content_hash: str) -> Article | None:
        with self._session() as s:
            row = s.scalars(
                select(ArticleRow).where(ArticleRow.content_hash == content_hash)
            ).first()
            return self._to_article(row) if row else None

    def save_article(self, article: Article) -> Article:
        existing = self.get_article_by_hash(article.content_hash)
        if existing is not None:
            return existing
        with self._session() as s:
            s.add(
                ArticleRow(
                    id=str(article.id),
                    source_id=article.source_id,
                    url=article.url,
                    canonical_url=article.canonical_url,
                    title=article.title,
                    byline=article.byline,
                    published_at=article.published_at,
                    retrieved_at=article.retrieved_at,
                    content_text=article.content_text,
                    content_hash=article.content_hash,
                    lang=article.lang,
                    tier_at_ingest=article.tier_at_ingest.value,
                    raw_metadata=article.raw_metadata,
                    quarantine_reason=article.quarantine_reason,
                )
            )
            s.commit()
        return article

    def list_articles(self, *, skip_quarantined: bool = True) -> list[Article]:
        with self._session() as s:
            rows = list(s.scalars(select(ArticleRow)).all())
            arts = [self._to_article(r) for r in rows]
        if skip_quarantined:
            arts = [a for a in arts if a.quarantine_reason is None]
        return arts

    def save_embedding(self, emb: ArticleEmbedding) -> None:
        with self._session() as s:
            row = s.get(EmbeddingRow, str(emb.article_id))
            data = dict(
                article_id=str(emb.article_id),
                embedding=emb.embedding,
                embedding_model=emb.embedding_model,
                embedding_dim=emb.embedding_dim,
                embedded_at=emb.embedded_at,
            )
            if row is None:
                s.add(EmbeddingRow(**data))
            else:
                for k, v in data.items():
                    setattr(row, k, v)
            s.commit()

    def get_embedding(self, article_id: UUID) -> ArticleEmbedding | None:
        with self._session() as s:
            row = s.get(EmbeddingRow, str(article_id))
            if row is None:
                return None
            return ArticleEmbedding(
                article_id=UUID(row.article_id),
                embedding=list(row.embedding),
                embedding_model=row.embedding_model,
                embedding_dim=row.embedding_dim,
                embedded_at=row.embedded_at,
            )

    def articles_missing_embeddings(self) -> list[Article]:
        with self._session() as s:
            arts = list(s.scalars(select(ArticleRow)).all())
            emb_ids = set(s.scalars(select(EmbeddingRow.article_id)).all())
            return [
                self._to_article(a)
                for a in arts
                if a.id not in emb_ids and a.quarantine_reason is None
            ]

    def save_story(self, story: Story) -> None:
        with self._session() as s:
            existing = s.scalars(
                select(StoryRow).where(StoryRow.fingerprint == story.fingerprint)
            ).first()
            data = dict(
                id=str(existing.id) if existing else str(story.id),
                fingerprint=story.fingerprint,
                first_seen_at=story.first_seen_at,
                last_seen_at=story.last_seen_at,
                corroboration_score=story.corroboration_score,
                title_hint=story.title_hint,
                status=story.status,
                article_ids=[str(i) for i in story.article_ids],
            )
            if existing is None:
                s.add(StoryRow(**data))
            else:
                for k, v in data.items():
                    setattr(existing, k, v)
            s.commit()

    def list_stories(self) -> list[Story]:
        with self._session() as s:
            rows = s.scalars(select(StoryRow)).all()
            return [self._to_story(r) for r in rows]

    def save_run(self, run: DigestRun) -> None:
        with self._session() as s:
            row = s.get(DigestRunRow, str(run.id))
            data = dict(
                id=str(run.id),
                scheduled_for=run.scheduled_for,
                started_at=run.started_at,
                finished_at=run.finished_at,
                status=run.status,
                kill_switch_hit=run.kill_switch_hit,
                budget_snapshot=run.budget_snapshot,
            )
            if row is None:
                s.add(DigestRunRow(**data))
            else:
                for k, v in data.items():
                    setattr(row, k, v)
            s.commit()

    def save_draft(self, draft: DigestDraft) -> None:
        with self._session() as s:
            row = s.get(DigestDraftRow, str(draft.id))
            data = dict(
                id=str(draft.id),
                run_id=str(draft.run_id),
                story_ids=[str(i) for i in draft.story_ids],
                spine_md=draft.spine_md,
                perspectives_json=[p.model_dump(mode="json") for p in draft.perspectives],
                divergence_md=draft.divergence_md,
                events_json=[e.model_dump(mode="json") for e in draft.events],
                citations_json=draft.citations,
                english_render_md=draft.english_render_md,
                validation_status=draft.validation_status,
                created_at=draft.created_at,
            )
            if row is None:
                s.add(DigestDraftRow(**data))
            else:
                for k, v in data.items():
                    setattr(row, k, v)
            s.commit()

    def get_draft(self, draft_id: UUID) -> DigestDraft | None:
        with self._session() as s:
            row = s.get(DigestDraftRow, str(draft_id))
            return self._to_draft(row) if row else None

    def pending_drafts(self) -> list[DigestDraft]:
        with self._session() as s:
            pubs = set(s.scalars(select(PublicationRow.draft_id)).all())
            rows = s.scalars(
                select(DigestDraftRow).where(DigestDraftRow.validation_status == "ok")
            ).all()
            return [self._to_draft(r) for r in rows if r.id not in pubs]

    def save_publication(self, pub: Publication) -> None:
        with self._session() as s:
            existing = s.get(PublicationRow, str(pub.id))
            if existing is None:
                # idempotent by draft
                by_draft = s.scalars(
                    select(PublicationRow).where(PublicationRow.draft_id == str(pub.draft_id))
                ).first()
                if by_draft is not None:
                    return
                s.add(
                    PublicationRow(
                        id=str(pub.id),
                        draft_id=str(pub.draft_id),
                        approved_at=pub.approved_at,
                        telegram_message_ids=pub.telegram_message_ids,
                        immutable_snapshot=pub.immutable_snapshot,
                    )
                )
                s.commit()

    @property
    def publications(self) -> dict[UUID, Publication]:
        with self._session() as s:
            rows = s.scalars(select(PublicationRow)).all()
            out: dict[UUID, Publication] = {}
            for r in rows:
                out[UUID(r.id)] = Publication(
                    id=UUID(r.id),
                    draft_id=UUID(r.draft_id),
                    approved_at=r.approved_at,
                    telegram_message_ids=list(r.telegram_message_ids),
                    immutable_snapshot=dict(r.immutable_snapshot),
                )
            return out

    def rate_source(self, source_id: str, score: float) -> None:
        with self._session() as s:
            s.add(
                SourceRatingRow(
                    source_id=source_id,
                    score=score,
                    rated_at=datetime.now(UTC),
                )
            )
            ratings = s.scalars(
                select(SourceRatingRow).where(SourceRatingRow.source_id == source_id)
            ).all()
            avg = sum(r.score for r in ratings) / len(ratings) if ratings else score
            src = s.get(SourceRow, source_id)
            if src is not None:
                src.reliability_score = max(0.1, min(1.5, avg))
            s.commit()

    def _to_source(self, r: SourceRow) -> Source:
        return Source(
            id=r.id,
            name=r.name,
            homepage_url=r.homepage_url,
            feed_url=r.feed_url,
            adapter=AdapterKind(r.adapter),
            tier=SourceTier(r.tier),
            spectrum_tags=list(r.spectrum_tags or []),
            language=r.language,
            enabled=r.enabled,
            reliability_score=r.reliability_score,
            strike_count=r.strike_count,
            trust_state=TrustState(r.trust_state),
            rate_limit_per_hour=r.rate_limit_per_hour,
        )

    def _to_article(self, r: ArticleRow) -> Article:
        return Article(
            id=UUID(r.id),
            source_id=r.source_id,
            url=r.url,
            canonical_url=r.canonical_url,
            title=r.title,
            byline=r.byline,
            published_at=r.published_at,
            retrieved_at=r.retrieved_at,
            content_text=r.content_text,
            content_hash=r.content_hash,
            lang=r.lang,
            tier_at_ingest=SourceTier(r.tier_at_ingest),
            raw_metadata=dict(r.raw_metadata or {}),
            quarantine_reason=r.quarantine_reason,
        )

    def _to_story(self, r: StoryRow) -> Story:
        return Story(
            id=UUID(r.id),
            fingerprint=r.fingerprint,
            first_seen_at=r.first_seen_at,
            last_seen_at=r.last_seen_at,
            corroboration_score=r.corroboration_score,
            title_hint=r.title_hint,
            status=r.status,
            article_ids=[UUID(i) for i in r.article_ids],
        )

    def _to_draft(self, r: DigestDraftRow) -> DigestDraft:
        return DigestDraft(
            id=UUID(r.id),
            run_id=UUID(r.run_id),
            story_ids=[UUID(i) for i in r.story_ids],
            spine_md=r.spine_md,
            perspectives=[PerspectiveBrief.model_validate(p) for p in r.perspectives_json],
            divergence_md=r.divergence_md,
            events=[PoliticalEvent.model_validate(e) for e in r.events_json],
            citations=list(r.citations_json),
            english_render_md=r.english_render_md,
            validation_status=r.validation_status,
            created_at=r.created_at,
        )
