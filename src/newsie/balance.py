"""Per-digest balance — share of articles and of supporting origins by spectrum."""

from __future__ import annotations

from collections import Counter
from typing import Any

from newsie.domain import Article, ClaimEvidence, Source, SourceTier, Stance, Story


def _share(counts: Counter[str]) -> dict[str, float]:
    total = sum(counts.values()) or 1
    return {key: round(100 * value / total, 1) for key, value in sorted(counts.items())}


def balance_report(
    stories: list[Story],
    articles_by_id: dict[Any, Any],
    sources: dict[str, Source],
    evidence: list[ClaimEvidence],
) -> str:
    article_counts: Counter[str] = Counter()
    for article in articles_by_id.values():
        if not isinstance(article, Article):
            continue
        if article.tier_at_ingest == SourceTier.SOCIAL_SIGNAL:
            continue
        source = sources.get(article.source_id)
        article_counts[source.spectrum.value if source else "untagged"] += 1

    origin_spectrum: dict[str, str] = {}
    for row in evidence:
        if row.stance != Stance.SUPPORTS:
            continue
        article = articles_by_id.get(row.article_id)
        if article is None or article.tier_at_ingest == SourceTier.SOCIAL_SIGNAL:
            continue
        source = sources.get(article.source_id)
        origin_spectrum[row.origin_id] = source.spectrum.value if source else "untagged"
    origin_counts: Counter[str] = Counter(origin_spectrum.values())

    lines = [
        "Balance",
        "Labels describe how widely something is reported, not whether it is true.",
        "Articles by spectrum: "
        + (", ".join(f"{key} {value}%" for key, value in _share(article_counts).items()) or "none"),
        "Supporting origins by spectrum: "
        + (", ".join(f"{key} {value}%" for key, value in _share(origin_counts).items()) or "none"),
    ]
    articles = {
        article.id: article for article in articles_by_id.values() if isinstance(article, Article)
    }
    for story in stories:
        spectra = {
            sources[articles[aid].source_id].spectrum.value
            for aid in story.article_ids
            if aid in articles
            and articles[aid].source_id in sources
            and articles[aid].tier_at_ingest != SourceTier.SOCIAL_SIGNAL
        }
        if len(spectra) == 1:
            only = next(iter(spectra))
            lines.append(f"Warning: {story.title_hint} draws on one spectrum group ({only}).")
    return "\n".join(lines)
