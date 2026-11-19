"""The checked-in 30-day capture: clustering and labels must replay."""

from __future__ import annotations

from datetime import datetime, timedelta

from newsie.corpus import (
    LOOKBACK_DAYS,
    labels_match,
    load_corpus_edition,
    load_payload,
    recorded_story_sets,
    replay_story_sets,
)
from newsie.evals.metrics import bcubed


def test_month_corpus_replays_clustering_and_labels() -> None:
    payload = load_payload()
    articles = payload["articles"]
    assert isinstance(articles, list)
    assert len(articles) >= 20
    sources = {row["source_id"] for row in articles if isinstance(row, dict)}
    assert len(sources) >= 5

    captured = datetime.fromisoformat(str(payload["captured_at"]))
    cutoff = captured - timedelta(hours=LOOKBACK_DAYS * 24)
    dated = 0
    for row in articles:
        assert isinstance(row, dict)
        assert row["origin_id"]
        assert len(row["embedding"]) == payload["embedding_dim"]
        published = row["published_at"]
        if published:
            dated += 1
            assert datetime.fromisoformat(str(published)) >= cutoff - timedelta(minutes=1)
    assert dated >= 10

    replayed = replay_story_sets(payload)
    recorded = recorded_story_sets(payload)
    predicted = {
        article_id: str(index) for index, group in enumerate(replayed) for article_id in group
    }
    gold = {article_id: str(index) for index, group in enumerate(recorded) for article_id in group}
    assert set(predicted) == set(gold)
    precision, recall = bcubed(predicted, gold)
    assert precision == 1.0
    assert recall == 1.0
    assert labels_match(payload)

    _store, draft = load_corpus_edition()
    assert draft.validation_status == "ok"
    assert draft.sentences
    assert all(sentence.citations for sentence in draft.sentences)
