"""Digest brain — LLM provider interface + deterministic stub for demos."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from newsie.config import Settings
from newsie.domain import (
    Article,
    DigestDraft,
    PerspectiveBrief,
    PoliticalEvent,
    Source,
    SourceTier,
    Story,
)


class LLMProvider(Protocol):
    def complete(self, system: str, user: str) -> str:
        ...


class StubLLMProvider:
    """No-network digest generator for demos/tests."""

    def complete(self, system: str, user: str) -> str:
        return "stub"


def _reporting_articles(articles: list[Article]) -> list[Article]:
    return [
        a
        for a in articles
        if a.tier_at_ingest in (SourceTier.REPORTING, SourceTier.OFFICIAL)
    ]


def build_draft_for_stories(
    *,
    run_id: UUID,
    stories: list[Story],
    articles_by_id: dict[UUID, Article],
    sources: dict[str, Source],
    settings: Settings,
    llm: LLMProvider | None = None,
) -> DigestDraft:
    _ = llm  # production Anthropic path plugs in later; stub builds structured draft
    cluster_articles: list[Article] = []
    for story in stories:
        for aid in story.article_ids:
            art = articles_by_id.get(aid)
            if art is not None:
                cluster_articles.append(art)

    reporting = _reporting_articles(cluster_articles) or cluster_articles
    citation_urls = [a.url for a in reporting]

    spine_lines = ["## Factual spine", ""]
    for art in reporting:
        src = sources.get(art.source_id)
        src_name = src.name if src else art.source_id
        spine_lines.append(f"- {art.title} ({src_name}) — {art.url}")
    spine_md = "\n".join(spine_lines)

    perspectives: list[PerspectiveBrief] = []
    for party in settings.default_parties:
        # Label-aware brief: summary explicitly tags the party (supports label-swap evals)
        perspectives.append(
            PerspectiveBrief(
                party_label=party,
                summary=(
                    f"From a {party} framing: coverage emphasizes how this story "
                    f"affects priorities associated with {party}."
                ),
                citation_urls=citation_urls[:2],
            )
        )

    titles = [s.title_hint for s in stories]
    divergence_md = (
        "## Divergence\n\n"
        "Outlets emphasize different angles across: "
        + "; ".join(titles)
        + ". Compare citations for corroboration."
    )

    events = [
        PoliticalEvent(
            title=stories[0].title_hint if stories else "No events",
            when=None,
            where="Berlin/Germany",
            citation_urls=citation_urls[:1],
        )
    ]

    render_parts = [
        "# Newsie digest",
        "",
        spine_md,
        "",
        "## Perspectives",
        "",
    ]
    for p in perspectives:
        render_parts.append(f"### {p.party_label}")
        render_parts.append(p.summary)
        render_parts.append("")
    render_parts.extend([divergence_md, "", "## Events", ""])
    for e in events:
        render_parts.append(f"- {e.title}" + (f" ({e.where})" if e.where else ""))

    return DigestDraft(
        run_id=run_id,
        story_ids=[s.id for s in stories],
        spine_md=spine_md,
        perspectives=perspectives,
        divergence_md=divergence_md,
        events=events,
        citations=citation_urls,
        english_render_md="\n".join(render_parts),
        validation_status="pending",
        created_at=datetime.now(UTC),
    )
