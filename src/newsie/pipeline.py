"""Durable-style digest pipeline with bounded, idempotent steps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from newsie.adapters.base import FetchContext, SourceAdapter
from newsie.citations import validate_draft
from newsie.cluster import cluster_articles, rank_stories
from newsie.config import Settings
from newsie.digest import LLMProvider, StubLLMProvider, build_draft_for_stories
from newsie.domain import Article, DigestDraft, DigestRun, Source
from newsie.embeddings import EmbeddingProvider, HashEmbeddingProvider, embed_articles
from newsie.guardrails import (
    BudgetDimension,
    BudgetExceededError,
    BudgetLedger,
    KillSwitch,
    KillSwitchEngagedError,
    LoopGuard,
    content_hash,
)
from newsie.store import MemoryStore


@dataclass
class PipelineResult:
    run: DigestRun
    draft: DigestDraft | None
    articles_ingested: int
    stories: int
    errors: list[str]


class DigestPipeline:
    def __init__(
        self,
        store: MemoryStore,
        settings: Settings,
        *,
        adapter: SourceAdapter,
        embedder: EmbeddingProvider | None = None,
        llm: LLMProvider | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.adapter = adapter
        self.embedder = embedder or HashEmbeddingProvider(dim=settings.embedding_dim)
        self.llm = llm or StubLLMProvider()
        self.kill_switch = kill_switch or KillSwitch(engaged=settings.kill_switch)
        self.budget = BudgetLedger(
            caps={
                BudgetDimension.LLM_TOKENS: settings.max_llm_tokens_per_run,
                BudgetDimension.FETCHES: settings.max_fetches_per_run,
                BudgetDimension.PLAYWRIGHT_MINUTES: settings.max_playwright_minutes_per_run,
                BudgetDimension.PIPELINE_STEPS: settings.max_pipeline_steps,
            }
        )

    def _step(self, name: str) -> None:
        self.kill_switch.check()
        self.budget.charge(BudgetDimension.PIPELINE_STEPS, 1)

    def ingest(self) -> int:
        self._step("ingest")
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
                if not text:
                    continue
                # Prompt-injection hardening: treat content as data only (never execute)
                article = Article(
                    source_id=source.id,
                    url=cand.url,
                    canonical_url=cand.url,
                    title=cand.title.strip() or cand.url,
                    byline=cand.byline,
                    published_at=cand.published_at,
                    retrieved_at=now,
                    content_text=text,
                    content_hash=content_hash(text),
                    lang=cand.language,
                    tier_at_ingest=source.tier,
                    raw_metadata=cand.raw_metadata,
                )
                before = self.store.get_article_by_hash(article.content_hash)
                saved = self.store.save_article(article)
                if before is None and saved.id == article.id:
                    new_count += 1
        return new_count

    def embed_new(self) -> int:
        self._step("embed")
        missing = self.store.articles_missing_embeddings()
        if not missing:
            return 0
        # Bound embed batch size for efficiency
        batch = missing[: self.settings.max_fetches_per_run]
        embeddings = embed_articles(batch, self.embedder, self.settings)
        for emb in embeddings:
            self.store.save_embedding(emb)
        # Charge a nominal token cost for embedding work in demo
        self.budget.charge(BudgetDimension.LLM_TOKENS, min(1000, 50 * len(batch)))
        return len(embeddings)

    def cluster(self) -> list[Any]:
        self._step("cluster")
        articles = self.store.list_articles()
        emb_map = {
            a.id: emb
            for a in articles
            if (emb := self.store.get_embedding(a.id)) is not None
        }
        stories = cluster_articles(
            articles,
            emb_map,
            self.store.sources,
            threshold=self.settings.cluster_similarity_threshold,
            max_iterations=max(100, len(articles) * len(articles) + 10),
        )
        # Idempotent story replace by fingerprint for demo store
        existing_fps = {s.fingerprint: s for s in self.store.list_stories()}
        for story in stories:
            if story.fingerprint in existing_fps:
                keep = existing_fps[story.fingerprint]
                merged = story.model_copy(update={"id": keep.id})
                self.store.save_story(merged)
            else:
                self.store.save_story(story)
        return self.store.list_stories()

    def build_digest(self, run: DigestRun) -> DigestDraft:
        self._step("digest")
        articles_by_id = {a.id: a for a in self.store.list_articles()}
        ranked = rank_stories(
            self.store.list_stories(),
            articles_by_id,
            self.store.sources,
            limit=self.settings.max_stories_per_digest,
        )
        draft = build_draft_for_stories(
            run_id=run.id,
            stories=ranked,
            articles_by_id=articles_by_id,
            sources=self.store.sources,
            settings=self.settings,
            llm=self.llm,
        )
        self.budget.charge(BudgetDimension.LLM_TOKENS, 2000)

        cluster_arts: list[Article] = []
        for story in ranked:
            for aid in story.article_ids:
                if aid in articles_by_id:
                    cluster_arts.append(articles_by_id[aid])
        result = validate_draft(draft, cluster_arts)
        draft = draft.model_copy(
            update={"validation_status": "ok" if result.ok else "fail:" + ";".join(result.errors)}
        )
        self.store.save_draft(draft)
        return draft

    def run(self) -> PipelineResult:
        now = datetime.now(UTC)
        run = DigestRun(scheduled_for=now, started_at=now, status="running")
        self.store.save_run(run)
        errors: list[str] = []
        draft: DigestDraft | None = None
        ingested = 0
        story_count = 0
        try:
            ingested = self.ingest()
            self.embed_new()
            stories = self.cluster()
            story_count = len(stories)
            if story_count == 0:
                run = run.model_copy(
                    update={
                        "status": "empty",
                        "finished_at": datetime.now(UTC),
                        "budget_snapshot": self.budget.snapshot(),
                    }
                )
                self.store.save_run(run)
                return PipelineResult(run, None, ingested, 0, ["no stories"])
            draft = self.build_digest(run)
            run = run.model_copy(
                update={
                    "status": "awaiting_hitl",
                    "finished_at": datetime.now(UTC),
                    "budget_snapshot": self.budget.snapshot(),
                }
            )
        except (KillSwitchEngagedError, BudgetExceededError) as exc:
            errors.append(str(exc))
            run = run.model_copy(
                update={
                    "status": "aborted",
                    "kill_switch_hit": isinstance(exc, KillSwitchEngagedError),
                    "finished_at": datetime.now(UTC),
                    "budget_snapshot": self.budget.snapshot(),
                }
            )
        self.store.save_run(run)
        return PipelineResult(run, draft, ingested, story_count, errors)


def seed_demo_sources(store: MemoryStore) -> None:
    from newsie.domain import AdapterKind

    seeds = [
        Source(
            id="tagesschau",
            name="Tagesschau",
            homepage_url="https://www.tagesschau.de",
            feed_url="https://www.tagesschau.de/index~rss2.xml",
            adapter=AdapterKind.FIXTURE,
            spectrum_tags=["center"],
        ),
        Source(
            id="rbb",
            name="rbb",
            homepage_url="https://www.rbb24.de",
            feed_url=None,
            adapter=AdapterKind.FIXTURE,
            spectrum_tags=["regional"],
        ),
        Source(
            id="zeit",
            name="ZEIT ONLINE",
            homepage_url="https://www.zeit.de",
            feed_url="https://newsfeed.zeit.de/index",
            adapter=AdapterKind.FIXTURE,
            spectrum_tags=["center-left"],
        ),
    ]
    for s in seeds:
        store.upsert_source(s)
