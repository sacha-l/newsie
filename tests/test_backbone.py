"""Backbone rules: origins, labels, ranking, citations, stable stories."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from newsie.adapters.base import FetchContext
from newsie.adapters.fixture import FixtureAdapter
from newsie.adapters.rss import RssAdapter
from newsie.citations import validate_draft
from newsie.cli import build_live_pipeline
from newsie.cluster import assign_stories, rank_stories
from newsie.config import Settings
from newsie.domain import (
    AdapterKind,
    Article,
    ArticleEmbedding,
    CitationRef,
    Claim,
    ClaimType,
    DigestDraft,
    DigestSentence,
    Source,
    SourceTier,
    Spectrum,
    Story,
)
from newsie.embeddings import HashEmbeddingProvider
from newsie.evidence import label_claim, match_story, omitted_claims, passage_supports
from newsie.hitl import flag_sentence
from newsie.origins import assign_origins
from newsie.pipeline import DigestPipeline, seed_demo_sources
from newsie.signals import is_burst
from newsie.sources import load_live_sources
from newsie.store import MemoryStore
from newsie.urls import canonicalise_url


def _article(
    *,
    source_id: str,
    text: str,
    title: str = "Titel",
    tier: SourceTier = SourceTier.REPORTING,
    origin: str | None = None,
    partial: bool = False,
) -> Article:
    now = datetime.now(UTC)
    return Article(
        source_id=source_id,
        url=f"https://example.test/{source_id}/{abs(hash(text)) % 100000}",
        canonical_url=f"https://example.test/{source_id}",
        title=title,
        retrieved_at=now,
        published_at=now,
        content_text=text,
        full_text=text,
        content_hash=f"sha256:{source_id}:{text[:24]}",
        tier_at_ingest=tier,
        origin_id=origin,
        partial=partial,
    )


def _source(source_id: str, *, spectrum: Spectrum, group: str | None, tier: SourceTier) -> Source:
    return Source(
        id=source_id,
        name=source_id,
        homepage_url="https://example.test",
        spectrum=spectrum,
        publisher_group=group,
        tier=tier,
    )


def test_live_pipeline_does_not_fall_back_to_fixtures(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'live.db'}",
        demo_mode=False,
    )
    pipeline, _store = build_live_pipeline(settings)
    assert pipeline.adapter.allow_fixture_fallback is False


def test_seed_covers_every_spectrum_group() -> None:
    sources = load_live_sources()
    assert len(sources) >= 20
    spectra = {source.spectrum for source in sources}
    assert {
        Spectrum.CENTRE,
        Spectrum.CENTRE_LEFT,
        Spectrum.CENTRE_RIGHT,
        Spectrum.LEFT,
        Spectrum.REGIONAL,
        Spectrum.OFFICIAL,
        Spectrum.PARTY,
    } <= spectra
    assert any(source.publisher_group == "axel_springer" for source in sources)


def test_canonical_url_strips_tracking_and_follows_link() -> None:
    html = '<html><head><link rel="canonical" href="https://Example.TEST/story"></head></html>'
    assert (
        canonicalise_url("https://example.test/click?utm_source=rss&id=1", html)
        == "https://example.test/story"
    )
    assert (
        canonicalise_url("https://example.test/a?id=1&utm_medium=email&fbclid=x")
        == "https://example.test/a?id=1"
    )


def test_rss_lookback_drops_old_entries() -> None:
    feed = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
    <item>
      <title>Old</title>
      <link>https://example.test/old</link>
      <description>Old body text here</description>
      <pubDate>Mon, 01 Jan 2020 10:00:00 +0000</pubDate>
    </item>
    <item>
      <title>New</title>
      <link>https://example.test/new</link>
      <description>New body text here</description>
      <pubDate>Mon, 16 Nov 2026 18:00:00 +0000</pubDate>
    </item>
    </channel></rss>"""
    adapter = RssAdapter(fetch_text_fn=lambda _url: feed)
    source = Source(
        id="t",
        name="T",
        homepage_url="https://example.test",
        feed_url="https://example.test/feed.xml",
        adapter=AdapterKind.RSS,
        tier=SourceTier.REPORTING,
    )
    items = adapter.fetch(
        source,
        FetchContext(
            deadline=datetime(2026, 11, 16, 21, tzinfo=UTC), max_articles=10, lookback_hours=18
        ),
    )
    assert [item.title for item in items] == ["New"]


