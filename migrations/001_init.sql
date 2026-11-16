-- Newsie Phase 2 schema (Supabase / Postgres). Enable pgvector first:
-- create extension if not exists vector;

create extension if not exists vector;

create table if not exists sources (
  id text primary key,
  name text not null,
  homepage_url text not null,
  feed_url text,
  adapter text not null default 'rss',
  tier text not null default 'reporting',
  spectrum_tags jsonb not null default '[]',
  language text not null default 'de',
  enabled boolean not null default true,
  reliability_score double precision not null default 1.0,
  strike_count integer not null default 0,
  trust_state text not null default 'trusted',
  rate_limit_per_hour integer not null default 60
);

create table if not exists articles (
  id uuid primary key,
  source_id text not null references sources(id),
  url text not null,
  canonical_url text not null,
  title text not null,
  byline text,
  published_at timestamptz,
  retrieved_at timestamptz not null,
  content_text text not null,
  content_hash text not null unique,
  lang text not null default 'de',
  tier_at_ingest text not null,
  raw_metadata jsonb not null default '{}',
  quarantine_reason text
);

create table if not exists article_embeddings (
  article_id uuid primary key references articles(id) on delete cascade,
  embedding vector(1536),
  embedding_model text not null,
  embedding_dim integer not null,
  embedded_at timestamptz not null
);

create table if not exists stories (
  id uuid primary key,
  fingerprint text not null unique,
  first_seen_at timestamptz not null,
  last_seen_at timestamptz not null,
  corroboration_score double precision not null default 0,
  title_hint text not null,
  status text not null default 'active',
  article_ids jsonb not null default '[]'
);

create table if not exists digest_runs (
  id uuid primary key,
  scheduled_for timestamptz not null,
  started_at timestamptz,
  finished_at timestamptz,
  status text not null,
  kill_switch_hit boolean not null default false,
  budget_snapshot jsonb not null default '{}'
);

create table if not exists digest_drafts (
  id uuid primary key,
  run_id uuid not null references digest_runs(id),
  story_ids jsonb not null default '[]',
  spine_md text not null,
  perspectives_json jsonb not null default '[]',
  divergence_md text not null,
  events_json jsonb not null default '[]',
  citations_json jsonb not null default '[]',
  english_render_md text not null,
  validation_status text not null,
  created_at timestamptz not null
);

create table if not exists publications (
  id uuid primary key,
  draft_id uuid not null references digest_drafts(id),
  approved_at timestamptz not null,
  telegram_message_ids jsonb not null default '[]',
  immutable_snapshot jsonb not null default '{}'
);

create table if not exists source_ratings (
  id bigserial primary key,
  source_id text not null references sources(id),
  score double precision not null,
  rated_at timestamptz not null
);
