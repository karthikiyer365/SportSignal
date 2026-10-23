-- ISL from FotMob (2021/22+): one new per-match player table, plus FotMob-only
-- columns on the shared tables. ISL rows use league 'IND-Indian Super League'.
-- shots_understat.player_id holds FotMob ids for ISL rows, Understat ids for Big-5:
-- always filter on league. Apply manually in SQL editor.
create table if not exists player_match (
    league text not null,
    season text not null,
    match_id bigint not null,          -- FotMob matchId
    fotmob_id bigint not null,         -- FotMob player id
    date date not null,
    team text not null,
    opponent text not null,
    is_home boolean not null,
    player_name text not null,
    position text,                     -- GK/DF/MF/FW
    is_starter boolean,
    minutes smallint,
    rating real,
    goals smallint, assists smallint,
    xg real, xgot real, xa real, np_xg real,
    shots smallint, shots_on_target smallint, big_chances_missed smallint,
    chances_created smallint,
    passes smallint, accurate_passes smallint, passes_final_third smallint,
    accurate_long_balls smallint, touches smallint, touches_opp_box smallint,
    dribbles smallint, dispossessed smallint,
    tackles smallint, interceptions smallint, clearances smallint, blocks smallint,
    recoveries smallint, dribbled_past smallint,
    duels_won smallint, duels_lost smallint, aerials_won smallint, ground_duels_won smallint,
    fouls_committed smallint, was_fouled smallint,
    yellow_cards smallint, red_cards smallint,
    saves smallint, goals_conceded smallint,   -- GK only, else null
    updated_at timestamptz not null default now(),
    primary key (league, season, match_id, fotmob_id)
);

alter table player_match enable row level security;
create policy "anon read only" on player_match for select to anon using (true);

alter table team_match_understat
    add column if not exists home_possession real,
    add column if not exists away_possession real;

alter table shots_understat add column if not exists xgot real;

alter table player_season
    add column if not exists fotmob_id bigint,
    add column if not exists fotmob_rating real,
    add column if not exists xgot real,
    add column if not exists touches_opp_box int,
    add column if not exists dribbles int,
    add column if not exists recoveries int,
    add column if not exists clearances int,
    add column if not exists blocks int,
    add column if not exists aerials_won int,
    add column if not exists duels_won int,
    add column if not exists passes_final_third int,
    add column if not exists accurate_passes int;

-- raw FotMob JSON archive; private, third-party data we don't serve
insert into storage.buckets (id, name, public) values ('fotmob', 'fotmob', false)
on conflict (id) do nothing;
