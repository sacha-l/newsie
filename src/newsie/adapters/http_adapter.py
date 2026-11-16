"""HTTP page adapter — fetch article HTML and extract readable text."""

from __future__ import annotations

from bs4 import BeautifulSoup

from newsie.adapters.base import FetchContext
from newsie.domain import ArticleCandidate, Source
from newsie.http_client import FetchError, fetch_text


def extract_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "aside"]):
        tag.decompose()
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True) or title
    # Prefer article/main bodies when present
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = root.get_text("\n", strip=True) if root else ""
    # Bound size for embeddings/LLM
    if len(text) > 12_000:
        text = text[:12_000]
    return title, text


class HttpAdapter:
    """Fetch a single page URL listed as source.feed_url (or homepage)."""

    def fetch(self, source: Source, ctx: FetchContext) -> list[ArticleCandidate]:
        url = source.feed_url or source.homepage_url
        if not url:
            return []
        try:
            html = fetch_text(url, headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
        except FetchError:
            raise
        title, text = extract_text(html)
        if not text:
            return []
        return [
            ArticleCandidate(
                url=url,
                title=title or source.name,
                content_text=text,
                language=source.language,
                raw_metadata={"adapter": "http"},
            )
        ]
