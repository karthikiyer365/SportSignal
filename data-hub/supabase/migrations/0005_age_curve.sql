-- Typical market value by (position, age) — precomputed by the pipeline
-- because PostgREST aggregates are disabled on the anon endpoint.
-- Apply manually in SQL editor.
create table if not exists age_curve (
    primary_position text not null,
    age int not null,
    avg_value_eur bigint not null,
    n int not null,
    updated_at timestamptz not null default now(),
    primary key (primary_position, age)
);

alter table age_curve enable row level security;

create policy "anon read only" on age_curve
    for select to anon using (true);
