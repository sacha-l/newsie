"""Event identity and the event board.

An embedding can propose that two articles belong together. It cannot decide it.
A join also needs a shared occurrence: the same actors, place, or wording.
A rejected proposal stays visible as a note so a person can review it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from newsie.domain import Article, DigestDraft, Source, Story

_TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß]{4,}")
_STOP = frozenset(
    {
        "aber",
        "auch",
        "beim",
        "berlin",
        "dass",
        "denn",
        "diese",
        "dieser",
        "dieses",
        "eine",
        "einem",
        "einen",
        "einer",
        "fuer",
        "für",
        "haben",
        "heute",
        "ihre",
        "ihren",
        "ihrer",
        "kann",
        "mehr",
        "nach",
        "nicht",
        "noch",
        "oder",
        "sein",
        "sich",
        "sind",
        "sowie",
        "that",
        "this",
        "und",
        "wird",
        "with",
        "from",
        "have",
        "been",
    }
)
_ACTORS = (
    "afd",
    "bsw",
    "bundestag",
    "bundesregierung",
    "cdu",
    "csu",
    "fdp",
    "grüne",
    "gruene",
    "linke",
    "senat",
    "spd",
)
_PLACES = (
    "berlin",
    "brandenburg",
    "deutschland",
    "germany",
    "hamburg",
    "köln",
    "koeln",
    "münchen",
    "muenchen",
)


@dataclass(frozen=True)
class JoinDecision:
    join: bool
    reason: str
    confidence: float
    actors: tuple[str, ...]
    location: str


def content_tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN.findall(text) if token.lower() not in _STOP}


def occurrence_overlap(left: str, right: str) -> tuple[float, list[str]]:
    first = content_tokens(left)
    second = content_tokens(right)
    if not first or not second:
        return 0.0, []
    shared = sorted(first & second)
    return len(shared) / len(first | second), shared


def same_event_text(left: str, right: str) -> bool:
    """True when two texts describe one occurrence, not merely a nearby topic."""
    score, shared = occurrence_overlap(left, right)
    return len(shared) >= 3 or score >= 0.18


def facets_of(text: str) -> tuple[tuple[str, ...], str]:
    lowered = text.lower()
    actors = tuple(name for name in _ACTORS if name in lowered)
    location = next((place for place in _PLACES if place in lowered), "")
    return actors, location


def describe_join(
    article: Article,
    story: Story,
    members: list[Article],
    score: float,
) -> JoinDecision:
    story_text = " ".join(
        [story.title_hint, *[f"{member.title} {member.body_text()[:500]}" for member in members]]
    )
    article_text = f"{article.title} {article.body_text()[:500]}"
    overlap, shared = occurrence_overlap(article_text, story_text)
    actors, location = facets_of(f"{story_text} {article_text}")
    if len(shared) >= 3 or overlap >= 0.18:
        shown = ", ".join(shared[:5])
        return JoinDecision(
            True,
            f"same occurrence ({shown}); similarity {score:.2f}",
            0.85,
            actors,
            location,
        )
    return JoinDecision(
        False,
        f"similarity {score:.2f} rejected; no shared occurrence",
        0.4,
        actors,
        location,
    )


def _sample_line(members: list[Article], sources: dict[str, Source]) -> str:
    names = []
    for source_id in sorted({article.source_id for article in members}):
        source = sources.get(source_id)
        names.append(source.name if source else source_id)
    count = len(members)
    publishers = len(names)
    noun = "article" if count == 1 else "articles"
    voice = "publisher" if publishers == 1 else "publishers"
    listed = ", ".join(names) if names else "no publisher recorded"
    return (
        f"In this collected sample: {count} {noun} from {publishers} {voice} ({listed}). "
        "This is not a measure of all coverage."
    )


@dataclass(frozen=True)
class ArticleTick:
    name: str
    title: str
    url: str
    when_label: str
    offset_pct: float


@dataclass(frozen=True)
class EventRow:
    title: str
    article_count: int
    publisher_count: int
    origin_count: int
    confidence: float
    notes: tuple[str, ...]
    known: tuple[str, ...]
    claimed: tuple[str, ...]
    differ: tuple[str, ...]
    unclear: tuple[str, ...]
    reporting: str
    ticks: tuple[ArticleTick, ...]


@dataclass(frozen=True)
class EventBoard:
    sample_note: str
    rows: tuple[EventRow, ...]
    verdicts: tuple[tuple[str, int], ...]


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _ticks(members: list[Article], sources: dict[str, Source]) -> tuple[ArticleTick, ...]:
    if not members:
        return ()
    moments = [_aware(article.published_at or article.retrieved_at) for article in members]
    start = min(moments)
    span = (max(moments) - start).total_seconds()
    ticks: list[ArticleTick] = []
    for index, article in enumerate(members):
        when = moments[index]
        offset = (
            ((index + 1) / (len(members) + 1)) * 100
            if span <= 0
            else ((when - start).total_seconds() / span) * 100
        )
        source = sources.get(article.source_id)
        ticks.append(
            ArticleTick(
                name=source.name if source else article.source_id,
                title=article.title,
                url=article.canonical_url or article.url,
                when_label=when.strftime("%d %b %H:%M"),
                offset_pct=max(2.0, min(98.0, offset)),
            )
        )
    return tuple(ticks)


def _reason(note: str) -> str:
    head, sep, tail = note.partition(": ")
    if sep and len(head) > 20:
        return tail
    return note


def build_event_board(
    *,
    stories: list[Story],
    articles: list[Article],
    sources: dict[str, Source],
    draft: DigestDraft | None,
    limit: int = 8,
) -> EventBoard:
    by_id = {article.id: article for article in articles}
    chosen = list(stories)
    if draft is not None and draft.story_ids:
        wanted = set(draft.story_ids)
        chosen = [story for story in stories if story.id in wanted] or chosen
    chosen = chosen[:limit]
    sentences = draft.sentences if draft is not None else []
    if draft is not None and articles:
        from newsie.citations import validate_draft

        sentences = validate_draft(draft, articles).sentences or sentences
    rows: list[EventRow] = []
    for story in chosen:
        members = [by_id[article_id] for article_id in story.article_ids if article_id in by_id]
        story_sentences = [row for row in sentences if row.story_id == story.id]
        known = tuple(
            row.text for row in story_sentences if row.section in {"spine", "known", "happening"}
        )
        claimed = tuple(row.text for row in story_sentences if row.section in {"view", "claimed"})
        differ = tuple(row.text for row in story_sentences if row.section == "differ")
        unclear = tuple(row.text for row in story_sentences if row.section == "unclear")
        reporting = next(
            (row.text for row in story_sentences if row.section == "reporting"),
            _sample_line(members, sources),
        )
        if not differ:
            differ = ("No recorded disagreement in this collected sample.",)
        if not unclear:
            unclear = ("Nothing in this sample is marked unverified.",)
        if not known:
            known = (story.title_hint,)
        origins = {article.origin_id or f"source:{article.source_id}" for article in members}
        rows.append(
            EventRow(
                title=story.title_hint,
                article_count=len(members),
                publisher_count=len({article.source_id for article in members}),
                origin_count=len(origins),
                confidence=story.resolution_confidence,
                notes=tuple(_reason(note) for note in story.assignment_notes[:6]),
                known=known[:4],
                claimed=claimed[:4] or ("No attributed claim is recorded.",),
                differ=differ[:4],
                unclear=unclear[:4],
                reporting=reporting,
                ticks=_ticks(members, sources),
            )
        )
    counts: dict[str, int] = {}
    for row in sentences:
        if row.section in {"note", "unclear", "reporting"}:
            continue
        counts[row.support_verdict or "unchecked"] = (
            counts.get(row.support_verdict or "unchecked", 0) + 1
        )
    verdicts = tuple(sorted(counts.items()))
    return EventBoard(
        sample_note=(
            "Counts are articles, publishers, and independent origins inside "
            "Newsie's collected sample. They are not public attention or opinion."
        ),
        rows=tuple(rows),
        verdicts=verdicts,
    )
