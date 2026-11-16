"""Attention from raw posts. A burst is against the topic's own baseline."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from newsie.domain import SocialPost, Story, StoryAttention, TrendPoint
from newsie.signals import is_burst


def build_trends(
    posts: list[SocialPost],
    previous: list[TrendPoint],
    *,
    now: datetime | None = None,
) -> list[TrendPoint]:
    moment = now or datetime.now(UTC)
    baselines = {point.topic: float(point.post_count) for point in previous}
    counts = Counter(post.topic for post in posts if post.topic)
    points: list[TrendPoint] = []
    for topic, count in sorted(counts.items()):
        baseline = baselines.get(topic, 0.0)
        points.append(
            TrendPoint(
                topic=topic,
                window_start=moment,
                post_count=count,
                baseline=baseline,
                burst=is_burst(float(count), baseline),
            )
        )
    return points


def attach_attention(stories: list[Story], points: list[TrendPoint]) -> list[StoryAttention]:
    """Link a bursting topic to a story when the topic words appear in the title."""
    linked: list[StoryAttention] = []
    for story in stories:
        title = story.title_hint.lower()
        for point in points:
            words = [word for word in point.topic.lower().split() if len(word) > 2]
            if not words or not all(word in title for word in words):
                continue
            linked.append(
                StoryAttention(
                    story_id=story.id,
                    topic=point.topic,
                    attention=float(point.post_count),
                    marker="trending on X" if point.burst else "",
                )
            )
            break
    return linked


def circulating_topics(posts: list[SocialPost], corroborated_text: list[str]) -> list[str]:
    """Topics in posts that no corroborated claim carries. Attention, not evidence."""
    covered = "\n".join(corroborated_text).lower()
    topics: list[str] = []
    for post in posts:
        topic = post.topic.strip()
        if not topic or topic.lower() in covered or topic in topics:
            continue
        topics.append(topic)
    return topics
