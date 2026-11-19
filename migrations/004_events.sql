-- Event identity recorded on stories. Safe to re-run only where the columns are absent.
alter table stories add column if not exists actors jsonb not null default '[]';
alter table stories add column if not exists location text not null default '';
alter table stories add column if not exists resolution_confidence double precision not null default 1;
alter table stories add column if not exists assignment_notes jsonb not null default '[]';
alter table stories add column if not exists parent_story_id text;
alter table claim_clusters add column if not exists assessment text not null default '';
