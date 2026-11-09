-- Match results (goals, shots, cards, corners) from football-data.co.uk.
-- Apply manually in SQL editor.
create table if not exists matches (
    league text not null,
    season text not null,
    date date not null,
    home_team text not null,
    away_team text not null,
    home_goals int,
    away_goals int,
    result text,
    home_goals_ht int,
    away_goals_ht int,
    result_ht text,
    referee text,
    home_shots int,
    away_shots int,
    home_shots_on_target int,
    away_shots_on_target int,
    home_fouls int,
    away_fouls int,
    home_corners int,
    away_corners int,
    home_yellow int,
    away_yellow int,
    home_red int,
    away_red int,
    updated_at timestamptz not null default now(),
    primary key (league, season, date, home_team, away_team)
);

alter table matches enable row level security;

create policy "anon read only" on matches
    for select to anon using (true);
