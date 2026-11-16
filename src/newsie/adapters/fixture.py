"""Deterministic fixture adapter for demos and tests — no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from newsie.adapters.base import FetchContext
from newsie.domain import ArticleCandidate, Source

FIXTURE_ARTICLES: dict[str, list[dict[str, str]]] = {
    "tagesschau": [
        {
            "url": "https://example.test/tagesschau/berlin-housing",
            "title": "Berlin Senat streitet über Mietendeckel-Reform",
            "content": (
                "Der Berliner Senat diskutiert eine Reform der Mietpolitik. "
                "SPD und Grüne unterstützen stärkere Regulierungen, die CDU warnt vor "
                "Investitionshemmnissen. Eine Abstimmung ist für nächste Woche geplant."
            ),
        },
        {
            "url": "https://example.test/tagesschau/bundestag-energy",
            "title": "Bundestag berät Energiegesetz",
            "content": (
                "Im Bundestag steht ein Energiegesetz zur Debatte. Die Regierung will "
                "den Ausbau erneuerbarer Energien beschleunigen. Die Opposition fordert "
                "mehr Technologieoffenheit."
            ),
        },
    ],
    "rbb": [
        {
            "url": "https://example.test/rbb/berlin-housing",
            "title": "Mietenstreit in Berlin eskaliert",
            "content": (
                "In Berlin spitzt sich die Debatte um Mietregeln zu. Mietervereine "
                "fordern schnellere Reformen. Die Immobilienwirtschaft spricht von "
                "Unsicherheit für Neubau. Der Senat will nächste Woche entscheiden."
            ),
        }
    ],
    "zeit": [
        {
            "url": "https://example.test/zeit/bundestag-energy",
            "title": "Energiegesetz: Koalition unter Druck",
            "content": (
                "Das geplante Energiegesetz polarisiert. Grüne und SPD betonen Klimaziele, "
                "FDP und Union betonen Versorgungssicherheit und Kosten. Analysten erwarten "
                "Änderungsanträge."
            ),
        }
    ],
}


class FixtureAdapter:
    def fetch(self, source: Source, ctx: FetchContext) -> list[ArticleCandidate]:
        rows = FIXTURE_ARTICLES.get(source.id, [])[: ctx.max_articles]
        now = datetime.now(UTC)
        out: list[ArticleCandidate] = []
        for i, row in enumerate(rows):
            out.append(
                ArticleCandidate(
                    url=row["url"],
                    title=row["title"],
                    content_text=row["content"],
                    published_at=now - timedelta(hours=i + 1),
                    language=source.language,
                    raw_metadata={"fixture": True, "source": source.id},
                )
            )
        return out
