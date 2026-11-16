"""Online story assignment by centroid. Story ids stay put when a new article joins.

Nearest-centroid lookup is the same rule pgvector runs with the HNSW index in
migrations/002_claims.sql (`nearest_open_story`). Pass `nearest` when the store
can run that query. Otherwise this module scans centroids in process, which is
what SQLite and the memory store do.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from newsie.domain import Article, ArticleEmbedding, Source, SourceTier, Story
from newsie.events import JoinDecision, describe_join, facets_of
from newsie.guardrails import LoopGuard

TIER_WEIGHT = {
    SourceTier.REPORTING: 1.0,
    SourceTier.OFFICIAL: 0.9,
    SourceTier.OPINION: 0.5,
    SourceTier.AGENT_DERIVED: 0.4,
    SourceTier.SOCIAL_SIGNAL: 0.2,
}


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("vector length mismatch")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _mean(vectors: list[list[float]]) -> list[float]:
    width = len(vectors[0])
    totals = [0.0] * width
    for vector in vectors:
        if len(vector) != width:
            raise ValueError("vector length mismatch")
        for index, value in enumerate(vector):
            totals[index] += value
    count = float(len(vectors))
    return [value / count for value in totals]


def _aware(dt: datetime | None, fallback: datetime) -> datetime:
    if dt is None:
        return fallback
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def independent_origin_count(articles: list[Article]) -> int:
    """Social posts never count. Missing origin ids fall back to the source id."""
    origins: set[str] = set()
    for article in articles:
        if article.tier_at_ingest == SourceTier.SOCIAL_SIGNAL:
            continue
        origins.add(article.origin_id or f"source:{article.source_id}")
    return len(origins)


def _in_window(story: Story, when: datetime) -> bool:
    if story.status == "closed":
        return False
    if story.window_start is not None and when < story.window_start:
        return False
    if story.window_end is not None and when > story.window_end:
        return False
    return True


NearestStory = Callable[[list[float], datetime], tuple[UUID, float] | None]


def assign_stories(
    articles: list[Article],
    embeddings: dict[UUID, ArticleEmbedding],
    existing: list[Story],
    *,
    threshold: float,
    window_hours: int,
    now: datetime | None = None,
    nearest: NearestStory | None = None,
) -> list[Story]:
    """Assign each article to the nearest open story centroid, or open a new story."""
    moment = now or datetime.now(UTC)
    guard = LoopGuard(max_iterations=len(articles) + len(existing) + 5, name="assign_stories")
    stories: list[Story] = []
    vectors: dict[UUID, list[list[float]]] = {}

    for story in existing:
        guard.tick()
        window_end = story.window_end
        status = story.status
        if window_end is not None and moment > window_end:
            status = "closed"
        stories.append(story.model_copy(update={"status": status}))
        if story.centroid is not None:
            vectors[story.id] = [story.centroid]

    assigned: dict[UUID, UUID] = {}
    for story in stories:
        for article_id in story.article_ids:
            assigned[article_id] = story.id

    ordered = sorted(
        articles,
        key=lambda article: (
            _aware(article.published_at, article.retrieved_at),
            article.content_hash,
        ),
    )
    for article in ordered:
        guard.tick()
        if article.id in assigned:
            continue
        embedding = embeddings.get(article.id)
        if embedding is None:
            continue
        when = _aware(article.published_at, article.retrieved_at)
        best: Story | None = None
        best_score = threshold
        if nearest is not None:
            found = nearest(list(embedding.embedding), when)
            if found is not None and found[1] >= threshold:
                hinted = next(
                    (
                        story
                        for story in stories
                        if story.id == found[0] and _in_window(story, when)
                    ),
                    None,
                )
                if hinted is not None:
                    best = hinted
                    best_score = found[1]
        if best is None:
            for story in stories:
                if story.centroid is None or not _in_window(story, when):
                    continue
                score = cosine(embedding.embedding, story.centroid)
                if score >= best_score:
                    best = story
                    best_score = score
        decision = JoinDecision(False, "", 1.0, (), "")
        rejected_id: UUID | None = None
        if best is not None:
            neighbours = [item for item in articles if item.id in set(best.article_ids)]
            decision = describe_join(article, best, neighbours, best_score)
            if not decision.join:
                rejected_id = best.id
                best = None
        if best is None:
            start = when
            actors, location = facets_of(f"{article.title} {article.body_text()[:500]}")
            note = f"{article.id}: opened as a new event"
            confidence = 1.0
            if rejected_id is not None:
                note = f"{article.id}: {decision.reason} near {rejected_id}"
                confidence = decision.confidence
                actors = decision.actors or actors
                location = decision.location or location
            opened = Story(
                fingerprint="",
                first_seen_at=article.retrieved_at,
                last_seen_at=article.retrieved_at,
                title_hint=article.title,
                status="active",
                article_ids=[article.id],
                centroid=list(embedding.embedding),
                window_start=start,
                window_end=start + timedelta(hours=window_hours),
                independent_origin_count=independent_origin_count([article]),
                actors=list(actors),
                location=location,
                resolution_confidence=confidence,
                assignment_notes=[note],
                parent_story_id=rejected_id,
            )
            opened = opened.model_copy(update={"fingerprint": str(opened.id)})
            stories.append(opened)
            vectors[opened.id] = [list(embedding.embedding)]
            assigned[article.id] = opened.id
            continue
        member_ids = list(dict.fromkeys([*best.article_ids, article.id]))
        bucket = vectors.setdefault(best.id, [best.centroid] if best.centroid else [])
        bucket.append(list(embedding.embedding))
        centroid = _mean(bucket)
        member_articles = [item for item in articles if item.id in set(member_ids)]
        if not any(item.id == article.id for item in member_articles):
            member_articles.append(article)
        updated = best.model_copy(
            update={
                "article_ids": member_ids,
                "centroid": centroid,
                "last_seen_at": max(best.last_seen_at, article.retrieved_at),
                "independent_origin_count": independent_origin_count(member_articles),
                "title_hint": best.title_hint or article.title,
                "actors": list(dict.fromkeys([*best.actors, *decision.actors])),
                "location": best.location or decision.location,
                "resolution_confidence": min(best.resolution_confidence, decision.confidence),
                "assignment_notes": [
                    *best.assignment_notes,
                    f"{article.id}: {decision.reason}",
                ],
            }
        )
        stories = [updated if item.id == best.id else item for item in stories]
        assigned[article.id] = best.id

    by_id = {article.id: article for article in articles}
    refreshed: list[Story] = []
    for story in stories:
        members = [by_id[article_id] for article_id in story.article_ids if article_id in by_id]
        if not members:
            refreshed.append(story)
            continue
        refreshed.append(
            story.model_copy(update={"independent_origin_count": independent_origin_count(members)})
        )
    return refreshed


def rank_stories(
    stories: list[Story],
    articles: dict[UUID, Article],
    sources: dict[str, Source],
    *,
    limit: int,
    now: datetime | None = None,
    attention: dict[UUID, float] | None = None,
) -> list[Story]:
    """freshness × independent origins × mean reliability × mean tier weight × attention.

    Reliability is the mean of the story's sources, so one low-rated source
    pulls the story down. Closed stories are left out.
    """
    moment = now or datetime.now(UTC)

    def score(story: Story) -> float:
        reliabilities: list[float] = []
        weights: list[float] = []
        for article_id in story.article_ids:
            article = articles.get(article_id)
            if article is None:
                continue
            source = sources.get(article.source_id)
            if source is None:
                weights.append(TIER_WEIGHT.get(article.tier_at_ingest, 0.4))
                continue
            reliabilities.append(source.reliability_score)
            weights.append(TIER_WEIGHT.get(source.tier, 0.4))
        reliability = sum(reliabilities) / len(reliabilities) if reliabilities else 1.0
        tier_weight = sum(weights) / len(weights) if weights else 1.0
        seen = (
            story.last_seen_at
            if story.last_seen_at.tzinfo
            else story.last_seen_at.replace(tzinfo=UTC)
        )
        age_hours = max(0.0, (moment - seen).total_seconds() / 3600)
        freshness = 1.0 / (1.0 + age_hours / 24.0)
        origins = max(story.independent_origin_count, 1)
        boost = 1.0
        if attention is not None:
            boost += max(0.0, attention.get(story.id, 0.0))
        return freshness * origins * reliability * tier_weight * boost

    ranked = sorted((item for item in stories if item.status == "active"), key=score, reverse=True)
    return ranked[:limit]