def test_publisher_group_and_agency_share_an_origin() -> None:
    left = _article(
        source_id="welt",
        text="Der Senat beschliesst die Reform morgen in Berlin mit allen Stimmen.",
    )
    right = _article(
        source_id="bild",
        text="Ein ganz anderer Text ueber Steuern und Haushalt ohne Bezug.",
    )
    wire_a = _article(
        source_id="tagesschau", text="Meldung (dpa) Der Kanzler reist nach Bruessel am Dienstag."
    )
    wire_b = _article(
        source_id="spiegel",
        text="Meldung (dpa) Der Kanzler reist nach Bruessel am Dienstag und spricht.",
    )
    sources = {
        "welt": _source(
            "welt", spectrum=Spectrum.CENTRE_RIGHT, group="axel_springer", tier=SourceTier.REPORTING
        ),
        "bild": _source(
            "bild", spectrum=Spectrum.CENTRE_RIGHT, group="axel_springer", tier=SourceTier.REPORTING
        ),
        "tagesschau": _source(
            "tagesschau", spectrum=Spectrum.CENTRE, group="ard", tier=SourceTier.REPORTING
        ),
        "spiegel": _source(
            "spiegel", spectrum=Spectrum.CENTRE_LEFT, group="spiegel", tier=SourceTier.REPORTING
        ),
    }
    updated = {
        article.source_id: article
        for article in assign_origins([left, right, wire_a, wire_b], sources)
    }
    assert updated["welt"].origin_id == updated["bild"].origin_id
    assert updated["welt"].origin_id == "group:axel_springer"
    assert updated["tagesschau"].origin_id == updated["spiegel"].origin_id
    assert updated["tagesschau"].agency_credit == "dpa"


def test_rank_uses_mean_reliability_freshness_and_tier() -> None:
    now = datetime.now(UTC)
    low = _article(source_id="low", text="aaa")
    high = _article(source_id="high", text="bbb")
    social = _article(source_id="social", text="ccc", tier=SourceTier.SOCIAL_SIGNAL)
    fresh = Story(
        first_seen_at=now,
        last_seen_at=now,
        title_hint="fresh",
        article_ids=[high.id],
        independent_origin_count=1,
        fingerprint="fresh",
    )
    stale = Story(
        first_seen_at=now - timedelta(days=3),
        last_seen_at=now - timedelta(days=2),
        title_hint="stale",
        article_ids=[high.id],
        independent_origin_count=1,
        fingerprint="stale",
    )
    mixed = Story(
        first_seen_at=now,
        last_seen_at=now,
        title_hint="mixed",
        article_ids=[low.id, high.id],
        independent_origin_count=2,
        fingerprint="mixed",
    )
    only_high = Story(
        first_seen_at=now,
        last_seen_at=now,
        title_hint="only",
        article_ids=[high.id],
        independent_origin_count=2,
        fingerprint="only",
    )
    social_story = Story(
        first_seen_at=now,
        last_seen_at=now,
        title_hint="social",
        article_ids=[social.id],
        independent_origin_count=1,
        fingerprint="social",
    )
    sources = {
        "low": _source(
            "low", spectrum=Spectrum.LEFT, group=None, tier=SourceTier.REPORTING
        ).model_copy(update={"reliability_score": 0.2}),
        "high": _source("high", spectrum=Spectrum.CENTRE, group=None, tier=SourceTier.REPORTING),
        "social": _source(
            "social", spectrum=Spectrum.CENTRE, group=None, tier=SourceTier.SOCIAL_SIGNAL
        ),
    }
    articles = {low.id: low, high.id: high, social.id: social}
    ranked = rank_stories([fresh, stale], articles, sources, limit=2, now=now)
    assert ranked[0].title_hint == "fresh"
    ranked_rel = rank_stories([mixed, only_high], articles, sources, limit=2, now=now)
    assert ranked_rel[0].title_hint == "only"
    ranked_tier = rank_stories([fresh, social_story], articles, sources, limit=2, now=now)
    assert ranked_tier[0].title_hint == "fresh"


