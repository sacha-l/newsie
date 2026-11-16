from __future__ import annotations

from pathlib import Path

from newsie.adapters.fixture import FixtureAdapter
from newsie.config import Settings
from newsie.domain import AdapterKind
from newsie.pipeline import DigestPipeline
from newsie.sources import load_seed_sources
from newsie.sql_store import SqlStore


def test_sql_store_persists_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    store = SqlStore(url)
    for s in load_seed_sources(demo_mode=True):
        store.upsert_source(s)
    assert "tagesschau" in store.sources

    settings = Settings(database_url=url, demo_mode=True, max_articles_per_source=3)
    # Force fixture adapters on sources for offline persistence test
    for s in list(store.list_enabled_sources()):
        store.upsert_source(s.model_copy(update={"adapter": AdapterKind.FIXTURE}))
    pipe = DigestPipeline(store, settings, adapter=FixtureAdapter())
    result = pipe.run()
    assert result.draft is not None

    store2 = SqlStore(url)
    assert len(store2.list_articles()) >= 1
    assert store2.get_draft(result.draft.id) is not None
