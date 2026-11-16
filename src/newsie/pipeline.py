"""Digest pipeline. Stages 2, 4, 5 and 6 are new; the others are the old stages in place."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from newsie.adapters.base import FetchContext, SourceAdapter
from newsie.adapters.http_adapter import fetch_article_page
from newsie.adapters.registry import AdapterRouter
from newsie.citations import validate_draft
from newsie.claims import extract_claims
from newsie.cluster import assign_stories, rank_stories
from newsie.config import Settings
from newsie.digest import build_draft_for_stories
from newsie.domain import Article, DigestDraft, DigestRun
from newsie.embeddings import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    OpenAIEmbeddingProvider,
    embed_articles,
    embed_claims,
)
from newsie.evidence import match_story
from newsie.guardrails import (
    BudgetDimension,
    BudgetExceededError,
    BudgetLedger,
    KillSwitch,
    KillSwitchEngagedError,
    LoopGuard,
    content_hash,
)
from newsie.llm import LLMProvider, StubLLMProvider, call_tokens
from newsie.origins import assign_origins
from newsie.sources import load_live_sources, load_seed_sources
from newsie.stage_queue import StageQueue
from newsie.store import Store
from newsie.trends import attach_attention, build_trends
from newsie.urls import canonicalise_url


@dataclass
class PipelineResult:
    run: DigestRun
    draft: DigestDraft | None
    articles_ingested: int
    stories: int
    errors: list[str] = field(default_factory=list)
    fetch_errors: list[str] = field(default_factory=list)


class DigestPipeline:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        *,
        adapter: SourceAdapter | AdapterRouter,
        embedder: EmbeddingProvider | None = None,
        llm: LLMProvider | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.adapter = adapter
        self.embedder = embedder or HashEmbeddingProvider(dim=settings.embedding_dim)
        self.llm = llm or StubLLMProvider()
        self.stages = StageQueue()
        self.kill_switch = kill_switch or KillSwitch(engaged=settings.kill_switch)
        self.budget = BudgetLedger(
            caps={
                BudgetDimension.LLM_TOKENS: settings.max_llm_tokens_per_run,
                BudgetDimension.FETCHES: settings.max_fetches_per_run,
                BudgetDimension.PLAYWRIGHT_MINUTES: settings.max_playwright_minutes_per_run,
                BudgetDimension.PIPELINE_STEPS: settings.max_pipeline_steps,
            }
        )
        self.stage_tokens: dict[str, int] = {}

    def _step(self, name: str) -> None:
        self.kill_switch.check()
        self.budget.charge(BudgetDimension.PIPELINE_STEPS, 1)
        self.stages.ack(self.stages.send(name))

    def _claim_embedder(self) -> EmbeddingProvider:
        dim = self.settings.claim_embedding_dim
        if isinstance(self.embedder, OpenAIEmbeddingProvider):
            return OpenAIEmbeddingProvider(self.embedder.api_key, self.embedder.model, dim)
        return HashEmbeddingProvider(dim=dim)

    def _charge_tokens(self, stage: str, amount: int) -> None:
        if amount > 0:
            self.budget.charge(BudgetDimension.LLM_TOKENS, amount)
        self.stage_tokens[stage] = self.stage_tokens.get(stage, 0) + amount

    def _snapshot(self) -> dict[str, Any]:
        snap: dict[str, Any] = dict(self.budget.snapshot())
        snap["by_stage"] = dict(self.stage_tokens)
        return snap

    def ingest(self) -> int:
        self._step("collect")
        sources = self.store.list_enabled_sources()[: self.settings.max_sources_per_run]
        ctx = FetchContext(
            deadline=datetime.now(UTC),
            max_articles=self.settings.max_articles_per_source,
            lookback_hours=self.settings.ingest_lookback_hours,
        )
        guard = LoopGuard(
            max_iterations=self.settings.max_sources_per_run + 1,
            name="ingest_sources",
        )
        if isinstance(self.adapter, AdapterRouter):
            self.adapter.errors.clear()
        new_count = 0
        now = datetime.now(UTC)
        for source in sources:
            guard.tick()
            self.kill_switch.check()
            self.budget.charge(BudgetDimension.FETCHES, 1)
            candidates = self.adapter.fetch(source, ctx)
            article_guard = LoopGuard(
                max_iterations=self.settings.max_articles_per_source + 1,
                name=f"ingest_articles:{source.id}",
            )
            for cand in candidates:
                article_guard.tick()
                text = cand.content_text.strip()
                title = cand.title.strip() or cand.url
                canonical = canonicalise_url(cand.url)
                method = str(cand.raw_metadata.get("extraction_method") or "rss_summary")
                partial = bool(cand.raw_metadata.get("partial") or False)
                full_text: str | None = None
                enrich = (
                    self.settings.fetch_full_text
                    and not cand.raw_metadata.get("fixture")
                    and self.budget.remaining(BudgetDimension.FETCHES) > 0
                )
                if enrich:
                    self.budget.charge(BudgetDimension.FETCHES, 1)
                    page = fetch_article_page(
                        cand.url, rate_limit_per_hour=source.rate_limit_per_hour
                    )
                    if page is not None and str(page["text"]).strip():
                        text = str(page["text"]).strip()
                        title = str(page["title"]).strip() or title
                        canonical = str(page["canonical_url"])
                        method = str(page["method"])
                        partial = bool(page["partial"])
                        full_text = text
                if not text:
                    continue
                article = Article(
                    source_id=source.id,
                    url=cand.url,
                    canonical_url=canonical,
                    title=title,
                    byline=cand.byline,
                    published_at=cand.published_at,
                    retrieved_at=now,
                    content_text=text,
                    full_text=full_text,
                    content_hash=content_hash(text),
                    lang=cand.language,
                    tier_at_ingest=source.tier,
                    raw_metadata=cand.raw_metadata,
                    extraction_method=method,
                    partial=partial,
                )
                before = self.store.get_article_by_hash(article.content_hash)
                saved = self.store.save_article(article)
                if before is None and saved.id == article.id:
                    new_count += 1
        return new_count

    def detect_origins(self) -> int:
        self._step("origins")
        articles = self.store.list_articles()
        updated = assign_origins(
            articles,
            self.store.sources,
            jaccard_threshold=self.settings.origin_jaccard_threshold,
        )
        for article in updated:
            self.store.update_article(article)
        return len(updated)

    def embed_new(self) -> int:
        self._step("embed")
        missing = self.store.articles_missing_embeddings()
        if not missing:
            return 0
        batch = missing[: self.settings.max_fetches_per_run]
        embeddings = embed_articles(batch, self.embedder, self.settings)
        for emb in embeddings:
            self.store.save_embedding(emb)
        self._charge_tokens("embed", int(getattr(self.embedder, "token_usage", 0) or 0))
        return len(embeddings)

    def cluster(self) -> list[Any]:
        self._step("cluster")
        cap = self.settings.max_sources_per_run * self.settings.max_articles_per_source
        articles = sorted(
            self.store.list_articles(),
            key=lambda article: article.retrieved_at,
            reverse=True,
        )[:cap]
        emb_map = {
            article.id: emb
            for article in articles
            if (emb := self.store.get_embedding(article.id)) is not None
        }
        stories = assign_stories(
            articles,
            emb_map,
            self.store.list_stories(),
            threshold=self.settings.cluster_similarity_threshold,
            window_hours=self.settings.story_window_hours,
            nearest=self.store.nearest_story,
        )
        active: list[Any] = []
        for story in stories:
            self.store.save_story(story)
            if story.status == "closed":
                self.store.drop_claim_embeddings(story.id)
            else:
                active.append(story)
        return active

    def attend(self) -> int:
        self._step("attention")
        posts = self.store.list_social_posts()
        points = build_trends(posts, self.store.list_trends())
        self.store.replace_trends(points)
        linked = attach_attention(self.store.list_stories(), points)
        self.store.replace_attention(linked)
        return len(linked)

    def extract_claim_stage(self) -> int:
        self._step("claims")
        articles = self.store.list_articles()
        guard = LoopGuard(max_iterations=len(articles) + 1, name="claims")
        total = 0
        usage = 0
        for article in articles:
            guard.tick()
            self.kill_switch.check()
            claims, spent = extract_claims(article, self.llm)
            usage += spent
            self.store.replace_claims(article.id, claims)
            total += len(claims)
        self._charge_tokens("claims", usage)
        return total

    def label_evidence(self) -> int:
        self._step("evidence")
        articles_by_id = {article.id: article for article in self.store.list_articles()}
        claims = self.store.list_claims()
        labelled = 0
        for story in self.store.list_stories():
            if story.status != "active":
                continue
            self.kill_switch.check()
            members = [articles_by_id[aid] for aid in story.article_ids if aid in articles_by_id]
            member_ids = {article.id for article in members}
            story_claims = [claim for claim in claims if claim.article_id in member_ids]
            claim_embedder = self._claim_embedder()
            vectors = embed_claims(
                [claim.text for claim in story_claims],
                claim_embedder,
                expect_dim=self.settings.claim_embedding_dim,
            )
            self._charge_tokens("evidence", call_tokens(claim_embedder))
            for claim, vector in zip(story_claims, vectors, strict=True):
                self.store.save_claim_vector(claim.id, story.id, vector)
            clusters, evidence = match_story(
                story,
                members,
                story_claims,
                vectors,
                self.store.sources,
                threshold=self.settings.claim_similarity_threshold,
                llm=self.llm,
            )
            self.store.replace_story_evidence(story.id, clusters, evidence)
            labelled += len(clusters)
        return labelled

    def build_digest(self, run: DigestRun) -> DigestDraft:
        self._step("digest")
        articles_by_id = {article.id: article for article in self.store.list_articles()}
        attention = {
            row.story_id: row.attention for row in self.store.list_attention() if row.marker
        }
        ranked = rank_stories(
            self.store.list_stories(),
            articles_by_id,
            self.store.sources,
            limit=self.settings.max_stories_per_digest,
            attention=attention,
        )
        spent: list[int] = []
        draft = build_draft_for_stories(
            run_id=run.id,
            stories=ranked,
            articles_by_id=articles_by_id,
            sources=self.store.sources,
            settings=self.settings,
            llm=self.llm,
            claims=self.store.list_claims(),
            clusters=self.store.list_clusters(),
            evidence=self.store.list_evidence(),
            social_posts=self.store.list_social_posts(),
            token_sink=spent,
        )
        self._charge_tokens("digest", spent[0] if spent else 0)
        cluster_arts: list[Article] = []
        for story in ranked:
            for aid in story.article_ids:
                if aid in articles_by_id:
                    cluster_arts.append(articles_by_id[aid])
        result = validate_draft(draft, cluster_arts)
        draft = draft.model_copy(
            update={
                "validation_status": "ok" if result.ok else "fail:" + ";".join(result.errors),
                "sentences": result.sentences or draft.sentences,
            }
        )
        self.store.save_draft(draft)
        return draft

    def run(self) -> PipelineResult:
        now = datetime.now(UTC)
        run = DigestRun(scheduled_for=now, started_at=now, status="running")
        self.store.save_run(run)
        errors: list[str] = []
        fetch_errors: list[str] = []
        draft: DigestDraft | None = None
        ingested = 0
        story_count = 0
        try:
            ingested = self.ingest()
            if isinstance(self.adapter, AdapterRouter):
                fetch_errors = list(self.adapter.errors)
            self.detect_origins()
            self.embed_new()
            stories = self.cluster()
            story_count = len(stories)
            self.attend()
            self.extract_claim_stage()
            self.label_evidence()
            if story_count == 0:
                run = run.model_copy(
                    update={
                        "status": "empty",
                        "finished_at": datetime.now(UTC),
                        "budget_snapshot": self._snapshot(),
                    }
                )
                self.store.save_run(run)
                return PipelineResult(
                    run, None, ingested, 0, ["no stories"], fetch_errors=fetch_errors
                )
            draft = self.build_digest(run)
            run = run.model_copy(
                update={
                    "status": "awaiting_hitl",
                    "finished_at": datetime.now(UTC),
                    "budget_snapshot": self._snapshot(),
                }
            )
        except (KillSwitchEngagedError, BudgetExceededError) as exc:
            errors.append(str(exc))
            run = run.model_copy(
                update={
                    "status": "aborted",
                    "kill_switch_hit": isinstance(exc, KillSwitchEngagedError),
                    "finished_at": datetime.now(UTC),
                    "budget_snapshot": self._snapshot(),
                }
            )
        self.store.save_run(run)
        return PipelineResult(run, draft, ingested, story_count, errors, fetch_errors=fetch_errors)


def seed_demo_sources(store: Store) -> None:
    for source in load_seed_sources(demo_mode=True):
        store.upsert_source(source)


def seed_live_sources(store: Store) -> None:
    for source in load_live_sources():
        store.upsert_source(source)
