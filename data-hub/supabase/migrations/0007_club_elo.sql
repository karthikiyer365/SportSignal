-- Club Elo rating snapshots from clubelo.com. One row per (team, snapshot
-- date); accumulates into a time series as the cron job runs. Big-5 only.
-- Apply manually in SQL editor.
create table if not exists club_elo (
    team text not null,
    league text not null,
    snapshot_date date not null,
    elo real not null,
    rank real,
    country text,
    level int,
    elo_from date,
    elo_to date,
    updated_at timestamptz not null default now(),
    primary key (team, league, snapshot_date)
);

alter table club_elo enable row level security;

create policy "anon read only" on club_elo
    for select to anon using (true);
