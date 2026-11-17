from __future__ import annotations

from datetime import UTC, datetime, timedelta

from newsie.social_live import (
    fetch_social,
    plain_text,
    posts_from_bsky,
    posts_from_mastodon,
    select_tags,
)


def test_select_tags_uses_words_already_on_the_page() -> None:
    tags = select_tags(["Berlin Senate argues over a rent-cap reform"])
    assert tags == ["miete", "berlin"]


def test_select_tags_falls_back_to_two_feeds() -> None:
    assert select_tags(["Job cuts and severance"]) == ["politik", "berlin"]


def test_plain_text_strips_markup() -> None:
    assert plain_text("<p>Wetter &amp; Berlin<br>kalt</p>") == "Wetter & Berlin kalt"


def test_mastodon_skips_boosts_and_keeps_text() -> None:
    when = datetime(2026, 11, 17, tzinfo=UTC)
    rows = posts_from_mastodon(
        [
            {"id": "1", "reblog": {"id": "x"}, "content": "<p>boosted</p>"},
            {
                "id": "2",
                "content": "<p>Senat streitet über Miete</p>",
                "url": "https://mastodon.de/@desk/2",
                "created_at": "2026-11-17T01:01:02.000Z",
                "favourites_count": 3,
                "account": {"acct": "desk"},
            },
        ],
        tag="miete",
        retrieved_at=when,
    )
    assert len(rows) == 1
    post, url = rows[0]
    assert post.text == "Senat streitet über Miete"
    assert post.platform == "mastodon"
    assert url.startswith("https://")


def test_fetch_social_summarizes_without_calling_the_network(monkeypatch) -> None:
    def fake_get(http, url: str):  # type: ignore[no-untyped-def]
        if "mastodon" in url:
            return (
                [
                    {
                        "id": "9",
                        "content": "<p>Berlin Miete bleibt Streit</p>",
                        "url": "https://mastodon.de/@a/9",
                        "created_at": "2026-11-17T01:00:00.000Z",
                        "account": {"acct": "a"},
                    }
                ],
                "",
            )
        return ({"posts": []}, "public.api.bsky.app returned HTTP 403")

    monkeypatch.setattr("newsie.social_live._get_json", fake_get)
    brief = fetch_social(
        ["Berlin Senate argues over a rent-cap reform"],
        now=datetime(2026, 11, 17, 1, 5, tzinfo=UTC),
    )
    assert "not evidence" in brief.summary
    assert brief.posts[0].handle == "a"
    assert any("403" in note for note in brief.notes)
    assert "No model rewrote" in brief.how
    assert [window.label for window in brief.windows] == [
        "Last hour",
        "Last 12 hours",
        "Last 24 hours",
    ]
    assert all(window.total == 1 for window in brief.windows)


def test_windows_keep_posts_inside_each_span(monkeypatch) -> None:
    now = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)

    def row(post_id: str, when: datetime, text: str) -> dict[str, object]:
        return {
            "id": post_id,
            "content": f"<p>{text}</p>",
            "url": f"https://mastodon.de/@a/{post_id}",
            "created_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "account": {"acct": "a"},
        }

    payload = [
        row("1", now - timedelta(minutes=20), "Berlin Miete jetzt"),
        row("2", now - timedelta(hours=6), "Berlin Miete heute"),
        row("3", now - timedelta(hours=20), "Berlin Miete gestern"),
        row("4", now - timedelta(hours=30), "Berlin Miete alt"),
    ]

    def fake_get(http, url: str):  # type: ignore[no-untyped-def]
        if "mastodon" in url and "miete" in url:
            return payload, ""
        if "mastodon" in url:
            return [], ""
        return {"posts": []}, ""

    monkeypatch.setattr("newsie.social_live._get_json", fake_get)
    brief = fetch_social(["rent in Berlin"], now=now)
    totals = {window.key: window.total for window in brief.windows}
    assert totals == {"hour": 1, "twelve": 2, "day": 3}
    assert "alt" not in " ".join(post.text for post in brief.posts)


def test_bsky_search_uses_the_host_that_answers(monkeypatch) -> None:
    seen: list[str] = []

    def fake_get(http, url: str):  # type: ignore[no-untyped-def]
        seen.append(url)
        if "mastodon" in url:
            return [], ""
        if url.startswith("https://api.bsky.app/"):
            return (
                {
                    "posts": [
                        {
                            "uri": "at://did/app.bsky.feed.post/abc",
                            "indexedAt": "2026-11-17T01:02:00.000Z",
                            "author": {"handle": "desk.bsky.social"},
                            "record": {"text": "Berlin rent row"},
                        }
                    ]
                },
                "",
            )
        return None, "public.api.bsky.app returned HTTP 403"

    monkeypatch.setattr("newsie.social_live._get_json", fake_get)
    brief = fetch_social(
        ["Berlin rent"],
        now=datetime(2026, 11, 17, 1, 5, tzinfo=UTC),
    )
    assert any(url.startswith("https://api.bsky.app/") for url in seen)
    assert not any(url.startswith("https://public.api.bsky.app/") for url in seen)
    assert any(post.platform == "bluesky" for post in brief.posts)
    assert brief.notes == ()


def test_a_busy_mastodon_feed_does_not_hide_bluesky(monkeypatch) -> None:
    now = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)

    def mastodon_row(post_id: int) -> dict[str, object]:
        when = now - timedelta(minutes=post_id)
        return {
            "id": str(post_id),
            "content": f"<p>Berlin post {post_id}</p>",
            "url": f"https://mastodon.de/@a/{post_id}",
            "created_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "account": {"acct": "a"},
        }

    def fake_get(http, url: str):  # type: ignore[no-untyped-def]
        if "mastodon" in url and "berlin" in url:
            return [mastodon_row(i) for i in range(1, 12)], ""
        if "mastodon" in url:
            return [], ""
        return (
            {
                "posts": [
                    {
                        "uri": "at://did/app.bsky.feed.post/abc",
                        "indexedAt": (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "author": {"handle": "desk.bsky.social"},
                        "record": {"text": "Berlin on Bluesky"},
                    }
                ]
            },
            "",
        )

    monkeypatch.setattr("newsie.social_live._get_json", fake_get)
    brief = fetch_social(["Berlin"], now=now)
    assert any(post.platform == "bluesky" for post in brief.posts)


def test_bsky_record_becomes_a_post() -> None:
    rows = posts_from_bsky(
        {
            "posts": [
                {
                    "uri": "at://did/app.bsky.feed.post/abc",
                    "indexedAt": "2026-11-17T01:02:00.000Z",
                    "likeCount": 4,
                    "author": {"handle": "desk.bsky.social"},
                    "record": {"text": "Ukraine talks stall"},
                }
            ]
        },
        tag="ukraine",
        retrieved_at=datetime(2026, 11, 17, tzinfo=UTC),
    )
    assert rows[0][0].platform == "bluesky"
    assert rows[0][0].text == "Ukraine talks stall"
