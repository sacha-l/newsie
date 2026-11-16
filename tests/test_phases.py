"""Exit checks that can run without a week of live articles or a human audit."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from newsie.adapters.base import FetchContext
from newsie.citations import validate_draft
from newsie.claims import heuristic_claims
from newsie.cluster import assign_stories
from newsie.config import Settings
from newsie.digest import build_draft_for_stories
from newsie.domain import (
    Article,
    ArticleCandidate,
    ArticleEmbedding,
    Claim,
    ClaimCluster,
    ClaimEvidence,
    ClaimType,
    EvidenceLabel,
    Source,
    Spectrum,
    Stance,
    Story,
)
from newsie.evals.label_swap import label_swap_ok, render_attributed
from newsie.evals.metrics import bcubed, beats_baseline, load_label_rows, wire_copy_rate
from newsie.llm import LLMProvider
from newsie.pipeline import DigestPipeline
from newsie.store import MemoryStore

FACT = "Berlin beschliesst einen Mietenstopp fuer Bestandswohnungen im kommenden Jahr."


def _source(source_id: str, spectrum: Spectrum) -> Source:
    return Source(
        id=source_id,
        name=source_id,
        homepage_url=f"https://example.test/{source_id}",
        spectrum=spectrum,
    )


def _article(source_id: str, text: str) -> Article:
    now = datetime.now(UTC)
    return Article(
        source_id=source_id,
        url=f"https://example.test/{source_id}/{abs(hash(text)) % 100000}",
        canonical_url=f"https://example.test/{source_id}/story",
        title="Mieten",
        retrieved_at=now,
        published_at=now,
        content_text=text,
        full_text=text,
        content_hash=f"sha256:{source_id}:{text[:32]}",
        tier_at_ingest=_source(source_id, Spectrum.CENTRE).tier,
    )


class _PairAdapter:
    def __init__(self, fact: str) -> None:
        self.fact = fact

    def fetch(self, source: Source, ctx: FetchContext) -> list[ArticleCandidate]:
        _ = ctx
        tail = f" Zusatz {source.id} " + (source.id + " ") * 30
        return [
            ArticleCandidate(
                url=f"https://example.test/{source.id}/mieten",
                title="Mieten",
                content_text=f"{self.fact} {tail}",
                published_at=datetime.now(UTC),
            )
        ]


class _SameFactEmbedder:
    dim = 8
    token_usage = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.token_usage = 0
        vectors: list[list[float]] = []
        for text in texts:
            if "Mietenstopp" in text:
                vectors.append([1.0] * self.dim)
            else:
                slot = len(vectors) % self.dim
                vector = [0.0] * self.dim
                vector[slot] = 1.0
                vectors.append(vector)
        return vectors


class _CitingModel:
    token_usage = 0

    def complete(self, system: str, user: str) -> str:
        _ = (system, user)
        self.token_usage = 4
        gloss = f"Berlin is pausing rents for existing flats. {FACT}"
        return json.dumps([{"text": gloss, "quote": FACT}])


def test_two_origins_pass_validation_end_to_end() -> None:
    store = MemoryStore()
    store.upsert_source(_source("tagesschau", Spectrum.CENTRE))
    store.upsert_source(_source("zeit", Spectrum.CENTRE_LEFT))
    settings = Settings(embedding_dim=8, fetch_full_text=False, database_url="sqlite://")
    pipeline = DigestPipeline(
        store,
        settings,
        adapter=_PairAdapter(FACT),
        embedder=_SameFactEmbedder(),
    )
    result = pipeline.run()
    assert result.draft is not None
    assert result.draft.validation_status == "ok"
    spine = [sentence for sentence in result.draft.sentences if sentence.section == "spine"]
    assert len(spine) == 1
    assert spine[0].text == FACT
    assert spine[0].citations[0].quote == FACT
    checked = validate_draft(result.draft, store.list_articles())
    assert checked.ok


def test_model_gloss_is_kept_only_when_the_quote_supports_it() -> None:
    article = _article("tagesschau", FACT)
    other = _article(
        "zeit",
        FACT + " Weitere Einzelheiten aus einer zweiten Redaktion folgen hier.",
    )
    claim = Claim(
        article_id=article.id,
        text=FACT,
        type=ClaimType.FACT,
        span_start=0,
        span_end=len(FACT),
    )
    other_claim = claim.model_copy(update={"article_id": other.id, "id": uuid4()})
    story = Story(
        first_seen_at=article.retrieved_at,
        last_seen_at=article.retrieved_at,
        title_hint="Mieten",
        article_ids=[article.id, other.id],
        fingerprint="mieten",
        independent_origin_count=2,
    )
    cluster = ClaimCluster(
        story_id=story.id,
        canonical_text=FACT,
        label=EvidenceLabel.CORROBORATED,
        origin_count=2,
    )
    citing: LLMProvider = _CitingModel()
    draft = build_draft_for_stories(
        run_id=story.id,
        stories=[story],
        articles_by_id={article.id: article, other.id: other},
        sources={
            "tagesschau": _source("tagesschau", Spectrum.CENTRE),
            "zeit": _source("zeit", Spectrum.CENTRE_LEFT),
        },
        settings=Settings(database_url="sqlite://"),
        llm=citing,
        claims=[claim, other_claim],
        clusters=[cluster],
    )
    spine = [sentence for sentence in draft.sentences if sentence.section == "spine"]
    assert spine[0].text.startswith("Berlin is pausing rents")
    assert FACT in spine[0].text
    assert validate_draft(draft, [article, other]).ok

    class _Unsupported:
        token_usage = 0

        def complete(self, system: str, user: str) -> str:
            _ = (system, user)
            return json.dumps([{"text": "A claim the quote does not contain.", "quote": FACT}])

    dropped = build_draft_for_stories(
        run_id=story.id,
        stories=[story],
        articles_by_id={article.id: article, other.id: other},
        sources={"tagesschau": _source("tagesschau", Spectrum.CENTRE)},
        settings=Settings(database_url="sqlite://"),
        llm=_Unsupported(),
        claims=[claim, other_claim],
        clusters=[cluster],
    )
    kept = [sentence for sentence in dropped.sentences if sentence.section == "spine"]
    assert kept[0].text == FACT


def test_omission_names_the_outlet_that_missed_a_corroborated_claim() -> None:
    now = datetime.now(UTC)
    carried_a = _article("tagesschau", FACT)
    carried_b = _article("zeit", FACT)
    silent = _article(
        "faz",
        "Ein anderer Absatz ohne den Mietenstopp und ohne dieselbe Behauptung.",
    )
    story = Story(
        first_seen_at=now,
        last_seen_at=now,
        title_hint="Mieten",
        article_ids=[carried_a.id, carried_b.id, silent.id],
        fingerprint="omit",
    )
    cluster = ClaimCluster(
        story_id=story.id,
        canonical_text=FACT,
        label=EvidenceLabel.CORROBORATED,
        origin_count=2,
    )
    claim = Claim(
        article_id=carried_a.id,
        text=FACT,
        type=ClaimType.FACT,
        span_start=0,
        span_end=len(FACT),
    )
    evidence = [
        ClaimEvidence(
            claim_cluster_id=cluster.id,
            article_id=carried_a.id,
            origin_id="source:tagesschau",
            stance=Stance.SUPPORTS,
            quote=FACT,
            judge_model="extraction",
        ),
        ClaimEvidence(
            claim_cluster_id=cluster.id,
            article_id=carried_b.id,
            origin_id="source:zeit",
            stance=Stance.SUPPORTS,
            quote=FACT,
            judge_model="extraction",
        ),
    ]
    draft = build_draft_for_stories(
        run_id=story.id,
        stories=[story],
        articles_by_id={carried_a.id: carried_a, carried_b.id: carried_b, silent.id: silent},
        sources={
            "tagesschau": _source("tagesschau", Spectrum.CENTRE),
            "zeit": _source("zeit", Spectrum.CENTRE_LEFT),
            "faz": _source("faz", Spectrum.CENTRE_RIGHT),
        },
        settings=Settings(database_url="sqlite://"),
        claims=[claim],
        clusters=[cluster],
        evidence=evidence,
    )
    assert f"faz did not carry: {FACT}" in draft.divergence_md


def test_label_swap_goes_through_the_view_template() -> None:
    spd = _article("spd", "Die SPD sagte die Mieten sollen in Berlin gedeckelt werden.")
    fdp = _article("fdp", "Die FDP sagte die Mieten sollen in Berlin gedeckelt werden.")
    left = heuristic_claims(spd)
    right = heuristic_claims(fdp)
    assert left[0].speaker == "SPD"
    assert right[0].speaker == "FDP"
    assert label_swap_ok(
        render_attributed(left[0].speaker or "", left[0].text),
        render_attributed(right[0].speaker or "", right[0].text),
        party_a="SPD",
        party_b="FDP",
    )


def test_nearest_story_hook_assigns_without_a_local_scan() -> None:
    now = datetime.now(UTC)
    first = _article("tagesschau", FACT)
    second = _article("zeit", "Ein ganz anderer Text ueber Energiepreise und Netzentgelte heute.")
    story = Story(
        first_seen_at=now,
        last_seen_at=now,
        title_hint="Mieten",
        article_ids=[first.id],
        centroid=[1.0, 0.0],
        window_start=now - timedelta(hours=1),
        window_end=now + timedelta(hours=72),
        fingerprint="open",
    )
    embedding = ArticleEmbedding(
        article_id=second.id,
        embedding=[0.0, 1.0],
        embedding_model="test",
        embedding_dim=2,
        embedded_at=now,
    )

    def nearest(vector: list[float], when: datetime) -> tuple[UUID, float] | None:
        _ = (vector, when)
        return story.id, 0.99

    assigned = assign_stories(
        [first, second],
        {second.id: embedding},
        [story],
        threshold=0.82,
        window_hours=72,
        now=now,
        nearest=nearest,
    )
    joined = next(item for item in assigned if item.id == story.id)
    assert second.id not in joined.article_ids
    opened = next(item for item in assigned if second.id in item.article_ids)
    assert opened.parent_story_id == story.id
    assert "rejected" in opened.assignment_notes[0]


def test_scores_and_constructed_label_file() -> None:
    assert bcubed({"a": "1", "b": "1", "c": "2"}, {"a": "1", "b": "1", "c": "2"}) == (1.0, 1.0)
    precision, recall = bcubed({"a": "1", "b": "1", "c": "1"}, {"a": "1", "b": "1", "c": "2"})
    assert abs(precision - (5 / 9)) < 1e-9
    assert recall == 1.0
    now = datetime.now(UTC)
    copied_a = _article("tagesschau", FACT)
    copied_b = _article("zeit", FACT)
    copied_a.origin_id = "agency:dpa"
    copied_b.origin_id = "agency:dpa"
    story = Story(
        first_seen_at=now,
        last_seen_at=now,
        title_hint="wire",
        article_ids=[copied_a.id, copied_b.id],
        fingerprint="wire",
    )
    assert wire_copy_rate([story], {copied_a.id: copied_a, copied_b.id: copied_b}) == 1.0
    rows = load_label_rows(
        Path(__file__).resolve().parents[1] / "data" / "gold" / "label_baseline.json"
    )
    assert beats_baseline(rows)


def test_sqlite_nearest_story_does_not_query() -> None:
    from newsie.sql_store import SqlStore

    store = SqlStore("sqlite://")
    assert store.nearest_story([0.1, 0.2], datetime.now(UTC)) is None
