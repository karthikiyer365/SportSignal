-- Identity map as shared source of truth. Apply manually in SQL editor.
create table if not exists player_xref (
    league text not null,
    season text not null,
    team text not null,
    fbref_name text not null,
    tm_id bigint,
    method text not null,
    confidence real not null,
    updated_at timestamptz not null default now(),
    primary key (league, season, team, fbref_name)
);

alter table player_xref enable row level security;

create policy "anon read only" on player_xref
    for select to anon using (true);
