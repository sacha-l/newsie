from __future__ import annotations

from datetime import UTC, datetime

from newsie.social_live import (
    feed_uri,
    fetch_social,
    plain_text,
    posts_from_bsky,
    posts_from_mastodon,
)


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


def test_feed_uri_uses_the_trend_link() -> None:
    link = "/profile/did:plc:abc/feed/topic1"
    assert feed_uri(link) == "at://did:plc:abc/app.bsky.feed.generator/topic1"


def _post(index: int, text: str) -> dict[str, object]:
    return {
        "uri": f"at://did/app.bsky.feed.post/{index}",
        "indexedAt": "2026-11-17T01:02:00.000Z",
        "author": {"handle": f"desk{index}.bsky.social"},
        "record": {"text": text},
    }


def test_a_trend_needs_three_posts_and_keeps_its_description(monkeypatch) -> None:
    def fake_get(http, url: str):  # type: ignore[no-untyped-def]
        if "getTrends" in url:
            return (
                {
                    "trends": [
                        {
                            "displayName": "Rent cap",
                            "description": "People argue about a Berlin rent cap.",
                            "link": "/profile/did:plc:abc/feed/rent",
                            "postCount": 40,
                        },
                        {
                            "displayName": "Thin",
                            "description": "Too few posts.",
                            "link": "/profile/did:plc:abc/feed/thin",
                            "postCount": 2,
                        },
                    ]
                },
                "",
            )
        if "trends/tags" in url:
            return [{"name": "miete", "history": [{"uses": "9"}, {"uses": "1"}]}], ""
        if "feed/rent" in url or "feed%2Frent" in url or "generator%2Frent" in url:
            return {"feed": [{"post": _post(i, "Berlin rent cap debate")} for i in range(3)]}, ""
        if "tag/miete" in url:
            return (
                [
                    {
                        "id": str(i),
                        "content": "<p>Berlin Miete Streit im Senat</p>",
                        "url": f"https://mastodon.de/@a/{i}",
                        "created_at": "2026-11-17T01:00:00.000Z",
                        "account": {"acct": "a"},
                    }
                    for i in range(3)
                ],
                "",
            )
        return {"feed": [{"post": _post(1, "only one")}]}, ""

    monkeypatch.setattr("newsie.social_live._get_json", fake_get)
    brief = fetch_social(now=datetime(2026, 11, 17, 1, 5, tzinfo=UTC))
    names = [topic.name for topic in brief.topics]
    assert names == ["Rent cap", "#miete"]
    assert brief.topics[0].summary == "People argue about a Berlin rent cap."
    assert len(brief.topics[0].posts) == 3
    assert "miete" in brief.topics[1].summary.lower()
    assert "not evidence" in brief.summary
    assert "No model rewrote" in brief.how
    assert "Thin" not in names


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
