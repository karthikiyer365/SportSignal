-- Cleaning columns computed by the pipeline. Apply manually in SQL editor.
alter table player_season
    add column if not exists primary_position text,
    add column if not exists value_is_stale boolean not null default false;
