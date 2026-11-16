"""Structured digest view for the web UI — newspaper layout, not raw markdown."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from newsie.domain import Article, DigestDraft, PerspectiveBrief, PoliticalEvent, Source, Story

BERLIN = ZoneInfo("Europe/Berlin")

CATEGORY_ORDER = (
    "Germany & politics",
    "Berlin & Brandenburg",
    "Corroborated wire",
)


@dataclass(frozen=True)
class HeadlineItem:
    title: str
    url: str
    source_id: str
    source_name: str
    spectrum_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class FramingNote:
    """One outlet's framing, derived from spectrum tags (no LLM call)."""

    outlet: str
    sentence: str


@dataclass(frozen=True)
class StoryBlock:
    headline: str
    category: str
    corroboration: float
    items: tuple[HeadlineItem, ...]
    dek: str
    outlet_count: int
    meanings: tuple[FramingNote, ...]
    differ_line: str
    is_lead: bool = False


@dataclass(frozen=True)
class CategorySection:
    title: str
    stories: tuple[StoryBlock, ...]


@dataclass(frozen=True)
class TrendingSource:
    source_id: str
    name: str
    article_count: int
    share_pct: float
    reliability: float
    spectrum_tags: tuple[str, ...]
    trending: bool


@dataclass(frozen=True)
class DigestView:
    edition_label: str
    sections: tuple[CategorySection, ...]
    divergence_text: str
    events: tuple[PoliticalEvent, ...]
    perspectives: tuple[PerspectiveBrief, ...]
    trending: tuple[TrendingSource, ...]
    validation_status: str | None


def _sources_map(store: Any) -> dict[str, Source]:
    if hasattr(store, "sources"):
        raw = store.sources
        if isinstance(raw, dict):
            return raw
    return {s.id: s for s in store.list_enabled_sources()}


def _strip_md_heading(md: str) -> str:
    lines = [ln for ln in md.strip().splitlines() if ln.strip()]
    if lines and lines[0].lstrip().startswith("#"):
        return "\n".join(lines[1:]).strip()
    return md.strip()


def _story_category(articles: list[Article], sources: dict[str, Source]) -> str:
    tags: set[str] = set()
    for art in articles:
        src = sources.get(art.source_id)
        if src is not None:
            tags.update(src.spectrum_tags)
    if "regional" in tags:
        return "Berlin & Brandenburg"
    if len(articles) >= 2:
        return "Corroborated wire"
    return "Germany & politics"


def _edition_label(when: datetime) -> str:
    local = when.astimezone(BERLIN)
    return f"{local:%A,} {local.day} {local:%B %Y} · Europe/Berlin"


def _edition_label_fallback() -> str:
    now = datetime.now(BERLIN)
    return f"{now:%A,} {now.day} {now:%B %Y} · Europe/Berlin"


def _headline_item(art: Article, sources: dict[str, Source]) -> HeadlineItem:
    src = sources.get(art.source_id)
    return HeadlineItem(
        title=art.title,
        url=art.url,
        source_id=art.source_id,
        source_name=src.name if src else art.source_id,
        spectrum_tags=tuple(src.spectrum_tags) if src else (),
    )


def _framing_phrase(tags: tuple[str, ...]) -> str:
    found = set(tags)
    if "regional" in found:
        return "Berlin/local framing"
    if "center-left" in found:
        return "social-priority framing"
    if "center" in found:
        return "institutional/mainstream framing"
    if tags:
        return f"{tags[0].replace('-', ' ')} framing"
    return "a general news framing"


def _meaning_sentence(item: HeadlineItem) -> str:
    return f"{item.source_name} reads this with {_framing_phrase(item.spectrum_tags)}."


def _differ_line(items: tuple[HeadlineItem, ...], divergence_text: str) -> str:
    if len(items) >= 2:
        bits = [f"{item.source_name} (“{item.title}”)" for item in items]
        if len(bits) == 2:
            named = f"{bits[0]} and {bits[1]}"
        else:
            named = ", ".join(bits[:-1]) + ", and " + bits[-1]
        return f"{named} cover this story with different headlines."
    note = " ".join(divergence_text.split())
    if note:
        return (
            "This story is single-sourced. "
            f"See how outlets differ in this edition: {note}"
        )
    return (
        "This story is single-sourced. "
        "See how outlets differ in the edition divergence note."
    )


def _story_block(
    *,
    headline: str,
    category: str,
    corroboration: float,
    items: tuple[HeadlineItem, ...],
    divergence_text: str,
) -> StoryBlock:
    return StoryBlock(
        headline=headline,
        category=category,
        corroboration=corroboration,
        items=items,
        dek=items[0].title,
        outlet_count=len({item.source_id for item in items}),
        meanings=tuple(
            FramingNote(outlet=item.source_name, sentence=_meaning_sentence(item))
            for item in items
        ),
        differ_line=_differ_line(items, divergence_text),
    )


