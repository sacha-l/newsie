"""RSS/Atom adapter — production path; network optional in tests via injection."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser  # type: ignore[import-untyped]

from newsie.adapters.base import FetchContext
from newsie.domain import ArticleCandidate, Source


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        dt = parsedate_to_datetime(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError, IndexError):
        return None


class RssAdapter:
    def __init__(self, fetch_text: Any | None = None) -> None:
        self._fetch_text = fetch_text

    def fetch(self, source: Source, ctx: FetchContext) -> list[ArticleCandidate]:
        if not source.feed_url:
            return []
        if self._fetch_text is not None:
            raw = self._fetch_text(source.feed_url)
            parsed = feedparser.parse(raw)
        else:
            parsed = feedparser.parse(source.feed_url)
        out: list[ArticleCandidate] = []
        for entry in parsed.entries[: ctx.max_articles]:
            link = getattr(entry, "link", None) or ""
            title = getattr(entry, "title", "") or ""
            summary = getattr(entry, "summary", None) or getattr(entry, "description", "") or ""
            if not link or not title:
                continue
            published = _parse_date(getattr(entry, "published", None))
            out.append(
                ArticleCandidate(
                    url=link,
                    title=title,
                    content_text=f"{title}\n\n{summary}".strip(),
                    published_at=published,
                    language=source.language,
                    raw_metadata={"adapter": "rss"},
                )
            )
        return out
