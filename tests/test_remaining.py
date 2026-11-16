"""The remaining backbone details: persistence, attention, scores, and Grok."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from newsie.adapters.extract import extract_article
from newsie.adapters.social_x import posts_from_records
from newsie.cluster import rank_stories
from newsie.config import Settings
from newsie.digest import build_draft_for_stories
from newsie.domain import (
    Article,
    SocialPost,
    Source,
    SourceTier,
    Story,
)
from newsie.evals.metrics import citation_support_rate, extraction_scores, macro_f1, pair_scores
from newsie.hitl import flag_sentence
from newsie.llm import GrokProvider, call_tokens
from newsie.origins import assign_origins
from newsie.pipeline import DigestPipeline
from newsie.search import keyword_score
from newsie.signals import conformal_threshold, least_sure, origin_accuracy, outlet_axis
from newsie.sql_store import SqlStore
from newsie.store import MemoryStore
from newsie.trends import attach_attention, build_trends, circulating_topics
from newsie.web.app import app


def _article(
    source_id: str,
    title: str,
    text: str,
    tier: SourceTier = SourceTier.REPORTING,
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
    )


def test_claim_vectors_round_trip_and_drop(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SqlStore(f"sqlite:///{tmp_path / 'claims.db'}")
    story_id = uuid4()
    claim_id = uuid4()
    store.save_claim_vector(claim_id, story_id, [0.25, 0.5])
    assert store.list_claim_vectors(story_id)[claim_id] == [0.25, 0.5]
    store.drop_claim_embeddings(story_id)
    assert store.list_claim_vectors(story_id) == {}


def test_digest_sums_each_model_call() -> None:
    class Meter:
        token_usage = 0
        last_call_tokens = 0

        def complete(self, system: str, user: str) -> str:
            _ = (system, user)
            self.last_call_tokens = 5
            self.token_usage += 5
            return "stub"

    now = datetime.now(UTC)
    stories = [
        Story(
            first_seen_at=now,
            last_seen_at=now,
            title_hint=title,
            fingerprint=title,
        )
        for title in ("One", "Two")
    ]
    model = Meter()
    spent: list[int] = []
    build_draft_for_stories(
        run_id=uuid4(),
        stories=stories,
        articles_by_id={},
        sources={},
        settings=Settings(database_url="sqlite://"),
        llm=model,  # type: ignore[arg-type]
        token_sink=spent,
    )
    assert call_tokens(model) == 5
    assert spent == [10]


def test_extractor_uses_trafilatura() -> None:
    html = (
        "<html><head><title>Mietenstopp in Berlin</title></head><body><article>"
        "<p>Berlin beschliesst einen Mietenstopp fuer Bestandswohnungen.</p>"
        "</article></body></html>"
    )
    title, text, method, partial = extract_article(html)
    assert "Mietenstopp" in text
    assert method == "trafilatura"
    assert partial is False
    assert title


def test_title_trigram_unions_long_headlines() -> None:
    title = "Berlin beschliesst den Mietenstopp fuer Wohnungen"
    left = _article(
        "tagesschau",
        title,
        "Ein langer eigener Text ueber das Verfahren im Senat heute Abend.",
    )
    right = _article(
        "zeit",
        title,
        "Eine andere Recherche ueber die Abstimmung und die Gegenstimmen im Haus.",
    )
    sources = {
        "tagesschau": Source(
            id="tagesschau", name="tagesschau", homepage_url="https://example.test"
        ),
        "zeit": Source(id="zeit", name="Zeit", homepage_url="https://example.test"),
    }
    updated = assign_origins([left, right], sources)
    assert updated[0].origin_id == updated[1].origin_id
    assert updated[0].origin_id is not None
    assert updated[0].origin_id.startswith("dup:")


def test_attention_reorders_rank_and_social_is_not_an_origin() -> None:
    now = datetime.now(UTC)
    quiet = Story(
        first_seen_at=now,
        last_seen_at=now,
        title_hint="Ruhig",
        article_ids=[],
        independent_origin_count=2,
        fingerprint="quiet",
    )
    loud = Story(
        first_seen_at=now,
        last_seen_at=now,
        title_hint="Mietenstopp Berlin",
        article_ids=[],
        independent_origin_count=1,
        fingerprint="loud",
    )
    ranked = rank_stories(
        [quiet, loud],
        {},
        {},
        limit=2,
        attention={loud.id: 4.0},
    )
    assert ranked[0].id == loud.id
    posts = posts_from_records(
        [{"id": "1", "text": "look", "topic": "Mietenstopp", "author_handle": "a", "reach": 10}]
    )
    points = build_trends(posts, [])
    assert points[0].burst is True
    linked = attach_attention([loud], points)
    assert linked[0].marker == "trending on X"
    assert circulating_topics(posts, ["something else"]) == ["Mietenstopp"]
    social = _article("x", "Post", "look", SourceTier.SOCIAL_SIGNAL)
    reporting = _article("tagesschau", "Titel", "Ein eigener Bericht ohne denselben Wortlaut hier.")
    social.origin_id = "source:x"
    reporting.origin_id = "source:tagesschau"
    from newsie.cluster import independent_origin_count

    assert independent_origin_count([social, reporting]) == 1


def test_learned_signals_and_stage_scores() -> None:
    axis = outlet_axis([[1.0, 0.0], [0.0, 1.0]])
    assert len(axis) == 2
    assert abs(abs(axis[0]) - abs(axis[1])) < 1e-6
    assert origin_accuracy({"agency:dpa": [True, False]}) == {"agency:dpa": 0.5}
    assert conformal_threshold([0.1, 0.2, 0.4, 0.8], alpha=0.25) >= 0.4
    assert least_sure([("a", 0.9), ("b", 0.1)], 1) == [("b", 0.1)]
    assert pair_scores({("a", "b")}, {("b", "a")}) == (1.0, 1.0)
    assert extraction_scores(["Berlin senkt die Mieten"], ["Berlin senkt die Mieten"]) == (1.0, 1.0)
    score = macro_f1(
        ["supports", "silent"],
        ["supports", "contradicts"],
        ("supports", "contradicts", "silent"),
    )
    assert 0.0 < score < 1.0
    assert citation_support_rate(3, 4) == 0.75
    assert keyword_score("Mietenstopp Berlin", "Berlin plant einen Mietenstopp") == 1.0


def test_flag_events_are_appended() -> None:
    store = MemoryStore()
    now = datetime.now(UTC)
    from newsie.domain import DigestDraft, DigestSentence

    sentence = DigestSentence(draft_id=uuid4(), section="spine", text="A cited line")
    draft = DigestDraft(
        id=sentence.draft_id or uuid4(),
        run_id=uuid4(),
        story_ids=[],
        spine_md="",
        perspectives=[],
        divergence_md="",
        events=[],
        citations=[],
        sentences=[sentence],
        english_render_md="",
        validation_status="ok",
        created_at=now,
    )
    store.save_draft(draft)
    flag_sentence(store, draft.id, sentence.id, "citation_wrong")
    flag_sentence(store, draft.id, sentence.id, "citation_wrong")
    assert len(store.list_flag_events(sentence.id)) == 2


def test_pipeline_acks_attention_and_embeds_claims_at_512() -> None:
    store = MemoryStore()
    store.upsert_source(
        Source(id="tagesschau", name="tagesschau", homepage_url="https://example.test")
    )
    settings = Settings(
        embedding_dim=8, claim_embedding_dim=512, fetch_full_text=False, database_url="sqlite://"
    )

    class One:
        def fetch(self, source: Source, ctx: object) -> list:
            _ = (source, ctx)
            return []

    pipeline = DigestPipeline(store, settings, adapter=One())
    pipeline.run()
    assert "attention" in pipeline.stages.acked
    assert pipeline._claim_embedder().dim == 512  # type: ignore[attr-defined]


def test_grok_reads_token_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.x.ai"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Berlin is pausing rents."}}],
                "usage": {"total_tokens": 7},
            },
        )

    provider = GrokProvider("test-key", transport=httpx.MockTransport(handler))
    text = provider.complete("system", "user")
    assert "pausing" in text
    assert provider.last_call_tokens == 7
    assert provider.token_usage == 7


def test_source_desk_adds_and_disables() -> None:
    client = TestClient(app)
    home = client.get("/")
    assert home.status_code == 200
    assert "independent origins" in home.text
    added = client.post(
        "/sources",
        data={
            "source_id": "probe-desk",
            "name": "Probe",
            "homepage_url": "https://example.test",
            "feed_url": "",
            "spectrum": "regional",
        },
    )
    assert added.status_code == 200
    assert "probe-desk" in added.text
    disabled = client.post("/sources/disable", data={"source_id": "probe-desk"})
    assert disabled.status_code == 200
    assert "Disabled probe-desk" in disabled.text
    assert "Probe Desk" not in disabled.text


def test_circulating_note_is_not_a_spine_sentence() -> None:
    now = datetime.now(UTC)
    story = Story(
        first_seen_at=now,
        last_seen_at=now,
        title_hint="Quiet",
        fingerprint="quiet",
    )
    post = SocialPost(
        platform="x",
        external_id="9",
        author_handle="reader",
        text="unverified",
        topic="Rent rumour",
        retrieved_at=now,
    )
    draft = build_draft_for_stories(
        run_id=uuid4(),
        stories=[story],
        articles_by_id={},
        sources={},
        settings=Settings(database_url="sqlite://"),
        social_posts=[post],
    )
    notes = [sentence.text for sentence in draft.sentences if sentence.section == "note"]
    assert "Circulating, unverified: Rent rumour" in notes
    spine = [sentence for sentence in draft.sentences if sentence.section == "spine"]
    assert all("Rent rumour" not in sentence.text for sentence in spine)