def _mark_lead(blocks: list[StoryBlock]) -> list[StoryBlock]:
    """Highest corroboration spans the broadsheet; a tie stays with the first block."""
    if not blocks:
        return blocks
    lead_at = max(range(len(blocks)), key=lambda i: (blocks[i].corroboration, -i))
    return [
        replace(block, is_lead=True) if i == lead_at else block
        for i, block in enumerate(blocks)
    ]


def _build_trending(
    articles: list[Article],
    sources: dict[str, Source],
) -> tuple[TrendingSource, ...]:
    if not articles:
        enabled = list(sources.values())
        if not enabled:
            return ()
        rows = [
            TrendingSource(
                source_id=s.id,
                name=s.name,
                article_count=0,
                share_pct=0.0,
                reliability=s.reliability_score,
                spectrum_tags=tuple(s.spectrum_tags),
                trending=False,
            )
            for s in sorted(enabled, key=lambda x: x.name)
        ]
        return tuple(rows)

    counts = Counter(a.source_id for a in articles)
    total = sum(counts.values()) or 1
    max_count = max(counts.values())
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    out: list[TrendingSource] = []
    for source_id, count in ranked:
        src = sources.get(source_id)
        name = src.name if src else source_id
        reliability = src.reliability_score if src else 1.0
        tags = tuple(src.spectrum_tags) if src else ()
        out.append(
            TrendingSource(
                source_id=source_id,
                name=name,
                article_count=count,
                share_pct=round(100 * count / total, 1),
                reliability=reliability,
                spectrum_tags=tags,
                trending=count == max_count and count > 0,
            )
        )
    return tuple(out)


def build_digest_view(store: Any, draft: DigestDraft | None) -> DigestView | None:
    sources = _sources_map(store)
    articles = store.list_articles()
    trending = _build_trending(articles, sources)

    if draft is None:
        return None

    stories_by_id: dict[UUID, Story] = {s.id: s for s in store.list_stories()}
    articles_by_id: dict[UUID, Article] = {a.id: a for a in articles}
    divergence_text = _strip_md_heading(draft.divergence_md)

    blocks: list[StoryBlock] = []
    for story_id in draft.story_ids:
        story = stories_by_id.get(story_id)
        if story is None:
            continue
        cluster_arts = [
            articles_by_id[aid]
            for aid in story.article_ids
            if aid in articles_by_id
        ]
        if not cluster_arts:
            continue
        category = _story_category(cluster_arts, sources)
        items = tuple(_headline_item(a, sources) for a in cluster_arts)
        blocks.append(
            _story_block(
                headline=story.title_hint,
                category=category,
                corroboration=story.corroboration_score,
                items=items,
                divergence_text=divergence_text,
            )
        )

    # Fallback: spine-only articles not tied to a listed story
    if not blocks and articles:
        reporting = [a for a in articles if a.quarantine_reason is None]
        if reporting:
            category = _story_category(reporting, sources)
            items = tuple(_headline_item(a, sources) for a in reporting[:12])
            blocks.append(
                _story_block(
                    headline="Today's reporting",
                    category=category,
                    corroboration=0.0,
                    items=items,
                    divergence_text=divergence_text,
                )
            )

    blocks = _mark_lead(blocks)

    by_cat: dict[str, list[StoryBlock]] = defaultdict(list)
    for block in blocks:
        by_cat[block.category].append(block)

    ordered_titles = list(CATEGORY_ORDER) + sorted(
        k for k in by_cat if k not in CATEGORY_ORDER
    )
    sections: list[CategorySection] = []
    for title in ordered_titles:
        stories_in_cat = by_cat.get(title)
        if not stories_in_cat:
            continue
        sections.append(
            CategorySection(title=title, stories=tuple(stories_in_cat))
        )

    edition = _edition_label(draft.created_at)

    return DigestView(
        edition_label=edition,
        sections=tuple(sections),
        divergence_text=divergence_text,
        events=tuple(draft.events),
        perspectives=tuple(draft.perspectives),
        trending=trending,
        validation_status=draft.validation_status,
    )


def build_sources_only_view(store: Any) -> DigestView:
    """Edition shell with trending rail when no digest draft exists yet."""
    sources = _sources_map(store)
    articles = store.list_articles()
    return DigestView(
        edition_label=_edition_label_fallback(),
        sections=(),
        divergence_text="",
        events=(),
        perspectives=(),
        trending=_build_trending(articles, sources),
        validation_status=None,
    )