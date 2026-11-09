-- Understat shot events (2014+): every shot with pitch coordinates and xG.
-- Names/ids are Understat's own. ~630k rows across the Big-5 backfill.
-- Apply manually in SQL editor.
create table if not exists shots_understat (
    league text not null,
    season text not null,
    shot_id bigint not null,
    game_id bigint not null,
    date date not null,
    team text not null,
    player text not null,
    player_id bigint,
    assist_player text,
    assist_player_id bigint,
    xg real,
    location_x real,
    location_y real,
    minute int,
    body_part text,
    situation text,
    result text,
    updated_at timestamptz not null default now(),
    primary key (league, season, shot_id)
);

alter table shots_understat enable row level security;

create policy "anon read only" on shots_understat
    for select to anon using (true);
