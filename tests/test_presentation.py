from __future__ import annotations

from newsie.cli import build_demo_pipeline
from newsie.web.presentation import build_digest_view


def test_build_digest_view_has_sections_and_trending() -> None:
    pipeline, store = build_demo_pipeline()
    result = pipeline.run()
    assert result.draft is not None
    view = build_digest_view(store, result.draft)
    assert view is not None
    assert view.sections
    assert view.trending
    assert any(s.article_count > 0 for s in view.trending)