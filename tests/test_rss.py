from __future__ import annotations

from datetime import UTC, datetime

from newsie.adapters.base import FetchContext
from newsie.adapters.rss import RssAdapter
from newsie.domain import AdapterKind, Source, SourceTier

SAMPLE_FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Test</title>
<item>
  <title>Hello Berlin</title>
  <link>https://example.test/rss/1</link>
  <description>Body text</description>
  <pubDate>Mon, 16 Nov 2026 10:00:00 +0100</pubDate>
</item>
</channel></rss>
"""


def test_rss_adapter_parses_feed() -> None:
    adapter = RssAdapter(fetch_text_fn=lambda _url: SAMPLE_FEED)
    source = Source(
        id="t",
        name="T",
        homepage_url="https://example.test",
        feed_url="https://example.test/feed.xml",
        adapter=AdapterKind.RSS,
        tier=SourceTier.REPORTING,
    )
    ctx = FetchContext(
        deadline=datetime.now(UTC),
        max_articles=10,
        lookback_hours=18,
    )
    items = adapter.fetch(source, ctx)
    assert len(items) == 1
    assert items[0].title == "Hello Berlin"
    assert "Body text" in items[0].content_text