def test_story_id_stays_when_an_article_joins() -> None:
    now = datetime.now(UTC)
    provider = HashEmbeddingProvider(dim=8)
    first = _article(source_id="a", text="Housing reform text shared across outlets today.")
    second = _article(source_id="b", text="Housing reform text shared across outlets today.")
    vectors = provider.embed(
        [f"{first.title}\n{first.content_text}", f"{second.title}\n{second.content_text}"]
    )
    emb = {
        first.id: ArticleEmbedding(
            article_id=first.id,
            embedding=vectors[0],
            embedding_model="hash",
            embedding_dim=8,
            embedded_at=now,
        )
    }
    opened = assign_stories([first], emb, [], threshold=0.8, window_hours=72, now=now)
    assert len(opened) == 1
    emb[second.id] = ArticleEmbedding(
        article_id=second.id,
        embedding=vectors[1],
        embedding_model="hash",
        embedding_dim=8,
        embedded_at=now,
    )
    again = assign_stories([first, second], emb, opened, threshold=0.8, window_hours=72, now=now)
    active = [story for story in again if story.status == "active"]
    assert len(active) == 1
    assert active[0].id == opened[0].id
    assert set(active[0].article_ids) == {first.id, second.id}


def test_housing_and_energy_fixtures_stay_apart() -> None:
    store = MemoryStore()
    seed_demo_sources(store)
    settings = Settings(demo_mode=True, embedding_dim=32, cluster_similarity_threshold=0.82)
    pipe = DigestPipeline(
        store,
        settings,
        adapter=FixtureAdapter(),
        embedder=HashEmbeddingProvider(dim=32),
    )
    pipe.run()
    by_id = {article.id: article for article in store.list_articles()}
    for story in store.list_stories():
        titles = " ".join(by_id[aid].title for aid in story.article_ids if aid in by_id)
        assert not ("Miet" in titles and "Energie" in titles)


def test_labels_follow_the_fixed_rule() -> None:
    corroborated, cross = label_claim(
        support_origins={"a", "b"},
        contradict_origins=set(),
        support_tiers=[SourceTier.REPORTING, SourceTier.REPORTING],
        support_spectra={"centre", "centre-right"},
    )
    assert corroborated.value == "corroborated"
    assert cross is True
    contested, _cross = label_claim(
        support_origins={"a"},
        contradict_origins={"b"},
        support_tiers=[SourceTier.REPORTING],
        support_spectra={"left"},
    )
    assert contested.value == "contested"
    single, _cross = label_claim(
        support_origins={"group:axel_springer"},
        contradict_origins=set(),
        support_tiers=[SourceTier.REPORTING, SourceTier.REPORTING],
        support_spectra={"centre-right"},
    )
    assert single.value == "single_origin"
    official, _cross = label_claim(
        support_origins={"gov"},
        contradict_origins=set(),
        support_tiers=[SourceTier.OFFICIAL],
        support_spectra={"official"},
    )
    assert official.value == "official_only"


def test_social_signal_does_not_corroborate() -> None:
    now = datetime.now(UTC)
    text = "Der Senat stimmt am Dienstag ueber die Mietreform ab und veroeffentlicht das Ergebnis."
    reporting = _article(source_id="tagesschau", text=text, origin="source:tagesschau")
    social = _article(
        source_id="x",
        text=text,
        origin="source:x",
        tier=SourceTier.SOCIAL_SIGNAL,
    )
    claim = Claim(
        article_id=reporting.id,
        text=text,
        type=ClaimType.FACT,
        span_start=0,
        span_end=len(text),
    )
    social_claim = claim.model_copy(update={"article_id": social.id, "id": uuid4()})
    story = Story(
        first_seen_at=now,
        last_seen_at=now,
        title_hint="t",
        article_ids=[reporting.id, social.id],
        fingerprint="s",
    )
    sources = {
        "tagesschau": _source(
            "tagesschau", spectrum=Spectrum.CENTRE, group=None, tier=SourceTier.REPORTING
        ),
        "x": _source("x", spectrum=Spectrum.CENTRE, group=None, tier=SourceTier.SOCIAL_SIGNAL),
    }
    vector = [1.0, 0.0]
    clusters, _evidence = match_story(
        story,
        [reporting, social],
        [claim, social_claim],
        [vector, vector],
        sources,
        threshold=0.9,
    )
    assert len(clusters) == 1
    assert clusters[0].label.value == "single_origin"
    assert clusters[0].origin_count == 1


