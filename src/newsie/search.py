"""Keyword half of hybrid search.

Postgres ranks with `keyword_rank` in migrations/003_postgres.sql (German
full-text search). This is the same overlap score for SQLite and tests.
"""

from __future__ import annotations


def keyword_score(query: str, body: str) -> float:
    """Share of query tokens that appear in the body. Both sides are data."""
    wanted = {token for token in query.lower().split() if token}
    if not wanted:
        return 0.0
    have = set(body.lower().split())
    return len(wanted & have) / len(wanted)
