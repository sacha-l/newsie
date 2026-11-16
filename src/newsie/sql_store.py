"""Persistent store (SQLite / Postgres) with MemoryStore-compatible API."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from newsie.db import (
    ArticleRow,
    ClaimClusterRow,
    ClaimEvidenceRow,
    ClaimRow,
    ClaimVectorRow,
    DigestDraftRow,
    DigestRunRow,
    DigestSentenceRow,
    EmbeddingRow,
    FlagEventRow,
    PublicationRow,
    SocialPostRow,
    SourceRatingRow,
    SourceRow,
    StoryArticleRow,
    StoryAttentionRow,
    StoryRow,
    TrendPointRow,
    init_db,
)
from newsie.domain import (
    AdapterKind,
    Article,
    ArticleEmbedding,
    CitationRef,
    Claim,
    ClaimCluster,
    ClaimEvidence,
    ClaimType,
    DigestDraft,
    DigestRun,
    DigestSentence,
    EvidenceLabel,
    FlagEvent,
    PerspectiveBrief,
    PoliticalEvent,
    Publication,
    SocialPost,
    Source,
    SourceTier,
    Spectrum,
    Stance,
    Story,
    StoryAttention,
    TrendPoint,
    TrustState,
)


class SqlStore:
    def __init__(self, database_url: str) -> None:
        self._url = database_url
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
                spectrum=source.spectrum.value,
                spectrum_basis=source.spectrum_basis,
                publisher_group=source.publisher_group,
                owner_preference=source.owner_preference,
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
                    full_text=article.full_text,
                    origin_id=article.origin_id,
                    agency_credit=article.agency_credit,
                    extraction_method=article.extraction_method,
                    partial=article.partial,
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
        if not story.fingerprint:
            story = story.model_copy(update={"fingerprint": str(story.id)})
        with self._session() as s:
            existing = s.get(StoryRow, str(story.id))
            data = dict(
                id=str(story.id),
                fingerprint=story.fingerprint,
                first_seen_at=story.first_seen_at,
                last_seen_at=story.last_seen_at,
                corroboration_score=float(story.independent_origin_count),
                title_hint=story.title_hint,
                status=story.status,
                article_ids=[str(i) for i in story.article_ids],
                centroid=story.centroid,
                window_start=story.window_start,
                window_end=story.window_end,
                independent_origin_count=story.independent_origin_count,
                actors=list(story.actors),
                location=story.location,
                resolution_confidence=story.resolution_confidence,
                assignment_notes=list(story.assignment_notes),
                parent_story_id=str(story.parent_story_id) if story.parent_story_id else None,
            )
            if existing is None:
                s.add(StoryRow(**data))
            else:
                for key, value in data.items():
                    setattr(existing, key, value)
            s.execute(delete(StoryArticleRow).where(StoryArticleRow.story_id == str(story.id)))
            for article_id in story.article_ids:
                s.add(
                    StoryArticleRow(
                        story_id=str(story.id),
                        article_id=str(article_id),
                        similarity=1.0,
                    )
                )
            s.commit()

    def list_stories(self) -> list[Story]:
        with self._session() as s:
            rows = s.scalars(select(StoryRow)).all()
            membership = s.scalars(select(StoryArticleRow)).all()
            by_story: dict[str, list[UUID]] = {}
            for member in membership:
                by_story.setdefault(member.story_id, []).append(UUID(member.article_id))
            stories: list[Story] = []
            for row in rows:
                story = self._to_story(row)
                if row.id in by_story:
                    story = story.model_copy(update={"article_ids": by_story[row.id]})
                stories.append(story)
            return stories

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
            s.execute(delete(DigestSentenceRow).where(DigestSentenceRow.draft_id == str(draft.id)))
            for sentence in draft.sentences:
                s.add(
                    DigestSentenceRow(
                        id=str(sentence.id),
                        draft_id=str(draft.id),
                        story_id=str(sentence.story_id) if sentence.story_id else None,
                        section=sentence.section,
                        text=sentence.text,
                        claim_cluster_id=(
                            str(sentence.claim_cluster_id) if sentence.claim_cluster_id else None
                        ),
                        citations_json=[
                            item.model_dump(mode="json") for item in sentence.citations
                        ],
                        support_verdict=sentence.support_verdict,
                        owner_flag=sentence.owner_flag,
                    )
                )
            s.commit()

    def get_draft(self, draft_id: UUID) -> DigestDraft | None:
        with self._session() as s:
            row = s.get(DigestDraftRow, str(draft_id))
            if row is None:
                return None
            draft = self._to_draft(row)
            return draft.model_copy(update={"sentences": self._sentences(s, row.id)})

    def pending_drafts(self) -> list[DigestDraft]:
        with self._session() as s:
            pubs = set(s.scalars(select(PublicationRow.draft_id)).all())
            rows = s.scalars(
                select(DigestDraftRow).where(DigestDraftRow.validation_status == "ok")
            ).all()
            return [
                self._to_draft(r).model_copy(update={"sentences": self._sentences(s, r.id)})
                for r in rows
                if r.id not in pubs
            ]

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
                src.owner_preference = max(0.1, min(1.5, avg))
            s.commit()

    def update_article(self, article: Article) -> Article:
        with self._session() as s:
            row = s.get(ArticleRow, str(article.id))
            if row is None:
                return self.save_article(article)
            row.origin_id = article.origin_id
            row.agency_credit = article.agency_credit
            row.full_text = article.full_text
            row.extraction_method = article.extraction_method
            row.partial = article.partial
            row.canonical_url = article.canonical_url
            row.content_text = article.content_text
            row.content_hash = article.content_hash
            row.title = article.title
            s.commit()
        return article

    def replace_claims(self, article_id: UUID, claims: list[Claim]) -> None:
        with self._session() as s:
            s.execute(delete(ClaimRow).where(ClaimRow.article_id == str(article_id)))
            for claim in claims:
                s.add(
                    ClaimRow(
                        id=str(claim.id),
                        article_id=str(claim.article_id),
                        text=claim.text,
                        type=claim.type.value,
                        speaker=claim.speaker,
                        span_start=claim.span_start,
                        span_end=claim.span_end,
                    )
                )
            s.commit()

    def list_claims(self) -> list[Claim]:
        with self._session() as s:
            rows = s.scalars(select(ClaimRow)).all()
            return [
                Claim(
                    id=UUID(row.id),
                    article_id=UUID(row.article_id),
                    text=row.text,
                    type=ClaimType(row.type),
                    speaker=row.speaker,
                    span_start=row.span_start,
                    span_end=row.span_end,
                )
                for row in rows
            ]

    def replace_story_evidence(
        self,
        story_id: UUID,
        clusters: list[ClaimCluster],
        evidence: list[ClaimEvidence],
    ) -> None:
        with self._session() as s:
            existing = s.scalars(
                select(ClaimClusterRow.id).where(ClaimClusterRow.story_id == str(story_id))
            ).all()
            if existing:
                s.execute(
                    delete(ClaimEvidenceRow).where(ClaimEvidenceRow.claim_cluster_id.in_(existing))
                )
                s.execute(delete(ClaimClusterRow).where(ClaimClusterRow.story_id == str(story_id)))
            for cluster in clusters:
                s.add(
                    ClaimClusterRow(
                        id=str(cluster.id),
                        story_id=str(cluster.story_id),
                        canonical_text=cluster.canonical_text,
                        label=cluster.label.value,
                        origin_count=cluster.origin_count,
                        contradict_count=cluster.contradict_count,
                        cross_spectrum=cluster.cross_spectrum,
                        assessment=cluster.assessment,
                    )
                )
            for row in evidence:
                s.add(
                    ClaimEvidenceRow(
                        claim_cluster_id=str(row.claim_cluster_id),
                        article_id=str(row.article_id),
                        origin_id=row.origin_id,
                        stance=row.stance.value,
                        quote=row.quote,
                        judge_model=row.judge_model,
                        confidence=float(getattr(row, "confidence", 1.0) or 1.0),
                    )
                )
            s.commit()

    def list_clusters(self) -> list[ClaimCluster]:
        with self._session() as s:
            rows = s.scalars(select(ClaimClusterRow)).all()
            return [
                ClaimCluster(
                    id=UUID(row.id),
                    story_id=UUID(row.story_id),
                    canonical_text=row.canonical_text,
                    label=EvidenceLabel(row.label),
                    origin_count=row.origin_count,
                    contradict_count=row.contradict_count,
                    cross_spectrum=row.cross_spectrum,
                    assessment=getattr(row, "assessment", "") or "",
                )
                for row in rows
            ]

    def list_evidence(self) -> list[ClaimEvidence]:
        with self._session() as s:
            rows = s.scalars(select(ClaimEvidenceRow)).all()
            return [
                ClaimEvidence(
                    claim_cluster_id=UUID(row.claim_cluster_id),
                    article_id=UUID(row.article_id),
                    origin_id=row.origin_id,
                    stance=Stance(row.stance),
                    quote=row.quote,
                    judge_model=row.judge_model,
                    confidence=float(getattr(row, "confidence", 1.0) or 1.0),
                )
                for row in rows
            ]

    def mark_sentence_flag(
        self, draft_id: UUID, sentence_id: UUID, flag: str
    ) -> DigestSentence | None:
        with self._session() as s:
            row = s.get(DigestSentenceRow, str(sentence_id))
            if row is None or row.draft_id != str(draft_id):
                return None
            row.owner_flag = flag
            s.add(
                FlagEventRow(
                    sentence_id=str(sentence_id),
                    draft_id=str(draft_id),
                    flag=flag,
                    recorded_at=datetime.now(UTC),
                )
            )
            s.commit()
            return self._to_sentence(row)

    def record_citation_failure(self, source_id: str) -> None:
        with self._session() as s:
            src = s.get(SourceRow, source_id)
            if src is None:
                return
            src.strike_count = int(src.strike_count) + 1
            src.reliability_score = max(0.1, 1.0 / (1.0 + src.strike_count))
            s.commit()

    def save_claim_vector(self, claim_id: UUID, story_id: UUID, vector: list[float]) -> None:
        with self._session() as session:
            row = session.get(ClaimVectorRow, str(claim_id))
            if row is None:
                session.add(
                    ClaimVectorRow(
                        claim_id=str(claim_id),
                        story_id=str(story_id),
                        embedding=list(vector),
                    )
                )
            else:
                row.story_id = str(story_id)
                row.embedding = list(vector)
            session.commit()
        self._mirror_claim_vector(claim_id, story_id, vector)

    def drop_claim_embeddings(self, story_id: UUID) -> None:
        with self._session() as session:
            session.execute(delete(ClaimVectorRow).where(ClaimVectorRow.story_id == str(story_id)))
            session.commit()

    def list_claim_vectors(self, story_id: UUID) -> dict[UUID, list[float]]:
        with self._session() as session:
            rows = session.scalars(
                select(ClaimVectorRow).where(ClaimVectorRow.story_id == str(story_id))
            ).all()
            return {UUID(row.claim_id): list(row.embedding) for row in rows}

    def replace_social_posts(self, posts: list[SocialPost]) -> None:
        with self._session() as session:
            session.execute(delete(SocialPostRow))
            for post in posts:
                session.add(
                    SocialPostRow(
                        id=str(post.id),
                        platform=post.platform,
                        external_id=post.external_id,
                        author_handle=post.author_handle,
                        text=post.text,
                        reach=post.reach,
                        topic=post.topic,
                        retrieved_at=post.retrieved_at,
                    )
                )
            session.commit()

    def list_social_posts(self) -> list[SocialPost]:
        with self._session() as session:
            rows = session.scalars(select(SocialPostRow)).all()
            return [
                SocialPost(
                    id=UUID(row.id),
                    platform=row.platform,
                    external_id=row.external_id,
                    author_handle=row.author_handle,
                    text=row.text,
                    reach=row.reach,
                    topic=row.topic,
                    retrieved_at=row.retrieved_at,
                )
                for row in rows
            ]

    def replace_trends(self, points: list[TrendPoint]) -> None:
        with self._session() as session:
            session.execute(delete(TrendPointRow))
            for point in points:
                session.add(
                    TrendPointRow(
                        topic=point.topic,
                        window_start=point.window_start,
                        post_count=point.post_count,
                        baseline=point.baseline,
                        burst=point.burst,
                    )
                )
            session.commit()

    def list_trends(self) -> list[TrendPoint]:
        with self._session() as session:
            rows = session.scalars(select(TrendPointRow)).all()
            return [
                TrendPoint(
                    topic=row.topic,
                    window_start=row.window_start,
                    post_count=row.post_count,
                    baseline=row.baseline,
                    burst=row.burst,
                )
                for row in rows
            ]

    def replace_attention(self, rows: list[StoryAttention]) -> None:
        with self._session() as session:
            session.execute(delete(StoryAttentionRow))
            for row in rows:
                session.add(
                    StoryAttentionRow(
                        story_id=str(row.story_id),
                        topic=row.topic,
                        attention=row.attention,
                        marker=row.marker,
                    )
                )
            session.commit()

    def list_attention(self) -> list[StoryAttention]:
        with self._session() as session:
            rows = session.scalars(select(StoryAttentionRow)).all()
            return [
                StoryAttention(
                    story_id=UUID(row.story_id),
                    topic=row.topic,
                    attention=row.attention,
                    marker=row.marker,
                )
                for row in rows
            ]

    def list_flag_events(self, sentence_id: UUID) -> list[FlagEvent]:
        with self._session() as session:
            rows = session.scalars(
                select(FlagEventRow).where(FlagEventRow.sentence_id == str(sentence_id))
            ).all()
            return [
                FlagEvent(
                    sentence_id=UUID(row.sentence_id),
                    draft_id=UUID(row.draft_id),
                    flag=row.flag,
                    recorded_at=row.recorded_at,
                )
                for row in rows
            ]

    def _mirror_claim_vector(self, claim_id: UUID, story_id: UUID, vector: list[float]) -> None:
        """Copy a 512-d vector into pgvector when that column exists."""
        if "postgres" not in self._url or len(vector) != 512:
            return
        literal = "[" + ",".join(format(float(value), ".8g") for value in vector) + "]"
        statement = text(
            "insert into claim_embeddings "
            "(claim_id, story_id, embedding, embedding_model, embedded_at) "
            "values (:claim_id, :story_id, cast(:embedding as vector), :model, :at) "
            "on conflict (claim_id) do update set "
            "embedding = excluded.embedding, story_id = excluded.story_id, "
            "embedded_at = excluded.embedded_at"
        )
        try:
            with self._session() as session:
                session.execute(
                    statement,
                    {
                        "claim_id": str(claim_id),
                        "story_id": str(story_id),
                        "embedding": literal,
                        "model": "text-embedding-3-small",
                        "at": datetime.now(UTC),
                    },
                )
                session.commit()
        except SQLAlchemyError:
            return

    def nearest_story(self, embedding: list[float], when: datetime) -> tuple[UUID, float] | None:
        """pgvector nearest open centroid. SQLite and a missing function return None."""
        if "postgres" not in self._url:
            return None
        literal = "[" + ",".join(format(float(value), ".8g") for value in embedding) + "]"
        statement = text(
            "select story_id, similarity from nearest_open_story(cast(:q as vector), :at)"
        )
        try:
            with self._session() as session:
                row = session.execute(statement, {"q": literal, "at": when}).first()
        except SQLAlchemyError:
            return None
        if row is None or row[0] is None:
            return None
        return UUID(str(row[0])), float(row[1])

    def _to_source(self, r: SourceRow) -> Source:
        raw = (getattr(r, "spectrum", None) or "").strip().lower()
        if not raw and r.spectrum_tags:
            raw = str(r.spectrum_tags[0]).strip().lower()
        aliases = {
            "center": Spectrum.CENTRE,
            "centre": Spectrum.CENTRE,
            "center-left": Spectrum.CENTRE_LEFT,
            "centre-left": Spectrum.CENTRE_LEFT,
            "center-right": Spectrum.CENTRE_RIGHT,
            "centre-right": Spectrum.CENTRE_RIGHT,
            "left": Spectrum.LEFT,
            "right": Spectrum.RIGHT,
            "regional": Spectrum.REGIONAL,
            "official": Spectrum.OFFICIAL,
            "party": Spectrum.PARTY,
        }
        spectrum = aliases.get(raw, Spectrum.CENTRE)
        return Source(
            id=r.id,
            name=r.name,
            homepage_url=r.homepage_url,
            feed_url=r.feed_url,
            adapter=AdapterKind(r.adapter),
            tier=SourceTier(r.tier),
            spectrum=spectrum,
            spectrum_basis=getattr(r, "spectrum_basis", "") or "",
            publisher_group=getattr(r, "publisher_group", None),
            language=r.language,
            enabled=r.enabled,
            reliability_score=r.reliability_score,
            owner_preference=getattr(r, "owner_preference", 1.0) or 1.0,
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
            full_text=r.full_text,
            origin_id=r.origin_id,
            agency_credit=r.agency_credit,
            extraction_method=r.extraction_method,
            partial=bool(r.partial),
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
            centroid=list(r.centroid) if r.centroid else None,
            window_start=r.window_start,
            window_end=r.window_end,
            independent_origin_count=r.independent_origin_count or 0,
            actors=list(getattr(r, "actors", None) or []),
            location=getattr(r, "location", "") or "",
            resolution_confidence=float(getattr(r, "resolution_confidence", 1.0) or 1.0),
            assignment_notes=list(getattr(r, "assignment_notes", None) or []),
            parent_story_id=(
                UUID(r.parent_story_id) if getattr(r, "parent_story_id", None) else None
            ),
        )

    def _to_sentence(self, r: DigestSentenceRow) -> DigestSentence:
        return DigestSentence(
            id=UUID(r.id),
            draft_id=UUID(r.draft_id),
            story_id=UUID(r.story_id) if r.story_id else None,
            section=r.section,
            text=r.text,
            claim_cluster_id=UUID(r.claim_cluster_id) if r.claim_cluster_id else None,
            citations=[CitationRef.model_validate(item) for item in (r.citations_json or [])],
            support_verdict=r.support_verdict,
            owner_flag=r.owner_flag,
        )

    def _sentences(self, session: Session, draft_id: str) -> list[DigestSentence]:
        rows = session.scalars(
            select(DigestSentenceRow).where(DigestSentenceRow.draft_id == draft_id)
        ).all()
        return [self._to_sentence(row) for row in rows]

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
