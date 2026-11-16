"""Load curated sources from the YAML seed. The seed file is the only copy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from newsie.domain import AdapterKind, Source, SourceTier, Spectrum

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEED = ROOT / "data" / "seed_sources.yaml"

_SPECTRUM_ALIASES = {
    "center": Spectrum.CENTRE,
    "centre": Spectrum.CENTRE,
    "center-left": Spectrum.CENTRE_LEFT,
    "centre-left": Spectrum.CENTRE_LEFT,
    "center-right": Spectrum.CENTRE_RIGHT,
    "centre-right": Spectrum.CENTRE_RIGHT,
    "left": Spectrum.LEFT,
    "right": Spectrum.RIGHT,
    "regional": Spectrum.REGIONAL,
    "official": Spectrum.OFFICIAL,
    "party": Spectrum.PARTY,
}

FIXTURE_SOURCE_IDS = frozenset({"tagesschau", "rbb", "zeit"})


def _spectrum(row: dict[str, Any]) -> Spectrum:
    raw = row.get("spectrum")
    if not raw:
        tags = list(row.get("spectrum_tags") or [])
        raw = tags[0] if tags else "centre"
    key = str(raw).strip().lower()
    try:
        return _SPECTRUM_ALIASES[key]
    except KeyError as exc:
        raise ValueError(f"unknown spectrum {raw!r} for source {row.get('id')}") from exc


def _to_source(row: dict[str, Any], *, force_fixture: bool = False) -> Source:
    adapter = AdapterKind.FIXTURE if force_fixture else AdapterKind(row.get("adapter", "rss"))
    return Source(
        id=row["id"],
        name=row["name"],
        homepage_url=row["homepage_url"],
        feed_url=row.get("feed_url"),
        adapter=adapter,
        tier=SourceTier(row.get("tier", "reporting")),
        spectrum=_spectrum(row),
        spectrum_basis=str(row.get("spectrum_basis") or ""),
        publisher_group=row.get("publisher_group"),
        language=row.get("language", "de"),
        enabled=bool(row.get("enabled", True)),
        rate_limit_per_hour=int(row.get("rate_limit_per_hour", 60)),
    )


def _rows(path: Path | None) -> list[dict[str, Any]]:
    seed_path = path or DEFAULT_SEED
    if not seed_path.exists():
        return []
    data = yaml.safe_load(seed_path.read_text(encoding="utf-8")) or {}
    return list(data.get("sources") or [])


def load_seed_sources(
    path: Path | None = None,
    *,
    demo_mode: bool = False,
) -> list[Source]:
    out: list[Source] = []
    for row in _rows(path):
        if demo_mode and row["id"] not in FIXTURE_SOURCE_IDS:
            continue
        out.append(_to_source(row, force_fixture=demo_mode))
    return out


def load_live_sources(path: Path | None = None) -> list[Source]:
    return load_seed_sources(path, demo_mode=False)
