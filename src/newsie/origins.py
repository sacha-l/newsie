"""Origin detection — agency credit, publisher group, and near-duplicate text.

An origin is the independent source of a report. Wire copies and outlets in one
publisher group count once. Social-signal items still receive an origin id, and
later counting excludes that tier.
"""

from __future__ import annotations

import re
from uuid import UUID

from newsie.domain import Article, Source
from newsie.guardrails import LoopGuard

_AGENCY = re.compile(r"\b(dpa|AFP|Reuters|AP|SID)\b")
_WORD = re.compile(r"\w+", re.UNICODE)


def parse_agency(text: str) -> str | None:
    match = _AGENCY.search(text)
    if match is None:
        return None
    return match.group(1).lower()


def shingles(text: str, n: int = 5) -> set[str]:
    words = _WORD.findall(text.lower())
    if not words:
        return set()
    if len(words) < n:
        return {" ".join(words)}
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def char_trigrams(text: str) -> set[str]:
    """Cheap title similarity. The Postgres path is pg_trgm; this is the same idea."""
    folded = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in text)
    compact = " ".join(folded.split())
    if len(compact) < 3:
        return {compact} if compact else set()
    return {compact[i : i + 3] for i in range(len(compact) - 2)}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _lead(article: Article) -> str:
    words = article.body_text().split()
    return f"{article.title} {' '.join(words[:80])}"


def _provisional(article: Article, sources: dict[str, Source], credit: str | None) -> str:
    if credit:
        return f"agency:{credit}"
    source = sources.get(article.source_id)
    if source is not None and source.publisher_group:
        return f"group:{source.publisher_group}"
    return f"source:{article.source_id}"


def assign_origins(
    articles: list[Article],
    sources: dict[str, Source],
    *,
    jaccard_threshold: float = 0.8,
    neighbor_window: int = 30,
) -> list[Article]:
    """Return articles with origin_id and agency_credit set. Input order is preserved."""
    if not articles:
        return []
    guard = LoopGuard(
        max_iterations=len(articles) * (neighbor_window + 2) * 2 + 10,
        name="origins",
    )
    credits = [parse_agency(f"{a.title}\n{a.body_text()}") for a in articles]
    labels = [_provisional(a, sources, credit) for a, credit in zip(articles, credits, strict=True)]
    parent = list(range(len(articles)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    by_agency: dict[str, int] = {}
    for index, credit in enumerate(credits):
        guard.tick()
        if credit is None:
            continue
        prior = by_agency.get(credit)
        if prior is None:
            by_agency[credit] = index
        else:
            union(prior, index)

    titles = [char_trigrams(article.title) for article in articles]
    ordered_titles = sorted(range(len(articles)), key=lambda i: articles[i].retrieved_at)
    for pos, index in enumerate(ordered_titles):
        guard.tick()
        title_words = articles[index].title.split()
        if len(title_words) < 4:
            continue
        for other in ordered_titles[pos + 1 : pos + 1 + neighbor_window]:
            guard.tick()
            if len(articles[other].title.split()) < 4:
                continue
            if jaccard(titles[index], titles[other]) >= jaccard_threshold:
                union(index, other)

    leads = [shingles(_lead(article)) for article in articles]
    ordered = sorted(range(len(articles)), key=lambda i: articles[i].retrieved_at)
    for pos, index in enumerate(ordered):
        guard.tick()
        for other in ordered[pos + 1 : pos + 1 + neighbor_window]:
            guard.tick()
            if jaccard(leads[index], leads[other]) >= jaccard_threshold:
                union(index, other)

    groups: dict[int, list[int]] = {}
    for index in range(len(articles)):
        groups.setdefault(find(index), []).append(index)

    origin_by_index: dict[int, str] = {}
    for members in groups.values():
        group_credits = {credits[i] for i in members if credits[i]}
        if len(group_credits) == 1:
            origin = f"agency:{next(iter(group_credits))}"
        elif len(members) > 1 and len({labels[i] for i in members}) > 1:
            anchor = min(articles[i].content_hash for i in members)
            origin = f"dup:{anchor}"
        else:
            origin = labels[members[0]]
        for index in members:
            origin_by_index[index] = origin

    updated: list[Article] = []
    for index, article in enumerate(articles):
        updated.append(
            article.model_copy(
                update={
                    "origin_id": origin_by_index[index],
                    "agency_credit": credits[index],
                }
            )
        )
    return updated


def origin_map(articles: list[Article]) -> dict[UUID, str]:
    return {article.id: article.origin_id or f"source:{article.source_id}" for article in articles}
