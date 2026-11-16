"""Per-source adapter selection with fixture fallback."""

from __future__ import annotations

from newsie.adapters.base import FetchContext, SourceAdapter
from newsie.adapters.fixture import FixtureAdapter
from newsie.adapters.http_adapter import HttpAdapter
from newsie.adapters.rss import RssAdapter
from newsie.domain import AdapterKind, ArticleCandidate, Source
from newsie.http_client import FetchError


class AdapterRouter:
    """Routes each source to its adapter; records fetch errors without aborting the run."""

    def __init__(self, *, allow_fixture_fallback: bool = True) -> None:
        self.rss = RssAdapter()
        self.http = HttpAdapter()
        self.fixture = FixtureAdapter()
        self.allow_fixture_fallback = allow_fixture_fallback
        self.errors: list[str] = []

    def _pick(self, source: Source) -> SourceAdapter:
        if source.adapter == AdapterKind.FIXTURE:
            return self.fixture
        if source.adapter == AdapterKind.HTTP:
            return self.http
        if source.adapter == AdapterKind.RSS:
            return self.rss
        # playwright/agent not implemented as default fetchers here
        return self.rss if source.feed_url else self.http

    def fetch(self, source: Source, ctx: FetchContext) -> list[ArticleCandidate]:
        adapter = self._pick(source)
        try:
            items = adapter.fetch(source, ctx)
            if items:
                return items
            if self.allow_fixture_fallback and source.id in {"tagesschau", "rbb", "zeit"}:
                self.errors.append(f"{source.id}: empty live fetch; fixture fallback")
                return self.fixture.fetch(source, ctx)
            return []
        except FetchError as exc:
            msg = f"{source.id}: {exc}"
            self.errors.append(msg)
            if self.allow_fixture_fallback and source.adapter != AdapterKind.FIXTURE:
                # Only fallback when source has fixture data
                fb = self.fixture.fetch(source, ctx)
                if fb:
                    self.errors.append(f"{source.id}: using fixture fallback after fetch error")
                    return fb
            return []
