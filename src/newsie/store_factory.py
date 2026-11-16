"""Choose memory vs SQL store from settings."""

from __future__ import annotations

from newsie.config import Settings
from newsie.sql_store import SqlStore
from newsie.store import MemoryStore, Store


def create_store(settings: Settings, *, force_memory: bool = False) -> Store:
    if force_memory:
        return MemoryStore()
    url = settings.database_url.strip()
    # Persist by default for Phase 2 (sqlite file or Postgres/Supabase)
    if url.startswith("sqlite:") or "postgres" in url:
        return SqlStore(url)
    return MemoryStore()
