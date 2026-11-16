-- Postgres search, views, append-only flags, and optional queue/cron.
-- Apply after 002_claims.sql. SQLite keeps the Python equivalents.

create table if not exists flag_events (
  id bigserial primary key,
  sentence_id uuid not null,
  draft_id uuid not null,
  flag text not null,
  recorded_at timestamptz not null default now()
);

create index if not exists flag_events_sentence_idx on flag_events (sentence_id);

-- Keyword half of hybrid search. Vector neighbours stay in nearest_open_story.
create or replace function keyword_rank(q text, body text)
returns double precision
language sql
immutable
as $$
  select ts_rank(
    to_tsvector('german', coalesce(body, '')),
    plainto_tsquery('german', coalesce(q, ''))
  )::double precision;
$$;

-- Readable label next to the rows. The app still calls newsie.evidence.label_claim.
create or replace view claim_labels as
select
  claim_cluster_id,
  count(*) filter (where stance = 'supports') as support_rows,
  count(*) filter (where stance = 'contradicts') as contradict_rows
from claim_evidence
group by claim_cluster_id;

-- pg_cron and pgmq are optional extensions. A missing extension must not abort migrate.
do $$
begin
  create extension if not exists pg_cron;
  perform cron.schedule(
    'newsie-digest',
    '0 7,18 * * *',
    $cron$select pgmq.send('newsie_stages', '{"stage":"digest"}') $cron$
  );
exception when others then
  raise notice 'pg_cron unavailable: %', sqlerrm;
end $$;

do $$
begin
  create extension if not exists pgmq;
  perform pgmq.create('newsie_stages');
exception when others then
  raise notice 'pgmq unavailable: %', sqlerrm;
end $$;
