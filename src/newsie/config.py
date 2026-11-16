"""Env-driven settings — one source of truth for budgets and loop caps."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    digest_tz: str = "Europe/Berlin"
    ingest_lookback_hours: int = 18
    max_stories_per_digest: int = 8
    max_sources_per_run: int = 40
    max_articles_per_source: int = 25
    max_pipeline_steps: int = 64
    max_llm_tokens_per_run: int = 80_000
    max_fetches_per_run: int = 200
    max_playwright_minutes_per_run: int = 10
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    cluster_similarity_threshold: float = 0.82
    playwright_enabled: bool = False
    kill_switch: bool = False
    database_url: str = "sqlite:///./newsie_data.db"
    demo_mode: bool = True
    # Set to your Supabase pooler URL for Phase 2 Postgres, e.g.
    # postgresql://postgres....supabase.co:6543/postgres
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_owner_chat_id: str | None = None
    default_parties: list[str] = Field(
        default_factory=lambda: [
            "CDU/CSU",
            "SPD",
            "Grüne",
            "FDP",
            "Die Linke",
            "AfD",
            "BSW",
            "Other/Institutional",
        ]
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
