"""Public social feeds fetched on request.

Post text is untrusted data. It is a signal, never evidence, and it is never executed.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import httpx

from newsie.domain import SocialPost

BERLIN = ZoneInfo("Europe/Berlin")
MAX_CALLS = 6
MIN_POSTS = 3
MAX_TOPICS = 4
POSTS_PER_TOPIC = 5
MAX_POSTS = 40
_BSKY = "https://api.bsky.app"
_TEXT = 240

_STOP = frozenset(
    {
        "und",
        "der",
        "die",
        "das",
        "ein",
        "eine",
        "ist",
        "nicht",
        "mit",
        "von",
        "für",
        "fur",
        "auf",
        "den",
        "dem",
        "des",
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
        "http",
        "https",
    }
)
_HTML = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[a-zA-ZäöüÄÖÜß]{4,}")

_HOW = (
    "On request, Newsie read the public Bluesky trend list and the public Mastodon "
    "trending tags, then the posts for those topics. A topic is shown only when at "
    "least 3 posts came back. The Bluesky line is the description that trend list "
    "sent. The Mastodon line is the words those posts repeat. No model rewrote them. "
    "These posts do not count toward origins or evidence labels."
)


@dataclass(frozen=True)
class SocialCard:
    handle: str
    platform: str
    when_label: str
    text: str
    url: str
    tag: str


@dataclass(frozen=True)
class SocialTopic:
    name: str
    summary: str
    platform: str
    count_label: str
    posts: tuple[SocialCard, ...]


@dataclass(frozen=True)
class SocialBrief:
    fetched_label: str
    summary: str
    how: str
    posts: tuple[SocialCard, ...]
    notes: tuple[str, ...]
    topics: tuple[SocialTopic, ...] = ()


def stamp(when: datetime) -> str:
    local = when.astimezone(BERLIN)
    return f"{local:%A,} {local.day} {local:%B %Y}, {local:%H:%M} Europe/Berlin"


def plain_text(raw: str) -> str:
    text = _HTML.sub(" ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_TEXT]


def feed_uri(link: str) -> str:
    """Turn a Bluesky trend link into the feed address getFeed expects."""
    parts = [part for part in link.strip("/").split("/") if part]
    if len(parts) >= 4 and parts[0] == "profile" and parts[2] == "feed":
        return f"at://{parts[1]}/app.bsky.feed.generator/{parts[3]}"
    return ""


def posts_from_mastodon(
    payload: object, *, tag: str, retrieved_at: datetime, limit: int = MAX_POSTS
) -> list[tuple[SocialPost, str]]:
    if not isinstance(payload, list):
        return []
    found: list[tuple[SocialPost, str]] = []
    for row in payload:
        if not isinstance(row, dict) or row.get("reblog"):
            continue
        item = _mastodon_row(row, tag=tag, retrieved_at=retrieved_at)
        if item is not None:
            found.append(item)
        if len(found) >= limit:
            break
    return found


def posts_from_bsky(
    payload: object, *, tag: str, retrieved_at: datetime, limit: int = MAX_POSTS
) -> list[tuple[SocialPost, str]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("posts")
    if not isinstance(rows, list):
        return []
    found: list[tuple[SocialPost, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = _bsky_row(row, tag=tag, retrieved_at=retrieved_at)
        if item is not None:
            found.append(item)
        if len(found) >= limit:
            break
    return found


def posts_from_bsky_feed(
    payload: object, *, tag: str, retrieved_at: datetime, limit: int = POSTS_PER_TOPIC
) -> list[tuple[SocialPost, str]]:
    if not isinstance(payload, dict):
        return []
    rows: list[object] = []
    feed = payload.get("feed")
    if not isinstance(feed, list):
        return []
    for item in feed:
        post = item.get("post") if isinstance(item, dict) else None
        if isinstance(post, dict):
            rows.append(post)
    return posts_from_bsky({"posts": rows}, tag=tag, retrieved_at=retrieved_at, limit=limit)


def fetch_social(
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> SocialBrief:
    """Read trending topics, then the posts for each. Failures stay notes."""
    moment = now or datetime.now(UTC)
    notes: list[str] = []
    topics: list[SocialTopic] = []
    owns = client is None
    http = client or httpx.Client(
        timeout=8.0,
        follow_redirects=True,
        headers={
            "User-Agent": "Newsie/0.1 (+https://github.com/sacha-l/newsie)",
            "Accept": "application/json",
        },
    )
    calls = 0
    try:
        calls += 1
        trends, note = _get_json(http, f"{_BSKY}/xrpc/app.bsky.unspecced.getTrends?limit=8")
        if note:
            notes.append(note)
        calls += 1
        tags, tag_note = _get_json(http, "https://mastodon.de/api/v1/trends/tags?limit=8")
        if tag_note:
            notes.append(tag_note)
        for name, summary, feed, count in _bsky_trends(trends)[:2]:
            if calls >= MAX_CALLS or len(topics) >= MAX_TOPICS:
                break
            calls += 1
            quoted = quote(feed, safe="")
            url = f"{_BSKY}/xrpc/app.bsky.feed.getFeed?feed={quoted}&limit={POSTS_PER_TOPIC}"
            payload, feed_note = _get_json(http, url)
            if feed_note:
                notes.append(feed_note)
                continue
            topic = _topic_from_posts(
                name=name,
                summary=summary,
                platform="bluesky",
                count=count,
                rows=posts_from_bsky_feed(payload, tag=name, retrieved_at=moment),
            )
            if topic is not None:
                topics.append(topic)
        for name, count in _mastodon_trends(tags)[:2]:
            if calls >= MAX_CALLS or len(topics) >= MAX_TOPICS:
                break
            calls += 1
            url = f"https://mastodon.de/api/v1/timelines/tag/{quote(name)}?limit={POSTS_PER_TOPIC}"
            payload, feed_note = _get_json(http, url)
            if feed_note:
                notes.append(feed_note)
                continue
            rows = posts_from_mastodon(
                payload, tag=name, retrieved_at=moment, limit=POSTS_PER_TOPIC
            )
            topic = _topic_from_posts(
                name=f"#{name}",
                summary=_thing_summary(name, [post for post, _url in rows]),
                platform="mastodon",
                count=count,
                rows=rows,
            )
            if topic is not None:
                topics.append(topic)
    finally:
        if owns:
            http.close()
    return _brief(topics, moment, notes)


def _bsky_trends(payload: object) -> list[tuple[str, str, str, int]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("trends"), list):
        return []
    found: list[tuple[str, str, str, int]] = []
    for row in payload["trends"]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("displayName") or "").strip()
        summary = plain_text(str(row.get("description") or ""))
        feed = feed_uri(str(row.get("link") or ""))
        count = _as_int(row.get("postCount"))
        if name and summary and feed and count >= MIN_POSTS:
            found.append((name, summary, feed, count))
    return found


def _mastodon_trends(payload: object) -> list[tuple[str, int]]:
    if not isinstance(payload, list):
        return []
    found: list[tuple[str, int]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        history = row.get("history")
        uses = _trend_uses(history)
        if name and uses >= MIN_POSTS:
            found.append((name, uses))
    return found


def _topic_from_posts(
    *,
    name: str,
    summary: str,
    platform: str,
    count: int,
    rows: list[tuple[SocialPost, str]],
) -> SocialTopic | None:
    cards: list[SocialCard] = []
    seen: set[str] = set()
    for post, url in rows:
        if post.external_id in seen:
            continue
        seen.add(post.external_id)
        cards.append(_card(post, url))
        if len(cards) >= POSTS_PER_TOPIC:
            break
    if len(cards) < MIN_POSTS:
        return None
    shown = len(cards)
    label = f"{count} posts on this trend. {shown} to read."
    return SocialTopic(
        name=name,
        summary=summary,
        platform=platform,
        count_label=label,
        posts=tuple(cards),
    )


def _thing_summary(name: str, posts: list[SocialPost]) -> str:
    words = _repeated(posts)
    if words:
        return f"People are posting about #{name}. The posts mention {', '.join(words)}."
    return f"People are posting about #{name}."


def _repeated(posts: list[SocialPost]) -> list[str]:
    counts: Counter[str] = Counter()
    for post in posts:
        counts.update(set(_WORD.findall(post.text.lower())) - _STOP)
    return [word for word, count in counts.most_common(5) if count >= 2]


def _brief(topics: list[SocialTopic], when: datetime, notes: list[str]) -> SocialBrief:
    posts = tuple(post for topic in topics for post in topic.posts)
    if not topics:
        summary = (
            "No trending topic came back with at least 3 posts. Nothing was added to the edition."
        )
    else:
        noun = "topic" if len(topics) == 1 else "topics"
        summary = (
            f"{len(topics)} trending {noun}, each with at least 3 posts. "
            "This is a social signal, not evidence, and it does not change the edition."
        )
    return SocialBrief(
        fetched_label=stamp(when),
        summary=summary,
        how=_HOW,
        posts=posts,
        notes=tuple(notes),
        topics=tuple(topics),
    )


def _card(post: SocialPost, url: str) -> SocialCard:
    return SocialCard(
        handle=post.author_handle or "unknown",
        platform=post.platform,
        when_label=stamp(post.retrieved_at),
        text=post.text,
        url=url if url.startswith("https://") else "",
        tag=post.topic,
    )


def _trend_uses(history: object) -> int:
    if not isinstance(history, list):
        return 0
    return max(
        (_as_int(item.get("uses")) for item in history if isinstance(item, dict)),
        default=0,
    )


def _mastodon_row(
    row: dict[str, Any], *, tag: str, retrieved_at: datetime
) -> tuple[SocialPost, str] | None:
    text = plain_text(str(row.get("content") or ""))
    external_id = str(row.get("id") or "").strip()
    if not text or not external_id:
        return None
    account = _mapping(row.get("account"))
    url = str(row.get("url") or "")
    return (
        SocialPost(
            platform="mastodon",
            external_id=external_id,
            author_handle=str(account.get("acct") or ""),
            text=text,
            reach=_as_int(row.get("favourites_count")),
            topic=tag,
            retrieved_at=_when(row.get("created_at"), retrieved_at),
        ),
        url,
    )


def _bsky_row(
    row: dict[str, Any], *, tag: str, retrieved_at: datetime
) -> tuple[SocialPost, str] | None:
    record = _mapping(row.get("record"))
    text = plain_text(str(record.get("text") or ""))
    external_id = str(row.get("uri") or "").strip()
    if not text or not external_id:
        return None
    author = _mapping(row.get("author"))
    handle = str(author.get("handle") or "")
    url = f"https://bsky.app/profile/{handle}/post/{external_id.rsplit('/', 1)[-1]}"
    if not handle:
        url = ""
    return (
        SocialPost(
            platform="bluesky",
            external_id=external_id,
            author_handle=handle,
            text=text,
            reach=_as_int(row.get("likeCount")),
            topic=tag,
            retrieved_at=_when(row.get("indexedAt"), retrieved_at),
        ),
        url,
    )


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _when(value: object, fallback: datetime) -> datetime:
    if not isinstance(value, str) or not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _get_json(http: httpx.Client, url: str) -> tuple[object | None, str]:
    host = urlsplit(url).netloc
    try:
        response = http.get(url)
    except httpx.HTTPError:
        return None, f"{host} did not answer"
    if response.status_code != 200:
        return None, f"{host} returned HTTP {response.status_code}"
    try:
        body: object = response.json()
    except ValueError:
        return None, f"{host} did not return JSON"
    return body, ""
