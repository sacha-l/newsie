"""Public social feeds fetched on request.

Post text is untrusted data. It is a signal, never evidence, and it is never executed.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import httpx

from newsie.domain import SocialPost

BERLIN = ZoneInfo("Europe/Berlin")
MAX_CALLS = 3
MAX_POSTS = 40
MAX_SHOWN = 8
_WINDOWS: tuple[tuple[str, str, int], ...] = (
    ("hour", "Last hour", 1),
    ("twelve", "Last 12 hours", 12),
    ("day", "Last 24 hours", 24),
)
_TEXT = 240

_TAGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ukraine", ("ukraine",)),
    ("miete", ("miete", "rent", "rents")),
    ("energie", ("energie", "energy")),
    ("ki", ("ki", "ai", "copilot")),
    ("berlin", ("berlin",)),
    ("politik", ("politik", "senate", "bundestag", "coalition", "koalition")),
)
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
    "On request, Newsie read up to two public Mastodon tag feeds and one public "
    "Bluesky search for words already on this page. Each feed returns its latest "
    "40 posts. Last hour, last 12 hours, and last 24 hours are three views of that "
    "same fetch; posts older than 24 hours are left out. HTML was stripped. No model "
    "rewrote the posts. These posts do not count toward origins or evidence labels."
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
class SocialWindow:
    key: str
    label: str
    summary: str
    posts: tuple[SocialCard, ...]
    total: int


@dataclass(frozen=True)
class SocialBrief:
    fetched_label: str
    summary: str
    how: str
    posts: tuple[SocialCard, ...]
    notes: tuple[str, ...]
    windows: tuple[SocialWindow, ...] = ()


def stamp(when: datetime) -> str:
    local = when.astimezone(BERLIN)
    return f"{local:%A,} {local.day} {local:%B %Y}, {local:%H:%M} Europe/Berlin"


def select_tags(texts: list[str], *, limit: int = 2) -> list[str]:
    """Pick feed tags from headlines already on the page. Two feeds at most."""
    blob = " ".join(texts).lower()
    chosen = [tag for tag, words in _TAGS if any(_has_word(blob, word) for word in words)]
    if not chosen:
        chosen = ["politik", "berlin"]
    return chosen[:limit]


def plain_text(raw: str) -> str:
    text = _HTML.sub(" ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_TEXT]


def posts_from_mastodon(
    payload: object, *, tag: str, retrieved_at: datetime
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
        if len(found) >= MAX_POSTS:
            break
    return found


def posts_from_bsky(
    payload: object, *, tag: str, retrieved_at: datetime
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
        if len(found) >= MAX_POSTS:
            break
    return found


def fetch_social(
    texts: list[str],
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> SocialBrief:
    """Fetch a bounded set of public posts. Failures stay notes, not exceptions."""
    moment = now or datetime.now(UTC)
    tags = select_tags(texts)
    notes: list[str] = []
    rows: list[tuple[SocialPost, str]] = []
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
        for tag in tags:
            if calls >= MAX_CALLS:
                break
            url = f"https://mastodon.de/api/v1/timelines/tag/{quote(tag)}?limit={MAX_POSTS}"
            calls += 1
            payload, note = _get_json(http, url)
            if note:
                notes.append(note)
            elif payload is not None:
                rows.extend(posts_from_mastodon(payload, tag=tag, retrieved_at=moment))
        if calls < MAX_CALLS:
            query = quote(" ".join(tags))
            since = quote((moment - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"))
            url = (
                "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
                f"?q={query}&sort=latest&since={since}&limit={MAX_POSTS}"
            )
            calls += 1
            payload, note = _get_json(http, url)
            if note:
                notes.append(note)
            elif payload is not None:
                rows.extend(posts_from_bsky(payload, tag=" ".join(tags), retrieved_at=moment))
    finally:
        if owns:
            http.close()
    return _brief(rows, moment, notes)


def _brief(rows: list[tuple[SocialPost, str]], when: datetime, notes: list[str]) -> SocialBrief:
    seen: set[tuple[str, str]] = set()
    fresh: list[tuple[SocialPost, str, timedelta]] = []
    moment = _aware(when)
    for post, url in rows:
        key = (post.platform, post.external_id)
        if key in seen:
            continue
        seen.add(key)
        age = moment - _aware(post.retrieved_at)
        if age < timedelta(0):
            age = timedelta(0)
        if age > timedelta(hours=24):
            continue
        fresh.append((post, url, age))
    fresh.sort(key=lambda item: item[2])
    windows = tuple(_window(key, label, hours, fresh) for key, label, hours in _WINDOWS)
    day = windows[-1]
    return SocialBrief(
        fetched_label=stamp(when),
        summary=_summary([post for post, _url, _age in fresh], windows),
        how=_HOW,
        posts=day.posts,
        notes=tuple(notes),
        windows=windows,
    )


def _window(
    key: str,
    label: str,
    hours: int,
    fresh: list[tuple[SocialPost, str, timedelta]],
) -> SocialWindow:
    chosen = [(post, url) for post, url, age in fresh if age <= timedelta(hours=hours)]
    cards = tuple(_card(post, url) for post, url in chosen[:MAX_SHOWN])
    return SocialWindow(
        key=key,
        label=label,
        summary=_window_summary(label, [post for post, _url in chosen], shown=len(cards)),
        posts=cards,
        total=len(chosen),
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


def _summary(posts: list[SocialPost], windows: tuple[SocialWindow, ...]) -> str:
    if not posts:
        return (
            "No public posts from the last 24 hours came back for this request. "
            "Nothing was added to the edition."
        )
    counts = {window.key: window.total for window in windows}
    noun = "post" if len(posts) == 1 else "posts"
    return (
        f"{len(posts)} {noun} from the last 24 hours. "
        f"{counts.get('hour', 0)} in the last hour, and "
        f"{counts.get('twelve', 0)} in the last 12 hours. "
        "This is a social signal from those feeds, not evidence, and it does not "
        "change the edition."
    )


def _window_summary(label: str, posts: list[SocialPost], *, shown: int) -> str:
    if not posts:
        return f"No posts in the {label.lower()} from this fetch."
    counts = Counter(post.topic for post in posts)
    bits = ", ".join(f"{tag} {count}" for tag, count in counts.most_common())
    noun = "post" if len(posts) == 1 else "posts"
    words: Counter[str] = Counter()
    for post in posts:
        for word in _WORD.findall(post.text.lower()):
            if word not in _STOP:
                words[word] += 1
    top = [word for word, count in words.most_common(6) if count > 1]
    recurring = f" Words that repeat: {', '.join(top)}." if top else ""
    hidden = f" Showing {shown} of {len(posts)}." if shown < len(posts) else ""
    return f"{len(posts)} {noun} in the {label.lower()} ({bits}).{recurring}{hidden}"


def _aware(when: datetime) -> datetime:
    if when.tzinfo is None:
        return when.replace(tzinfo=UTC)
    return when


def _has_word(blob: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", blob) is not None


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
