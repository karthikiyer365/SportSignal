-- Phase A: merged player-season table. Apply manually in Supabase SQL editor.
create table if not exists player_season (
    league text not null,
    season text not null,
    team text not null,
    player_name text not null,
    nationality text,
    position text,
    age smallint,
    birth_year smallint,
    matches_played smallint,
    starts smallint,
    minutes integer,
    nineties real,
    goals smallint,
    assists smallint,
    goals_assists smallint,
    non_penalty_goals smallint,
    penalties_scored smallint,
    penalties_attempted smallint,
    yellow_cards smallint,
    red_cards smallint,
    goals_per90 real,
    assists_per90 real,
    goals_assists_per90 real,
    non_penalty_goals_per90 real,
    non_penalty_goals_assists_per90 real,
    tm_id bigint,
    xref_method text not null default 'unmatched',
    xref_confidence real,
    market_value_in_eur bigint,
    value_date date,
    updated_at timestamptz not null default now(),
    primary key (league, season, team, player_name)
);

alter table player_season enable row level security;

create policy "anon read only" on player_season
    for select to anon using (true);
-- no insert/update/delete policies for anon: service role bypasses RLS.
