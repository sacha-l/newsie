"""Story clustering via cosine similarity — idempotent merge by fingerprint."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import UUID, uuid4

from newsie.domain import Article, ArticleEmbedding, Source, SourceTier, Story
from newsie.guardrails import LoopGuard


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("vector length mismatch")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def corroboration_score(articles: list[Article], sources: dict[str, Source]) -> float:
    reporting_ids = {
        a.source_id
        for a in articles
        if a.tier_at_ingest in (SourceTier.REPORTING, SourceTier.OFFICIAL)
        and sources.get(a.source_id) is not None
    }
    return float(len(reporting_ids))


def cluster_articles(
    articles: list[Article],
    embeddings: dict[UUID, ArticleEmbedding],
    sources: dict[str, Source],
    *,
    threshold: float,
    max_iterations: int,
) -> list[Story]:
    """Greedy clustering; re-running with same inputs converges to same groupings by hash set."""
    guard = LoopGuard(max_iterations=max_iterations, name="cluster")
    now = datetime.now(UTC)
    stories: list[Story] = []
    assigned: set[UUID] = set()

    def _aware(dt: datetime | None) -> datetime:
        if dt is None:
            return now
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

    # Stable order for determinism
    ordered = sorted(articles, key=lambda a: (_aware(a.published_at), a.content_hash))

    for article in ordered:
        guard.tick()
        if article.id in assigned:
            continue
        emb = embeddings.get(article.id)
        if emb is None:
            continue
        members = [article]
        assigned.add(article.id)
        for other in ordered:
            guard.tick()
            if other.id in assigned:
                continue
            other_emb = embeddings.get(other.id)
            if other_emb is None:
                continue
            if cosine(emb.embedding, other_emb.embedding) >= threshold:
                members.append(other)
                assigned.add(other.id)
        member_ids = [m.id for m in members]
        fingerprint = "|".join(sorted(m.content_hash for m in members))
        stories.append(
            Story(
                id=uuid4(),
                fingerprint=fingerprint,
                first_seen_at=min((m.retrieved_at for m in members), default=now),
                last_seen_at=max((m.retrieved_at for m in members), default=now),
                corroboration_score=corroboration_score(members, sources),
                title_hint=members[0].title,
                article_ids=member_ids,
            )
        )
    return stories


def rank_stories(
    stories: list[Story],
    articles: dict[UUID, Article],
    sources: dict[str, Source],
    *,
    limit: int,
) -> list[Story]:
    def score(story: Story) -> float:
        rel = 1.0
        for aid in story.article_ids:
            art = articles.get(aid)
            if art is None:
                continue
            src = sources.get(art.source_id)
            if src is not None:
                rel = max(rel, src.reliability_score)
        return story.corroboration_score * rel

    ranked = sorted(stories, key=score, reverse=True)
    return ranked[:limit]
