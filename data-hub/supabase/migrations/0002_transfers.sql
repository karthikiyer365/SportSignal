-- Transfer events (all leagues). Apply manually in Supabase SQL editor.
create table if not exists transfers (
    tm_id bigint not null,
    player_name text,
    transfer_date date not null,
    transfer_season text,
    from_club_id bigint,
    to_club_id bigint,
    from_club_name text,
    to_club_name text,
    transfer_fee bigint,
    market_value_in_eur bigint,
    updated_at timestamptz not null default now(),
    primary key (tm_id, transfer_date)
);

alter table transfers enable row level security;

create policy "anon read only" on transfers
    for select to anon using (true);