def test_same_wording_from_two_origins_is_corroborated() -> None:
    now = datetime.now(UTC)
    text = "Der Senat stimmt am Dienstag ueber die Mietreform ab und veroeffentlicht das Ergebnis."
    left = _article(source_id="tagesschau", text=text, origin="source:tagesschau")
    right = _article(source_id="faz", text=text, origin="source:faz")
    claim = Claim(
        article_id=left.id, text=text, type=ClaimType.FACT, span_start=0, span_end=len(text)
    )
    other = claim.model_copy(update={"article_id": right.id, "id": uuid4()})
    story = Story(
        first_seen_at=now,
        last_seen_at=now,
        title_hint="t",
        article_ids=[left.id, right.id],
        fingerprint="s",
    )
    sources = {
        "tagesschau": _source(
            "tagesschau", spectrum=Spectrum.CENTRE, group=None, tier=SourceTier.REPORTING
        ),
        "faz": _source(
            "faz", spectrum=Spectrum.CENTRE_RIGHT, group=None, tier=SourceTier.REPORTING
        ),
    }
    vector = [1.0, 0.0]
    clusters, evidence = match_story(
        story,
        [left, right],
        [claim, other],
        [vector, vector],
        sources,
        threshold=0.9,
    )
    assert clusters[0].label.value == "corroborated"
    assert clusters[0].cross_spectrum is True
    missing = omitted_claims("zeit", [left, right], clusters, evidence)
    assert missing == []
    outsider = _article(
        source_id="zeit",
        text="Ein anderer Artikel ohne diesen Satz im sichtbaren Text.",
        origin="source:zeit",
    )
    missing = omitted_claims("zeit", [outsider], clusters, evidence)
    assert missing == clusters


def test_validator_requires_support_not_just_a_url() -> None:
    article = _article(source_id="s", text="Der Senat stimmt am Dienstag ueber die Mietreform ab.")
    article = article.model_copy(
        update={"url": "https://example.test/a", "canonical_url": "https://example.test/a"}
    )
    good = DigestSentence(
        section="spine",
        text=article.content_text,
        citations=[CitationRef(article_id=article.id, url=article.url, quote=article.content_text)],
    )
    bad = DigestSentence(
        section="spine",
        text="Die Opposition hat das Gesetz abgelehnt und eine neue Wahl gefordert.",
        citations=[CitationRef(article_id=article.id, url=article.url, quote=article.content_text)],
    )
    draft = DigestDraft(
        run_id=uuid4(),
        story_ids=[],
        spine_md="s",
        perspectives=[],
        divergence_md="d",
        events=[],
        citations=[article.url],
        sentences=[good],
        english_render_md="r",
        created_at=datetime.now(UTC),
    )
    assert validate_draft(draft, [article]).ok is True
    failed = validate_draft(draft.model_copy(update={"sentences": [bad]}), [article])
    assert failed.ok is False
    assert any("does not support" in error for error in failed.errors)
    assert passage_supports(article.content_text, article.content_text)


def test_citation_flag_lowers_reliability() -> None:
    store = MemoryStore()
    seed_demo_sources(store)
    settings = Settings(demo_mode=True, embedding_dim=32)
    pipe = DigestPipeline(
        store,
        settings,
        adapter=FixtureAdapter(),
        embedder=HashEmbeddingProvider(dim=32),
    )
    result = pipe.run()
    assert result.draft is not None
    sentence = next(item for item in result.draft.sentences if item.citations)
    source_id = next(
        article.source_id
        for article in store.list_articles()
        if article.id == sentence.citations[0].article_id
    )
    before = store.sources[source_id].reliability_score
    flag_sentence(store, result.draft.id, sentence.id)
    assert store.sources[source_id].reliability_score < before
    assert store.get_draft(result.draft.id).sentences
    flagged = next(
        item for item in store.get_draft(result.draft.id).sentences if item.id == sentence.id
    )
    assert flagged.owner_flag == "citation_wrong"


def test_burst_is_against_the_series_baseline() -> None:
    assert is_burst(10, 4) is True
    assert is_burst(5, 4) is False
    assert is_burst(1, 0) is True
