"""A 30-day source capture used as the deployed edition and as algorithm fixtures.

Article bodies are not stored. The file keeps headlines, links, dates, origin
ids, embeddings, and the label inputs so the assignment and label rules can be
run again on the same capture.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from newsie.adapters.registry import AdapterRouter
from newsie.citations import validate_draft
from newsie.cluster import assign_stories, rank_stories
from newsie.config import Settings
from newsie.domain import (
    Article,
    ArticleEmbedding,
    CitationRef,
    ClaimEvidence,
    DigestDraft,
    DigestSentence,
    EvidenceLabel,
    SourceTier,
    Stance,
    Story,
)
from newsie.embeddings import HashEmbeddingProvider
from newsie.evidence import label_claim
from newsie.pipeline import DigestPipeline, seed_live_sources
from newsie.store import MemoryStore

CORPUS_DIM = 32
LOOKBACK_DAYS = 30


def corpus_path() -> Path:
    name = Path("data") / "corpus" / "month.json"
    candidates = [
        Path(__file__).resolve().parents[2] / name,
        Path(__file__).resolve().parents[1] / name,
        Path.cwd() / name,
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def capture_settings() -> Settings:
    return Settings(
        ingest_lookback_hours=LOOKBACK_DAYS * 24,
        max_articles_per_source=40,
        max_sources_per_run=40,
        max_fetches_per_run=4000,
        max_stories_per_digest=8,
        fetch_full_text=False,
        demo_mode=False,
        embedding_dim=CORPUS_DIM,
        claim_embedding_dim=CORPUS_DIM,
        database_url="sqlite://",
    )


def capture_corpus(path: Path | None = None) -> dict[str, object]:
    """Fetch the seed feeds for the lookback window and write the algorithm record."""
    settings = capture_settings()
    store = MemoryStore()
    seed_live_sources(store)
    router = AdapterRouter(allow_fixture_fallback=False)
    pipeline = DigestPipeline(
        store,
        settings,
        adapter=router,
        embedder=HashEmbeddingProvider(dim=CORPUS_DIM),
    )
    captured_at = datetime.now(UTC)
    pipeline.run()
    payload = _payload(store, captured_at=captured_at, errors=list(router.errors))
    target = path or corpus_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_payload(path: Path | None = None) -> dict[str, object]:
    raw = json.loads((path or corpus_path()).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("corpus file must be a JSON object")
    return raw


def corpus_available() -> bool:
    return corpus_path().is_file()


def articles_from_payload(payload: dict[str, object]) -> list[Article]:
    rows = payload["articles"]
    if not isinstance(rows, list):
        raise ValueError("corpus articles must be a list")
    articles: list[Article] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        published = row.get("published_at")
        retrieved = row.get("retrieved_at")
        articles.append(
            Article(
                id=UUID(str(row["id"])),
                source_id=str(row["source_id"]),
                url=str(row["url"]),
                canonical_url=str(row["canonical_url"]),
                title=str(row["title"]),
                published_at=datetime.fromisoformat(published) if published else None,
                retrieved_at=datetime.fromisoformat(str(retrieved)),
                content_text=str(row["title"]),
                content_hash=str(row["content_hash"]),
                tier_at_ingest=SourceTier(str(row["tier"])),
                origin_id=str(row["origin_id"]) if row.get("origin_id") else None,
            )
        )
    return articles


def embeddings_from_payload(payload: dict[str, object]) -> dict[UUID, ArticleEmbedding]:
    rows = payload["articles"]
    if not isinstance(rows, list):
        raise ValueError("corpus articles must be a list")
    captured = datetime.fromisoformat(str(payload["captured_at"]))
    found: dict[UUID, ArticleEmbedding] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("embedding"), list):
            continue
        article_id = UUID(str(row["id"]))
        vector = [float(value) for value in row["embedding"]]
        found[article_id] = ArticleEmbedding(
            article_id=article_id,
            embedding=vector,
            embedding_model="hash",
            embedding_dim=len(vector),
            embedded_at=captured,
        )
    return found


def replay_story_sets(payload: dict[str, object]) -> list[set[str]]:
    settings = capture_settings()
    stories = assign_stories(
        articles_from_payload(payload),
        embeddings_from_payload(payload),
        [],
        threshold=settings.cluster_similarity_threshold,
        window_hours=settings.story_window_hours,
        now=datetime.fromisoformat(str(payload["captured_at"])),
    )
    return [{str(article_id) for article_id in story.article_ids} for story in stories]


def recorded_story_sets(payload: dict[str, object]) -> list[set[str]]:
    rows = payload["stories"]
    if not isinstance(rows, list):
        raise ValueError("corpus stories must be a list")
    return [
        {str(article_id) for article_id in row["article_ids"]}
        for row in rows
        if isinstance(row, dict)
    ]


def labels_match(payload: dict[str, object]) -> bool:
    rows = payload["labels"]
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        label, cross = label_claim(
            support_origins=set(str(item) for item in row["support_origins"]),
            contradict_origins=set(str(item) for item in row["contradict_origins"]),
            support_tiers=[SourceTier(str(item)) for item in row["support_tiers"]],
            support_spectra=set(str(item) for item in row["support_spectra"]),
        )
        if label.value != row["label"] or cross != bool(row["cross_spectrum"]):
            return False
    return True


def load_corpus_edition() -> tuple[MemoryStore, DigestDraft]:
    """Store and draft for the captured month. Article text is the headline only."""
    payload = load_payload()
    store = MemoryStore()
    from newsie.sources import load_live_sources

    for source in load_live_sources():
        store.upsert_source(source)
    articles = articles_from_payload(payload)
    by_id = {article.id: article for article in articles}
    for article in articles:
        store.save_article(article)
    story_rows = payload["stories"]
    stories: list[Story] = []
    if isinstance(story_rows, list):
        for row in story_rows:
            if not isinstance(row, dict):
                continue
            article_ids = [UUID(str(item)) for item in row["article_ids"]]
            first = by_id[article_ids[0]].retrieved_at if article_ids else datetime.now(UTC)
            story = Story(
                id=UUID(str(row["id"])),
                fingerprint=str(row["id"]),
                first_seen_at=first,
                last_seen_at=first,
                title_hint=str(row["title_hint"]),
                status="active",
                article_ids=article_ids,
                independent_origin_count=int(row["independent_origin_count"]),
            )
            store.save_story(story)
            stories.append(story)
    ranked = rank_stories(
        stories,
        by_id,
        store.sources,
        limit=capture_settings().max_stories_per_digest,
    )
    draft = _draft(ranked, by_id)
    checked = validate_draft(draft, [by_id[i] for story in ranked for i in story.article_ids])
    draft = draft.model_copy(
        update={"validation_status": "ok" if checked.ok else "fail:" + ";".join(checked.errors)}
    )
    store.save_draft(draft)
    return store, draft


def _draft(stories: list[Story], articles: dict[UUID, Article]) -> DigestDraft:
    draft_id = UUID(int=1)
    sentences: list[DigestSentence] = []
    for story in stories:
        if not story.article_ids:
            continue
        article = articles[story.article_ids[0]]
        sentences.append(
            DigestSentence(
                draft_id=draft_id,
                story_id=story.id,
                section="spine",
                text=article.title,
                citations=[
                    CitationRef(
                        article_id=article.id,
                        url=article.canonical_url or article.url,
                        quote=article.title,
                    )
                ],
            )
        )
    return DigestDraft(
        id=draft_id,
        run_id=draft_id,
        story_ids=[story.id for story in stories],
        spine_md="\n".join(sentence.text for sentence in sentences),
        perspectives=[],
        divergence_md="",
        events=[],
        citations=[ref.url for sentence in sentences for ref in sentence.citations],
        sentences=sentences,
        english_render_md="",
        validation_status="pending",
        created_at=datetime.now(UTC),
    )


def _payload(store: MemoryStore, *, captured_at: datetime, errors: list[str]) -> dict[str, object]:
    articles = []
    for article in store.list_articles():
        embedding = store.get_embedding(article.id)
        if embedding is None:
            continue
        articles.append(
            {
                "id": str(article.id),
                "source_id": article.source_id,
                "url": article.url,
                "canonical_url": article.canonical_url,
                "title": article.title,
                "published_at": article.published_at.isoformat() if article.published_at else None,
                "retrieved_at": article.retrieved_at.isoformat(),
                "content_hash": article.content_hash,
                "tier": article.tier_at_ingest.value,
                "origin_id": article.origin_id,
                "embedding": embedding.embedding,
            }
        )
    stories = [
        {
            "id": str(story.id),
            "title_hint": story.title_hint,
            "article_ids": [str(article_id) for article_id in story.article_ids],
            "independent_origin_count": story.independent_origin_count,
            "status": story.status,
        }
        for story in store.list_stories()
    ]
    return {
        "captured_at": captured_at.isoformat(),
        "lookback_hours": LOOKBACK_DAYS * 24,
        "embedding_dim": CORPUS_DIM,
        "fetch_errors": errors,
        "articles": articles,
        "stories": stories,
        "labels": _labels(store),
    }


def _labels(store: MemoryStore) -> list[dict[str, object]]:
    articles = {article.id: article for article in store.list_articles()}
    sources = store.sources
    grouped: dict[UUID, list[ClaimEvidence]] = {}
    for row in store.list_evidence():
        grouped.setdefault(row.claim_cluster_id, []).append(row)
    labels: list[dict[str, object]] = []
    for cluster in store.list_clusters():
        support: set[str] = set()
        contradict: set[str] = set()
        tiers: list[SourceTier] = []
        spectra: set[str] = set()
        for row in grouped.get(cluster.id, []):
            article = articles.get(row.article_id)
            if article is None or article.tier_at_ingest == SourceTier.SOCIAL_SIGNAL:
                continue
            source = sources.get(article.source_id)
            tier = source.tier if source is not None else article.tier_at_ingest
            if tier == SourceTier.SOCIAL_SIGNAL:
                continue
            if row.stance == Stance.SUPPORTS:
                support.add(row.origin_id)
                tiers.append(tier)
                if source is not None:
                    spectra.add(source.spectrum.value)
            elif row.stance == Stance.CONTRADICTS:
                contradict.add(row.origin_id)
        label, cross = label_claim(
            support_origins=support,
            contradict_origins=contradict,
            support_tiers=tiers,
            support_spectra=spectra,
        )
        if label != cluster.label or cross != cluster.cross_spectrum:
            raise RuntimeError(f"label drift on {cluster.id}")
        labels.append(
            {
                "label": label.value,
                "cross_spectrum": cross,
                "support_origins": sorted(support),
                "contradict_origins": sorted(contradict),
                "support_tiers": [tier.value for tier in tiers],
                "support_spectra": sorted(spectra),
            }
        )
    return labels


def assert_label(value: str) -> EvidenceLabel:
    return EvidenceLabel(value)
