"""RSS/Atom adapter — real HTTP fetch with 403-resistant headers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser  # type: ignore[import-untyped]

from newsie.adapters.base import FetchContext
from newsie.domain import ArticleCandidate, Source
from newsie.http_client import FetchError, fetch_text

FetchFn = Callable[[str], str]


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
    def __init__(self, fetch_text_fn: FetchFn | None = None) -> None:
        self._fetch_text = fetch_text_fn or fetch_text

    def fetch(self, source: Source, ctx: FetchContext) -> list[ArticleCandidate]:
        if not source.feed_url:
            return []
        try:
            raw = self._fetch_text(source.feed_url)
        except FetchError:
            raise
        parsed = feedparser.parse(raw)
        out: list[ArticleCandidate] = []
        for entry in parsed.entries[: ctx.max_articles]:
            link = getattr(entry, "link", None) or ""
            title = getattr(entry, "title", "") or ""
            summary = getattr(entry, "summary", None) or getattr(entry, "description", "") or ""
            if not link or not title:
                continue
            published = _parse_date(getattr(entry, "published", None)) or _parse_date(
                getattr(entry, "updated", None)
            )
            out.append(
                ArticleCandidate(
                    url=link,
                    title=title,
                    content_text=f"{title}\n\n{summary}".strip(),
                    published_at=published,
                    language=source.language,
                    raw_metadata={"adapter": "rss", "feed_url": source.feed_url},
                )
            )
        return out
