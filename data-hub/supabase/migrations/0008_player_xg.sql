-- Understat xG columns on player_season (2014+ seasons only; earlier stay null).
-- Apply manually in SQL editor.
alter table player_season
    add column if not exists xg real,
    add column if not exists np_xg real,
    add column if not exists xa real,
    add column if not exists xg_chain real,
    add column if not exists xg_buildup real,
    add column if not exists shots bigint,
    add column if not exists key_passes bigint,
    add column if not exists understat_id bigint;
