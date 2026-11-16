from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from newsie.adapters.fixture import FixtureAdapter
from newsie.citations import validate_draft
from newsie.config import Settings
from newsie.domain import DigestDraft, PerspectiveBrief, PoliticalEvent
from newsie.guardrails import KillSwitch
from newsie.hitl import HitlError, approve_draft
from newsie.pipeline import DigestPipeline, seed_demo_sources
from newsie.store import MemoryStore


def _settings() -> Settings:
    return Settings(
        demo_mode=True,
        max_stories_per_digest=5,
        cluster_similarity_threshold=0.5,
        embedding_dim=1536,
        embedding_model="text-embedding-3-small",
    )


def test_demo_pipeline_produces_validated_draft() -> None:
    store = MemoryStore()
    seed_demo_sources(store)
    pipe = DigestPipeline(store, _settings(), adapter=FixtureAdapter())
    result = pipe.run()
    assert result.run.status == "awaiting_hitl"
    assert result.draft is not None
    assert result.draft.validation_status == "ok"
    assert result.articles_ingested >= 3
    assert result.stories >= 1
    assert "Factual spine" in result.draft.english_render_md


def test_ingest_is_idempotent() -> None:
    store = MemoryStore()
    seed_demo_sources(store)
    pipe = DigestPipeline(store, _settings(), adapter=FixtureAdapter())
    n1 = pipe.ingest()
    n2 = pipe.ingest()
    assert n1 > 0
    assert n2 == 0
    assert len(store.list_articles()) == n1


def test_kill_switch_aborts_pipeline() -> None:
    store = MemoryStore()
    seed_demo_sources(store)
    ks = KillSwitch(engaged=True, reason="stop")
    pipe = DigestPipeline(store, _settings(), adapter=FixtureAdapter(), kill_switch=ks)
    result = pipe.run()
    assert result.run.status == "aborted"
    assert result.run.kill_switch_hit is True


def test_hitl_required_and_idempotent_approve() -> None:
    store = MemoryStore()
    seed_demo_sources(store)
    pipe = DigestPipeline(store, _settings(), adapter=FixtureAdapter())
    result = pipe.run()
    assert result.draft is not None
    assert len(store.publications) == 0
    pub1 = approve_draft(store, result.draft.id, kill_switch=pipe.kill_switch)
    pub2 = approve_draft(store, result.draft.id, kill_switch=pipe.kill_switch)
    assert pub1.id == pub2.id
    assert len(store.publications) == 1


def test_cannot_approve_invalid_draft() -> None:
    store = MemoryStore()
    draft = DigestDraft(
        run_id=uuid4(),
        story_ids=[],
        spine_md="x",
        perspectives=[],
        divergence_md="y",
        events=[],
        citations=[],
        english_render_md="z",
        validation_status="fail:bad",
        created_at=datetime.now(UTC),
    )
    store.save_draft(draft)
    with pytest.raises(HitlError):
        approve_draft(store, draft.id, kill_switch=KillSwitch())


def test_citation_validator_rejects_fabricated_url() -> None:
    from newsie.domain import Article, SourceTier

    articles = [
        Article(
            source_id="s",
            url="https://example.test/a",
            canonical_url="https://example.test/a",
            title="t",
            retrieved_at=datetime.now(UTC),
            content_text="body",
            content_hash="sha256:x",
            tier_at_ingest=SourceTier.REPORTING,
        )
    ]
    draft = DigestDraft(
        run_id=uuid4(),
        story_ids=[],
        spine_md="s",
        perspectives=[
            PerspectiveBrief(party_label="SPD", summary="s", citation_urls=["https://evil.test/x"])
        ],
        divergence_md="d",
        events=[PoliticalEvent(title="e", citation_urls=[])],
        citations=["https://evil.test/x"],
        english_render_md="r",
        validation_status="pending",
        created_at=datetime.now(UTC),
    )
    result = validate_draft(draft, articles)
    assert result.ok is False


def test_label_swap_perspectives_track_party() -> None:
    store = MemoryStore()
    seed_demo_sources(store)
    pipe = DigestPipeline(store, _settings(), adapter=FixtureAdapter())
    result = pipe.run()
    assert result.draft is not None
    labels = [p.party_label for p in result.draft.perspectives]
    assert "SPD" in labels and "CDU/CSU" in labels
    spd = next(p for p in result.draft.perspectives if p.party_label == "SPD")
    assert "SPD" in spd.summary


def test_ratings_update_reliability() -> None:
    store = MemoryStore()
    seed_demo_sources(store)
    before = store.sources["tagesschau"].reliability_score
    store.rate_source("tagesschau", 0.5)
    after = store.sources["tagesschau"].reliability_score
    assert after != before
    assert after == 0.5
