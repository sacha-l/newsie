from __future__ import annotations

from datetime import UTC, datetime

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
