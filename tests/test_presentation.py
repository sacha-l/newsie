from __future__ import annotations

from newsie.cli import build_demo_pipeline
from newsie.domain import Story
from newsie.web.presentation import build_digest_view


def _cards(view):
    return [story for section in view.sections for story in section.stories]


def test_build_digest_view_has_sections_and_trending() -> None:
    pipeline, store = build_demo_pipeline()
    result = pipeline.run()
    assert result.draft is not None
    view = build_digest_view(store, result.draft)
    assert view is not None
    assert view.sections
    assert view.trending
    assert any(s.article_count > 0 for s in view.trending)
    cards = _cards(view)
    assert cards
    leads = [card for card in cards if card.is_lead]
    assert len(leads) == 1
    assert leads[0].corroboration == max(card.corroboration for card in cards)
    by_id = {story.id: story for story in store.list_stories()}
    assert leads[0].headline == by_id[result.draft.story_ids[0]].title_hint
    for card in cards:
        assert card.items
        assert card.dek
        assert card.meanings
        assert len(card.meanings) == len(card.items)
        assert card.differ_line
        if len(card.items) >= 2:
            assert card.items[0].source_name in card.differ_line
            assert card.items[0].title in card.differ_line
        else:
            assert "single-sourced" in card.differ_line


def test_corroborated_card_has_sources_meaning_and_differ_line() -> None:
    """Demo articles stay separate under hash embeddings; pin two into one cluster."""
    pipeline, store = build_demo_pipeline()
    result = pipeline.run()
    assert result.draft is not None
    by_source: dict[str, object] = {}
    for article in store.list_articles():
        by_source.setdefault(article.source_id, article)
    left = by_source["tagesschau"]
    right = by_source["rbb"]
    story = Story(
        fingerprint="corroborated-demo",
        first_seen_at=left.retrieved_at,
        last_seen_at=left.retrieved_at,
        corroboration_score=2.0,
        title_hint=left.title,
        article_ids=[left.id, right.id],
    )
    store.save_story(story)
    draft = result.draft.model_copy(update={"story_ids": [story.id]})
    view = build_digest_view(store, draft)
    assert view is not None
    cards = _cards(view)
    assert len(cards) == 1
    card = cards[0]
    assert card.is_lead
    assert len(card.items) >= 2
    assert card.outlet_count >= 2
    assert card.dek == left.title
    assert card.meanings
    joined = " ".join(note.sentence for note in card.meanings)
    assert "Tagesschau" in joined
    assert "institutional/mainstream framing" in joined
    assert "rbb" in joined
    assert "Berlin/local framing" in joined
    assert "Tagesschau" in card.differ_line
    assert "rbb" in card.differ_line
    assert left.title in card.differ_line
    assert right.title in card.differ_line
    assert "single-sourced" not in card.differ_line
