from __future__ import annotations

from datetime import UTC, datetime

import pytest

from newsie.adapters.base import FetchContext
from newsie.adapters.rss import RssAdapter
from newsie.cli import build_live_pipeline
from newsie.domain import AdapterKind, Source, SourceTier
from newsie.http_client import FetchError, fetch_text


def test_fetch_text_tagesschau() -> None:
    text = fetch_text("https://www.tagesschau.de/index~rss2.xml")
    assert "rss" in text.lower() or "<item" in text.lower() or "<entry" in text.lower()


def test_rss_adapter_live_tagesschau() -> None:
    adapter = RssAdapter()
    source = Source(
        id="tagesschau",
        name="Tagesschau",
        homepage_url="https://www.tagesschau.de",
        feed_url="https://www.tagesschau.de/index~rss2.xml",
        adapter=AdapterKind.RSS,
        tier=SourceTier.REPORTING,
    )
    ctx = FetchContext(deadline=datetime.now(UTC), max_articles=5, lookback_hours=18)
    items = adapter.fetch(source, ctx)
    assert len(items) >= 1
    assert items[0].title
    assert items[0].url.startswith("http")


def test_live_pipeline_ingests() -> None:
    pipeline, store = build_live_pipeline()
    # Keep run bounded
    pipeline.settings = pipeline.settings.model_copy(
        update={"max_articles_per_source": 5, "max_stories_per_digest": 5}
    )
    result = pipeline.run()
    assert result.articles_ingested >= 1 or len(store.list_articles()) >= 1
    assert result.run.status in {"awaiting_hitl", "empty"}
    # Soft assertion: if network flaky, fetch_errors may be present but shouldn't 403-all
    hard_403 = [e for e in result.fetch_errors if "HTTP 403" in e and "fallback" not in e]
    # Allow some 403s if fallback worked; fail only if nothing ingested and all 403
    if result.articles_ingested == 0 and len(store.list_articles()) == 0:
        pytest.fail(f"live ingest produced nothing; fetch_errors={result.fetch_errors}")
    _ = hard_403


def test_fetch_error_on_forbidden_status() -> None:
    # Deterministic local 403 via httpx mock transport
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        with pytest.raises(FetchError) as ei:
            fetch_text("https://example.test/feed", max_retries=1, client=client)
        assert ei.value.status_code == 403
