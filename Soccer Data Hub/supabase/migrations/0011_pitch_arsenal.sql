-- Baseball pitch-quality: season x pitcher x pitch_type summary (n >= 25), 2020+.
-- Raw pitches live in the public `statcast` Storage bucket, not here (500 MB DB cap).
-- LHP are mirrored: hb_arm_in and release_x read as for a righty. Stuff+ columns come in a later migration.
create table if not exists pitch_arsenal (
    season int not null,
    pitcher bigint not null,          -- MLBAM id
    pitch_type text not null,
    pitcher_name text,
    p_throws text not null,
    n int not null,
    usage_pct real,
    velo real,
    spin real,
    spin_axis real,                   -- circular mean, degrees
    ivb_in real,                      -- induced vertical break, inches
    hb_arm_in real,                   -- horizontal break, inches, + = arm side
    release_x real,
    release_z real,
    extension real,
    arm_angle real,
    rv_per_100 real,                  -- -100 * mean(delta_run_exp), + = good for pitcher
    whiff_pct real,                   -- whiffs / swings
    xwobacon real,                    -- mean xwOBA on contact
    updated_at timestamptz not null default now(),
    primary key (season, pitcher, pitch_type)
);

alter table pitch_arsenal enable row level security;
create policy "anon read only" on pitch_arsenal for select to anon using (true);
