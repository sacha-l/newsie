"""Load curated sources from YAML seed file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from newsie.domain import AdapterKind, Source, SourceTier

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEED = ROOT / "data" / "seed_sources.yaml"

LIVE_DEFAULTS: list[dict[str, Any]] = [
    {
        "id": "tagesschau",
        "name": "Tagesschau",
        "homepage_url": "https://www.tagesschau.de",
        "feed_url": "https://www.tagesschau.de/index~rss2.xml",
        "adapter": "rss",
        "tier": "reporting",
        "spectrum_tags": ["center"],
    },
    {
        "id": "zeit",
        "name": "ZEIT ONLINE",
        "homepage_url": "https://www.zeit.de",
        "feed_url": "https://newsfeed.zeit.de/index",
        "adapter": "rss",
        "tier": "reporting",
        "spectrum_tags": ["center-left"],
    },
    {
        "id": "spiegel",
        "name": "SPIEGEL",
        "homepage_url": "https://www.spiegel.de",
        "feed_url": "https://www.spiegel.de/schlagzeilen/index.rss",
        "adapter": "rss",
        "tier": "reporting",
        "spectrum_tags": ["center-left"],
    },
    {
        "id": "dw",
        "name": "Deutsche Welle",
        "homepage_url": "https://www.dw.com",
        "feed_url": "https://rss.dw.com/rdf/rss-de-all",
        "adapter": "rss",
        "tier": "reporting",
        "spectrum_tags": ["center"],
    },
    {
        "id": "rbb",
        "name": "rbb",
        "homepage_url": "https://www.rbb24.de",
        "feed_url": "https://www.rbb24.de/aktuell/index.xml",
        "adapter": "rss",
        "tier": "reporting",
        "spectrum_tags": ["regional"],
    },
]


def _to_source(row: dict[str, Any], *, force_fixture: bool = False) -> Source:
    adapter = AdapterKind.FIXTURE if force_fixture else AdapterKind(row.get("adapter", "rss"))
    return Source(
        id=row["id"],
        name=row["name"],
        homepage_url=row["homepage_url"],
        feed_url=row.get("feed_url"),
        adapter=adapter,
        tier=SourceTier(row.get("tier", "reporting")),
        spectrum_tags=list(row.get("spectrum_tags") or []),
        language=row.get("language", "de"),
        enabled=bool(row.get("enabled", True)),
    )


def load_seed_sources(
    path: Path | None = None,
    *,
    demo_mode: bool = False,
) -> list[Source]:
    seed_path = path or DEFAULT_SEED
    rows: list[dict[str, Any]]
    if seed_path.exists():
        data = yaml.safe_load(seed_path.read_text(encoding="utf-8")) or {}
        rows = list(data.get("sources") or [])
    else:
        rows = LIVE_DEFAULTS
    if not rows:
        rows = LIVE_DEFAULTS
    # In demo mode keep fixture adapters for known fixture ids; others stay as configured
    out: list[Source] = []
    for row in rows:
        force_fixture = demo_mode and row["id"] in {"tagesschau", "rbb", "zeit"}
        if demo_mode and row["id"] not in {"tagesschau", "rbb", "zeit"}:
            # skip unknown live-only sources in pure demo
            if row.get("adapter") == "rss" and row["id"] not in {"tagesschau", "rbb", "zeit"}:
                continue
        out.append(_to_source(row, force_fixture=force_fixture))
    if not out:
        out = [_to_source(r, force_fixture=True) for r in LIVE_DEFAULTS[:3]]
    return out


def load_live_sources(path: Path | None = None) -> list[Source]:
    seed_path = path or DEFAULT_SEED
    if seed_path.exists():
        data = yaml.safe_load(seed_path.read_text(encoding="utf-8")) or {}
        rows = list(data.get("sources") or []) or LIVE_DEFAULTS
    else:
        rows = LIVE_DEFAULTS
    # Prefer curated live list merged with defaults by id
    by_id = {r["id"]: r for r in LIVE_DEFAULTS}
    for r in rows:
        by_id[r["id"]] = {**by_id.get(r["id"], {}), **r, "adapter": r.get("adapter") or "rss"}
    return [_to_source(r, force_fixture=False) for r in by_id.values()]
