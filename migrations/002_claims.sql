-- Claim layer for Postgres / Supabase. Apply after 001_init.sql.
-- The app's SQLite models mirror these tables with JSON embeddings.
-- Article and claim nearest-neighbour lookup uses pgvector. The Python
-- assign_stories / match_story functions implement the same rule off Postgres.

create extension if not exists vector;
create extension if not exists pg_trgm;

alter table sources add column if not exists spectrum text not null default 'centre';
alter table sources add column if not exists spectrum_basis text not null default '';
alter table sources add column if not exists publisher_group text;
alter table sources add column if not exists owner_preference double precision not null default 1.0;

alter table articles add column if not exists full_text text;
alter table articles add column if not exists origin_id text;
alter table articles add column if not exists agency_credit text;
alter table articles add column if not exists extraction_method text;
alter table articles add column if not exists partial boolean not null default false;

alter table stories add column if not exists centroid vector(1536);
alter table stories add column if not exists window_start timestamptz;
alter table stories add column if not exists window_end timestamptz;
alter table stories add column if not exists independent_origin_count integer not null default 0;

create table if not exists story_articles (
  story_id uuid not null references stories(id) on delete cascade,
  article_id uuid not null references articles(id) on delete cascade,
  similarity double precision not null default 0,
  primary key (story_id, article_id)
);

create index if not exists story_articles_article_idx on story_articles (article_id);

create table if not exists claims (
  id uuid primary key,
  article_id uuid not null references articles(id) on delete cascade,
  text text not null,
  type text not null,
  speaker text,
  span_start integer not null,
  span_end integer not null
);

create index if not exists claims_article_idx on claims (article_id);

create table if not exists claim_clusters (
  id uuid primary key,
  story_id uuid not null references stories(id) on delete cascade,
  canonical_text text not null,
  label text not null,
  origin_count integer not null default 0,
  contradict_count integer not null default 0,
  cross_spectrum boolean not null default false
);

create index if not exists claim_clusters_story_idx on claim_clusters (story_id);

create table if not exists claim_evidence (
  claim_cluster_id uuid not null references claim_clusters(id) on delete cascade,
  article_id uuid not null references articles(id) on delete cascade,
  origin_id text not null,
  stance text not null,
  quote text not null default '',
  judge_model text not null,
  primary key (claim_cluster_id, article_id)
);

create table if not exists digest_sentences (
  id uuid primary key,
  draft_id uuid not null references digest_drafts(id) on delete cascade,
  story_id uuid references stories(id),
  section text not null,
  text text not null,
  claim_cluster_id uuid references claim_clusters(id),
  citations jsonb not null default '[]',
  support_verdict text not null default 'unchecked',
  owner_flag text
);

create index if not exists digest_sentences_draft_idx on digest_sentences (draft_id);

-- Claim vectors stay small and are deleted when a story window closes.
-- 512 dimensions is the disk budget; do not store 1536-d claim vectors here.
create table if not exists claim_embeddings (
  claim_id uuid primary key references claims(id) on delete cascade,
  story_id uuid not null references stories(id) on delete cascade,
  embedding vector(512),
  embedding_model text not null,
  embedded_at timestamptz not null
);

create index if not exists article_embeddings_hnsw
  on article_embeddings using hnsw (embedding vector_cosine_ops);

create index if not exists claim_embeddings_hnsw
  on claim_embeddings using hnsw (embedding vector_cosine_ops);

-- Cheap wire-copy pass before the shingle comparison in origins.py.
create index if not exists articles_title_trgm on articles using gin (title gin_trgm_ops);

-- Same rule as newsie.evidence.label_claim. Official-only wins when every
-- supporter is an official-tier source and nothing contradicts.
create or replace function evidence_label(
  support_count integer,
  contradict_count integer,
  official_only boolean
) returns text
language sql
immutable
as $$
  select case
    when support_count >= 1 and contradict_count >= 1 then 'contested'
    when support_count >= 1 and official_only then 'official_only'
    when support_count >= 2 then 'corroborated'
    else 'single_origin'
  end;
$$;

-- Same nearest-centroid rule as newsie.cluster.assign_stories. SqlStore calls
-- this when the database is Postgres. SQLite keeps the Python scan.
create or replace function nearest_open_story(q vector(1536), at timestamptz)
returns table (story_id uuid, similarity double precision)
language sql
stable
as $$
  select id, (1 - (centroid <=> q))::double precision
  from stories
  where status = 'active'
    and centroid is not null
    and (window_start is null or window_start <= at)
    and (window_end is null or window_end >= at)
  order by centroid <=> q
  limit 1;
$$;

-- Schedules and stage hand-off live in Postgres. DBOS is not used.
-- create extension if not exists pg_cron;
-- create extension if not exists pgmq;
-- select cron.schedule('newsie-digest', '0 7,18 * * *', $$select 1$$);
