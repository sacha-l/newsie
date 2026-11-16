"""Raw social posts. Text is stored and never executed, and it is not evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from newsie.domain import SocialPost


def posts_from_records(records: list[dict[str, Any]]) -> list[SocialPost]:
    """Build posts from API records. Missing text is skipped."""
    posts: list[SocialPost] = []
    for record in records:
        text = str(record.get("text") or "").strip()
        external_id = str(record.get("id") or "").strip()
        if not text or not external_id:
            continue
        retrieved = record.get("retrieved_at")
        when = retrieved if isinstance(retrieved, datetime) else datetime.now(UTC)
        posts.append(
            SocialPost(
                platform=str(record.get("platform") or "x"),
                external_id=external_id,
                author_handle=str(record.get("author_handle") or ""),
                text=text,
                reach=int(record.get("reach") or 0),
                topic=str(record.get("topic") or "").strip(),
                retrieved_at=when,
            )
        )
    return posts
