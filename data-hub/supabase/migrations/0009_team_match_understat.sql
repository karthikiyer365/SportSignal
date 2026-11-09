-- Understat per-match team xG (2014+). Team names are Understat spellings —
-- join to matches via date + the club-name seam, not by name equality.
-- Apply manually in SQL editor.
create table if not exists team_match_understat (
    league text not null,
    season text not null,
    game_id bigint not null,
    date date not null,
    home_team text not null,
    away_team text not null,
    home_goals int,
    away_goals int,
    home_xg real,
    away_xg real,
    home_np_xg real,
    away_np_xg real,
    home_expected_points real,
    away_expected_points real,
    home_ppda real,
    away_ppda real,
    home_deep_completions int,
    away_deep_completions int,
    updated_at timestamptz not null default now(),
    primary key (league, season, game_id)
);

alter table team_match_understat enable row level security;

create policy "anon read only" on team_match_understat
    for select to anon using (true);
