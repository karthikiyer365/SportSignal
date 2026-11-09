-- Defensive (fbref 'misc') + keeper stat columns, 2017+ seasons only.
-- Apply manually in SQL editor.
alter table player_season
    add column if not exists tackles_won bigint,
    add column if not exists interceptions bigint,
    add column if not exists fouls_committed bigint,
    add column if not exists tackles_interceptions_per90 real,
    add column if not exists goals_against bigint,
    add column if not exists shots_on_target_against bigint,
    add column if not exists saves bigint,
    add column if not exists save_pct real,
    add column if not exists clean_sheets bigint,
    add column if not exists clean_sheet_pct real;
