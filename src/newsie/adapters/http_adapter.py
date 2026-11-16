"""Fetch one article page and extract the visible text."""

from __future__ import annotations

from newsie.adapters.base import FetchContext
from newsie.adapters.extract import extract_article
from newsie.domain import ArticleCandidate, Source
from newsie.http_client import FetchError, fetch_text
from newsie.urls import canonicalise_url


def fetch_article_page(
    url: str, *, rate_limit_per_hour: int | None = None
) -> dict[str, object] | None:
    """Download one article. None when the fetch fails or no text is visible."""
    try:
        html = fetch_text(
            url,
            headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
            rate_limit_per_hour=rate_limit_per_hour,
        )
    except FetchError:
        return None
    title, text, method, partial = extract_article(html)
    if not text:
        return None
    return {
        "title": title,
        "text": text,
        "method": method,
        "partial": partial,
        "canonical_url": canonicalise_url(url, html),
        "html": html,
    }


class HttpAdapter:
    """Fetch the source page when the source itself is a single document, not a feed."""

    def fetch(self, source: Source, ctx: FetchContext) -> list[ArticleCandidate]:
        _ = ctx
        url = source.feed_url or source.homepage_url
        if not url:
            return []
        page = fetch_article_page(url, rate_limit_per_hour=source.rate_limit_per_hour)
        if page is None:
            return []
        title = str(page["title"] or source.name)
        text = str(page["text"])
        return [
            ArticleCandidate(
                url=str(page["canonical_url"]),
                title=title,
                content_text=text,
                language=source.language,
                raw_metadata={
                    "adapter": "http",
                    "extraction_method": page["method"],
                    "partial": page["partial"],
                },
            )
        ]
