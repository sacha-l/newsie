"""Event identity is not embedding similarity, and the brief keeps uncertainty visible."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from newsie.citations import validate_draft
from newsie.claims import classify_clause
from newsie.cluster import assign_stories
from newsie.domain import (
    Article,
    ArticleEmbedding,
    CitationRef,
    ClaimType,
    DigestDraft,
    DigestSentence,
    EvidenceLabel,
    Story,
)
from newsie.events import build_event_board, same_event_text
from newsie.evidence import assessment_of, support_relation


def _article(source_id: str, title: str, text: str) -> Article:
    now = datetime.now(UTC)
    return Article(
        source_id=source_id,
        url=f"https://example.test/{source_id}",
        canonical_url=f"https://example.test/{source_id}",
        title=title,
        retrieved_at=now,
        published_at=now,
        content_text=text,
        full_text=text,
        content_hash=f"sha256:{source_id}:{title}",
        tier_at_ingest="reporting",
    )


def test_same_wording_joins_and_records_why() -> None:
    now = datetime.now(UTC)
    text = "Berlin beschliesst einen Mietenstopp fuer Bestandswohnungen im kommenden Jahr."
    first = _article("tagesschau", "Mietenstopp in Berlin", text)
    second = _article("zeit", "Mietenstopp fuer Bestandswohnungen", text)
    vector = [1.0, 0.0]
    stories = assign_stories(
        [first],
        {
            first.id: ArticleEmbedding(
                article_id=first.id,
                embedding=vector,
                embedding_model="test",
                embedding_dim=2,
                embedded_at=now,
            )
        },
        [],
        threshold=0.8,
        window_hours=72,
        now=now,
    )
    again = assign_stories(
        [first, second],
        {
            first.id: ArticleEmbedding(
                article_id=first.id,
                embedding=vector,
                embedding_model="test",
                embedding_dim=2,
                embedded_at=now,
            ),
            second.id: ArticleEmbedding(
                article_id=second.id,
                embedding=vector,
                embedding_model="test",
                embedding_dim=2,
                embedded_at=now,
            ),
        },
        stories,
        threshold=0.8,
        window_hours=72,
        now=now,
    )
    active = [story for story in again if second.id in story.article_ids]
    assert len(active) == 1
    assert first.id in active[0].article_ids
    assert "same occurrence" in active[0].assignment_notes[-1]


def test_similar_embedding_does_not_merge_a_different_occurrence() -> None:
    now = datetime.now(UTC)
    rent = _article(
        "tagesschau",
        "Mietenstopp",
        "Berlin beschliesst einen Mietenstopp fuer Bestandswohnungen.",
    )
    energy = _article(
        "zeit",
        "Netzentgelte",
        "Energiepreise und Netzentgelte steigen im kommenden Winter.",
    )
    story = Story(
        first_seen_at=now,
        last_seen_at=now,
        title_hint=rent.title,
        article_ids=[rent.id],
        centroid=[1.0, 0.0],
        window_start=now - timedelta(hours=1),
        window_end=now + timedelta(hours=72),
        fingerprint="rent",
    )

    def nearest(vector: list[float], when: datetime) -> tuple[UUID, float] | None:
        _ = (vector, when)
        return story.id, 0.99

    assigned = assign_stories(
        [rent, energy],
        {
            energy.id: ArticleEmbedding(
                article_id=energy.id,
                embedding=[1.0, 0.0],
                embedding_model="test",
                embedding_dim=2,
                embedded_at=now,
            )
        },
        [story],
        threshold=0.8,
        window_hours=72,
        now=now,
        nearest=nearest,
    )
    kept = next(item for item in assigned if item.id == story.id)
    assert energy.id not in kept.article_ids
    opened = next(item for item in assigned if energy.id in item.article_ids)
    assert opened.parent_story_id == story.id


def test_constructed_event_pairs_match_the_occurrence_rule() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "gold" / "event_pairs.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert rows
    for row in rows:
        assert same_event_text(row["left"], row["right"]) is row["same_event"]


def test_claim_kinds_and_support_relations() -> None:
    assert classify_clause("Die Opposition wirft dem Senat einen Vorwurf vor heute.") is (
        ClaimType.ALLEGATION
    )
    assert classify_clause("Die Mieten koennten im naechsten Jahr weiter steigen.") is (
        ClaimType.PREDICTION
    )
    assert assessment_of(EvidenceLabel.CORROBORATED).value == "supported"
    assert assessment_of(EvidenceLabel.SINGLE_ORIGIN).value == "unverified"
    assert assessment_of(EvidenceLabel.CONTESTED).value == "disputed"
    quote = "Berlin beschliesst einen Mietenstopp fuer Bestandswohnungen."
    assert support_relation(f"Accounts differ on: {quote}", quote).value == "direct"
    assert support_relation("A different subject entirely here.", quote).value == "none"


def test_context_alone_fails_validation_and_the_board_names_the_sample() -> None:
    article = _article("tagesschau", "Mietenstopp", "Berlin beschliesst einen Mietenstopp.")
    draft = DigestDraft(
        run_id=article.id,
        story_ids=[],
        spine_md="",
        perspectives=[],
        divergence_md="",
        events=[],
        sentences=[
            DigestSentence(
                section="spine",
                text="The city discussed transport fares yesterday afternoon.",
                citations=[
                    CitationRef(
                        article_id=article.id,
                        url=article.url,
                        quote="Berlin beschliesst einen Mietenstopp.",
                    )
                ],
            )
        ],
        english_render_md="",
        created_at=datetime.now(UTC),
    )
    checked = validate_draft(draft, [article])
    assert not checked.ok
    story = Story(
        first_seen_at=article.retrieved_at,
        last_seen_at=article.retrieved_at,
        title_hint=article.title,
        article_ids=[article.id],
        fingerprint="one",
        assignment_notes=[f"{article.id}: opened as a new event"],
    )
    board = build_event_board(
        stories=[story],
        articles=[article],
        sources={},
        draft=None,
    )
    assert "collected sample" in board.sample_note
    assert board.rows[0].title == "Mietenstopp"
    assert board.rows[0].notes
