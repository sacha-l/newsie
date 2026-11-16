from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from newsie.domain import ArticleCandidate, Source


@dataclass
class FetchContext:
    deadline: datetime
    max_articles: int
    lookback_hours: int


class SourceAdapter(Protocol):
    def fetch(self, source: Source, ctx: FetchContext) -> list[ArticleCandidate]:
        """Return candidates; empty list on no content; respect ctx limits."""
