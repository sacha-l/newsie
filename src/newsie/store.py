"""In-memory store for demo/tests — idempotent upserts by content_hash / URL."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from newsie.domain import (
    Article,
    ArticleEmbedding,
    DigestDraft,
    DigestRun,
    Publication,
    Source,
    Story,
)


class MemoryStore:
    def __init__(self) -> None:
        self.sources: dict[str, Source] = {}
        self.articles_by_id: dict[UUID, Article] = {}
        self.articles_by_hash: dict[str, UUID] = {}
        self.embeddings: dict[UUID, ArticleEmbedding] = {}
        self.stories: dict[UUID, Story] = {}
        self.runs: dict[UUID, DigestRun] = {}
        self.drafts: dict[UUID, DigestDraft] = {}
        self.publications: dict[UUID, Publication] = {}
        self.source_ratings: list[tuple[str, float, datetime]] = []

    def upsert_source(self, source: Source) -> None:
        self.sources[source.id] = source

    def list_enabled_sources(self) -> list[Source]:
        return [s for s in self.sources.values() if s.enabled]

    def get_article_by_hash(self, content_hash: str) -> Article | None:
        article_id = self.articles_by_hash.get(content_hash)
        if article_id is None:
            return None
        return self.articles_by_id.get(article_id)

    def save_article(self, article: Article) -> Article:
        existing = self.get_article_by_hash(article.content_hash)
        if existing is not None:
            return existing
        self.articles_by_id[article.id] = article
        self.articles_by_hash[article.content_hash] = article.id
        return article

    def list_articles(self, *, skip_quarantined: bool = True) -> list[Article]:
        arts = list(self.articles_by_id.values())
        if skip_quarantined:
            arts = [a for a in arts if a.quarantine_reason is None]
        return arts

    def save_embedding(self, emb: ArticleEmbedding) -> None:
        self.embeddings[emb.article_id] = emb

    def get_embedding(self, article_id: UUID) -> ArticleEmbedding | None:
        return self.embeddings.get(article_id)

    def articles_missing_embeddings(self) -> list[Article]:
        return [
            a
            for a in self.list_articles()
            if a.id not in self.embeddings
        ]

    def save_story(self, story: Story) -> None:
        self.stories[story.id] = story

    def list_stories(self) -> list[Story]:
        return list(self.stories.values())

    def save_run(self, run: DigestRun) -> None:
        self.runs[run.id] = run

    def save_draft(self, draft: DigestDraft) -> None:
        self.drafts[draft.id] = draft

    def get_draft(self, draft_id: UUID) -> DigestDraft | None:
        return self.drafts.get(draft_id)

    def pending_drafts(self) -> list[DigestDraft]:
        published = {p.draft_id for p in self.publications.values()}
        return [
            d
            for d in self.drafts.values()
            if d.id not in published and d.validation_status == "ok"
        ]

    def save_publication(self, pub: Publication) -> None:
        self.publications[pub.id] = pub

    def rate_source(self, source_id: str, score: float) -> None:
        self.source_ratings.append((source_id, score, datetime.now(UTC)))
        source = self.sources.get(source_id)
        if source is None:
            return
        ratings = [s for sid, s, _ in self.source_ratings if sid == source_id]
        if ratings:
            avg = sum(ratings) / len(ratings)
            updated = source.model_copy(update={"reliability_score": max(0.1, min(1.5, avg))})
            self.sources[source_id] = updated
