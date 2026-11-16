"""In-memory store for demo/tests — idempotent upserts by content_hash / URL."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from newsie.domain import (
    Article,
    ArticleEmbedding,
    Claim,
    ClaimCluster,
    ClaimEvidence,
    DigestDraft,
    DigestRun,
    DigestSentence,
    FlagEvent,
    Publication,
    SocialPost,
    Source,
    Story,
    StoryArticle,
    StoryAttention,
    TrendPoint,
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
        self.claims: dict[UUID, Claim] = {}
        self.clusters: dict[UUID, ClaimCluster] = {}
        self.evidence: list[ClaimEvidence] = []
        self.sentences: dict[UUID, list[DigestSentence]] = {}
        self.claim_vectors: dict[UUID, tuple[UUID, list[float]]] = {}
        self.story_membership: list[StoryArticle] = []
        self.social_posts: list[SocialPost] = []
        self.trends: list[TrendPoint] = []
        self.attention: list[StoryAttention] = []
        self.flag_events: list[FlagEvent] = []

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
        return [a for a in self.list_articles() if a.id not in self.embeddings]

    def save_story(self, story: Story) -> None:
        if not story.fingerprint:
            story = story.model_copy(update={"fingerprint": str(story.id)})
        self.stories[story.id] = story
        self.story_membership = [row for row in self.story_membership if row.story_id != story.id]
        for article_id in story.article_ids:
            self.story_membership.append(
                StoryArticle(story_id=story.id, article_id=article_id, similarity=1.0)
            )

    def list_stories(self) -> list[Story]:
        return list(self.stories.values())

    def save_run(self, run: DigestRun) -> None:
        self.runs[run.id] = run

    def save_draft(self, draft: DigestDraft) -> None:
        self.drafts[draft.id] = draft
        self.sentences[draft.id] = list(draft.sentences)

    def get_draft(self, draft_id: UUID) -> DigestDraft | None:
        return self.drafts.get(draft_id)

    def pending_drafts(self) -> list[DigestDraft]:
        published = {p.draft_id for p in self.publications.values()}
        return [
            d for d in self.drafts.values() if d.id not in published and d.validation_status == "ok"
        ]

    def save_publication(self, pub: Publication) -> None:
        self.publications[pub.id] = pub

    def rate_source(self, source_id: str, score: float) -> None:
        """Owner taste. Does not change reliability_score."""
        self.source_ratings.append((source_id, score, datetime.now(UTC)))
        source = self.sources.get(source_id)
        if source is None:
            return
        ratings = [value for sid, value, _ in self.source_ratings if sid == source_id]
        if ratings:
            avg = sum(ratings) / len(ratings)
            updated = source.model_copy(update={"owner_preference": max(0.1, min(1.5, avg))})
            self.sources[source_id] = updated

    def update_article(self, article: Article) -> Article:
        self.articles_by_id[article.id] = article
        self.articles_by_hash[article.content_hash] = article.id
        return article

    def replace_claims(self, article_id: UUID, claims: list[Claim]) -> None:
        drop = [
            claim_id for claim_id, claim in self.claims.items() if claim.article_id == article_id
        ]
        for claim_id in drop:
            self.claims.pop(claim_id, None)
            self.claim_vectors.pop(claim_id, None)
        for claim in claims:
            self.claims[claim.id] = claim

    def list_claims(self) -> list[Claim]:
        return list(self.claims.values())

    def replace_story_evidence(
        self,
        story_id: UUID,
        clusters: list[ClaimCluster],
        evidence: list[ClaimEvidence],
    ) -> None:
        drop = [
            cluster_id
            for cluster_id, cluster in self.clusters.items()
            if cluster.story_id == story_id
        ]
        drop_set = set(drop)
        for cluster_id in drop:
            self.clusters.pop(cluster_id, None)
        self.evidence = [row for row in self.evidence if row.claim_cluster_id not in drop_set]
        for cluster in clusters:
            self.clusters[cluster.id] = cluster
        self.evidence.extend(evidence)

    def list_clusters(self) -> list[ClaimCluster]:
        return list(self.clusters.values())

    def list_evidence(self) -> list[ClaimEvidence]:
        return list(self.evidence)

    def mark_sentence_flag(
        self, draft_id: UUID, sentence_id: UUID, flag: str
    ) -> DigestSentence | None:
        draft = self.drafts.get(draft_id)
        if draft is None:
            return None
        updated_rows: list[DigestSentence] = []
        found: DigestSentence | None = None
        for sentence in draft.sentences:
            if sentence.id == sentence_id:
                found = sentence.model_copy(update={"owner_flag": flag})
                updated_rows.append(found)
            else:
                updated_rows.append(sentence)
        if found is None:
            return None
        self.drafts[draft_id] = draft.model_copy(update={"sentences": updated_rows})
        self.sentences[draft_id] = updated_rows
        self.append_flag_event(
            FlagEvent(
                sentence_id=sentence_id,
                draft_id=draft_id,
                flag=flag,
                recorded_at=datetime.now(UTC),
            )
        )
        return found

    def record_citation_failure(self, source_id: str) -> None:
        source = self.sources.get(source_id)
        if source is None:
            return
        strikes = source.strike_count + 1
        reliability = max(0.1, 1.0 / (1.0 + strikes))
        self.sources[source_id] = source.model_copy(
            update={"strike_count": strikes, "reliability_score": reliability}
        )

    def save_claim_vector(self, claim_id: UUID, story_id: UUID, vector: list[float]) -> None:
        self.claim_vectors[claim_id] = (story_id, vector)

    def drop_claim_embeddings(self, story_id: UUID) -> None:
        self.claim_vectors = {
            claim_id: pair for claim_id, pair in self.claim_vectors.items() if pair[0] != story_id
        }

    def nearest_story(self, embedding: list[float], when: datetime) -> tuple[UUID, float] | None:
        """No index here. assign_stories scans centroids instead."""
        _ = (embedding, when)
        return None

    def list_claim_vectors(self, story_id: UUID) -> dict[UUID, list[float]]:
        return {
            claim_id: vector
            for claim_id, (owner, vector) in self.claim_vectors.items()
            if owner == story_id
        }

    def replace_social_posts(self, posts: list[SocialPost]) -> None:
        self.social_posts = list(posts)

    def list_social_posts(self) -> list[SocialPost]:
        return list(self.social_posts)

    def replace_trends(self, points: list[TrendPoint]) -> None:
        self.trends = list(points)

    def list_trends(self) -> list[TrendPoint]:
        return list(self.trends)

    def replace_attention(self, rows: list[StoryAttention]) -> None:
        self.attention = list(rows)

    def list_attention(self) -> list[StoryAttention]:
        return list(self.attention)

    def append_flag_event(self, event: FlagEvent) -> None:
        self.flag_events.append(event)

    def list_flag_events(self, sentence_id: UUID) -> list[FlagEvent]:
        return [event for event in self.flag_events if event.sentence_id == sentence_id]


class Store(Protocol):
    """Shared store surface. MemoryStore and SqlStore both satisfy it."""

    @property
    def sources(self) -> dict[str, Source]: ...

    def upsert_source(self, source: Source) -> None: ...
    def list_enabled_sources(self) -> list[Source]: ...
    def get_article_by_hash(self, content_hash: str) -> Article | None: ...
    def save_article(self, article: Article) -> Article: ...
    def list_articles(self, *, skip_quarantined: bool = ...) -> list[Article]: ...
    def update_article(self, article: Article) -> Article: ...
    def articles_missing_embeddings(self) -> list[Article]: ...
    def save_embedding(self, emb: ArticleEmbedding) -> None: ...
    def get_embedding(self, article_id: UUID) -> ArticleEmbedding | None: ...
    def save_story(self, story: Story) -> None: ...
    def list_stories(self) -> list[Story]: ...
    def nearest_story(
        self, embedding: list[float], when: datetime
    ) -> tuple[UUID, float] | None: ...
    def drop_claim_embeddings(self, story_id: UUID) -> None: ...
    def replace_claims(self, article_id: UUID, claims: list[Claim]) -> None: ...
    def list_claims(self) -> list[Claim]: ...
    def save_claim_vector(self, claim_id: UUID, story_id: UUID, vector: list[float]) -> None: ...
    def replace_story_evidence(
        self, story_id: UUID, clusters: list[ClaimCluster], evidence: list[ClaimEvidence]
    ) -> None: ...
    def list_clusters(self) -> list[ClaimCluster]: ...
    def list_evidence(self) -> list[ClaimEvidence]: ...
    def save_run(self, run: DigestRun) -> None: ...
    def save_draft(self, draft: DigestDraft) -> None: ...
    def list_social_posts(self) -> list[SocialPost]: ...
    def replace_trends(self, points: list[TrendPoint]) -> None: ...
    def list_trends(self) -> list[TrendPoint]: ...
    def replace_attention(self, rows: list[StoryAttention]) -> None: ...
    def list_attention(self) -> list[StoryAttention]: ...
