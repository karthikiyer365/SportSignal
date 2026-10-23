# ISL data pipeline (FotMob → Supabase) — design

Branch: `feat/isl-fetch` · Date: 2026-10-22 · Status: **draft, awaiting approval**

## Why

Goal: ISL scouting reports, performance analytics and per-player dashboards.
None of the installed sources (soccerdata, StatsBomb beyond 2021/22, Understat,
FBref) cover the ISL. FotMob's public JSON does, from 2021/22 with xG. This
design covers **only the data layer**: get ISL into Supabase and keep it fresh.
The dashboard is a separate design that builds on these tables.

Video → SPADL/VAEP is explicitly later (non-goal here).

## Goals

1. Backfill ISL seasons 2021/22 → current (2026/27) into Supabase.
2. Weekly refresh, Mondays, fetching only finished matches not yet stored.
3. Reuse existing tables (user decision); add one new table for per-match player stats.
4. Keep a raw copy of every FotMob response so we can re-parse without re-fetching.

## Non-goals

- Dashboard UI (next design).
- I-League (FotMob search found no I-League; ESPN `ind.2` has results only).
- ESPN as a data source. Checked 2026-10-21: zero coordinates, near-empty player
  stats. Not used.
- Linking ISL players to Transfermarkt (`tm_id`) or market values.
- Video, SPADL, VAEP.

## Anti-goals (failure even if it "works")

- ISL rows leaking into the Big-5 football pages (search, shot maps) and showing
  Big-5 assumptions (38-game seasons, market values) against ISL players.
- Mixing FotMob xG with Understat xG in one number without anyone noticing.
- Pushing the DB over the 500 MB free cap (DB goes read-only → live site breaks).

## Constraints (verified 2026-10-22)

| Fact | Value |
|---|---|
| DB size | 300 MB / 500 MB (`pg_database_size`) |
| Storage | 427 MB / 1 GB (`statcast` 259 MB, `action-score` 168 MB) |
| ISL cost estimate | ~25 MB DB, ~17 MB Storage |
| Season label convention | start year as text: `'2021'` = 2021/22 (`matches` PL `'2025'` = 2025-08-15 → 2026-05-24) |
| League label | `IND-Indian Super League` (matches `ENG-Premier League` style) |
| NOT NULL w/o default on shared tables | key cols only; `player_season.xref_method` defaults `'unmatched'`, `value_is_stale` defaults `false` |
| FotMob | unofficial, no key, no auth header needed as of 2026-10-21; ~250 KB/match raw, 24 KB gzipped |
| Migrations | applied **by the user** in the SQL editor; never via MCP |

### FotMob endpoints used

| Purpose | URL |
|---|---|
| Season fixtures + match ids | `https://www.fotmob.com/api/data/leagues?id=9478&season=2024%2F2025` |
| Per-match everything | `https://www.fotmob.com/api/data/matchDetails?matchId=<id>` |

Matches per season (FotMob, all finished except current): 2021/22 115 · 2022/23 117 ·
2023/24 139 · 2024/25 163 · 2025/26 91 · 2026/27 78 scheduled, 12 played.

## Data model

### Reused tables — column mapping

**`matches`** (PK `league, season, date, home_team, away_team`) — no new columns.
FotMob → `home_goals, away_goals, result, home_goals_ht, away_goals_ht, result_ht,
home/away_shots, home/away_shots_on_target, home/away_fouls, home/away_corners,
home/away_yellow, home/away_red`. `referee` from matchFacts infoBox if present, else null.

**`team_match_understat`** (PK `league, season, game_id`) — `game_id` = FotMob matchId.
Fills `date, home_team, away_team, home/away_goals, home/away_xg, home/away_np_xg`.
Leaves `expected_points, ppda, deep_completions` null.
New columns: `home_possession real, away_possession real`.

**`shots_understat`** (PK `league, season, shot_id`) — `shot_id` = FotMob shot id,
`game_id` = matchId. Fills `date, team, player, xg, minute, body_part, situation, result`.
- `location_x/y`: FotMob pitch is 105×68 → divide to 0–1 like Understat. Orientation
  must be verified against a known goal before backfill (builder task, see below).
- `player_id` = **FotMob player id** for ISL rows (user decision 2026-10-23, ISL only;
  Big-5 rows keep Understat ids). `player_id` is therefore source-specific: Understat id
  for Big-5, FotMob id for ISL. Every query on it must also filter `league`.
  FotMob ids (up to ~1.1M) overlap Understat's range, and `site/player.html:1382` loads
  shots by `player_id = understat_id` with **no league filter**, so that query gets
  `league: "neq.IND-Indian Super League"` added.
- `assist_player*` null (FotMob shotmap has no assister).
- New column: `xgot real`.
- Value vocab: map FotMob to Understat's existing strings so filters work:
  `result` ∈ Goal/SavedShot/MissedShot/BlockedShot/ShotOnPost (builder confirms
  the exact existing strings with `select distinct`), `situation` ∈ existing values
  (`From Corner`, …), `body_part` likewise.

**`player_season`** (PK `league, season, team, player_name`) — one row per player-team-season,
**summed from `player_match`** (not from FotMob's leaderboard feeds).
Fills existing: `nationality, position, primary_position (GK/DF/MF/FW), age,
matches_played, starts, minutes, nineties, goals, assists, goals_assists,
non_penalty_goals, penalties_scored, yellow_cards, red_cards, *_per90, tackles_won,
interceptions, fouls_committed, saves, clean_sheets, goals_against, xg, np_xg, xa,
shots, key_passes (= chances created)`. `tm_id`, market value, `understat_id` null.
New columns:

```
fotmob_id bigint, fotmob_rating real, xgot real,
touches_opp_box int, dribbles int, recoveries int, clearances int, blocks int,
aerials_won int, duels_won int, passes_final_third int, accurate_passes int
```

### New table — `player_match`

One row per player per match. Name is league-generic on purpose (keyed by `league`),
so Big-5 could use it later; only ISL writes to it now.

```sql
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
```

~28k rows for the backfill (~17 MB). Stats FotMob doesn't provide for a player
stay null, never 0.

### Raw archive

Private Storage bucket `fotmob`, path `isl/<season>/<match_id>.json.gz`
(+ `isl/<season>/league.json.gz` per fetch). Private because it is third-party
data we don't need to serve. Local cache under `SOCCERHUB_CACHE` as usual.

### Migration

One file: `Soccer Data Hub/supabase/migrations/0012_isl_fotmob.sql` — `create table
player_match` + `alter table … add column if not exists` for the columns above.
User applies it in the SQL editor before any push runs.

## Code

Follows existing patterns (`readers/understat.py`, `pipelines/understat.py`, `supa.upsert_df`).

| File | Role |
|---|---|
| `src/soccerhub/readers/fotmob.py` | `fetch_league(season)`, `fetch_match(match_id)` — HTTP + pacing + local raw cache + upload to bucket |
| `src/soccerhub/pipelines/fotmob_isl.py` | parse raw → 5 DataFrames; `push_isl(season)` upserts all; `push_isl_new()` = current season, only matches missing from `player_match` |
| `src/soccerhub/pipelines/__init__.py` | export `push_isl`, `push_isl_new`; `PLAYER_MATCH_CONFLICT_KEY` |
| `tests/test_fotmob_isl.py` | one saved `matchDetails` fixture → asserts row counts, coordinate scaling, null-not-zero |

Fetch rules: one request at a time, ~2 s apart, User-Agent like a browser, retry
via existing `retry()`. Backfill = ~700 match calls ≈ 25–30 min, run **locally** once.

## Schedule (user decision 2026-10-23)

ISL runs **locally** on the existing launchd job, not GitHub Actions.

| Day (06:00 local) | Today | After |
|---|---|---|
| Mon | Actions: transfers, matches, club-elo · launchd: ENG-Premier League | same |
| Tue | launchd: ESP-La Liga | **launchd: ISL** (`push_isl_new()`) |
| Wed | launchd: GER-Bundesliga | launchd: ESP-La Liga |
| Thu | Actions (2nd run) · launchd: ITA-Serie A | launchd: GER-Bundesliga |
| Fri | launchd: FRA-Ligue 1 | launchd: ITA-Serie A |
| Sat | — | launchd: FRA-Ligue 1 |

Changes:
- `run-season.yml`: `"0 6 * * 1,4"` → `"0 6 * * 1"`.
- `scripts/com.ikarthik.soccerhub-fbref.plist`: weekdays 1–5 → 1–6 (adds Saturday).
- `scripts/refresh_fbref_chain.py`: `leagues_for_today` switches from list index to an
  explicit weekday map, `{0: PL, 1: ISL, 2: Liga, 3: Bund, 4: Serie A, 5: Ligue 1}`.
  Tuesday calls `push_isl_new()` instead of the FBref chain.
- After editing the plist the user reloads it (`launchctl unload/load`); that's a
  local machine change, not in the repo.

## Affected surfaces (things that change behaviour without being edited)

| Surface | Effect of ISL rows | Handling |
|---|---|---|
| `site/player.html:301` search (`player_season`, no league filter) | ISL players appear in Big-5 player search | **hidden**: add `league: "neq.IND-Indian Super League"`. Proper fix tracked in issue #31 |
| `site/player.html:986,1256` (38/34-game season math) | wrong "share of season" for ISL players | unreachable once search hides ISL; #31 |
| `site/player.html:1382` shot map (`player_id = understat_id`) | ISL shots could match a Big-5 player whose Understat id equals an ISL player's FotMob id | add `league: "neq.IND-Indian Super League"` to the query |
| `push_age_curve` (reads all `player_season`) | none — filters `market_value_in_eur not null` | — |
| `site/match.html`, `site/team.html` | none — hard-coded Big-5 `LEAGUES` | — |
| xG comparisons across leagues | FotMob vs Understat xG in same columns | every ISL query filters `league`; documented here |

## Decided (2026-10-23)

1. Hide ISL from Big-5 search; league-aware search tracked in
   [#31](https://github.com/karthikiyer365/SportSignal/issues/31).
2. FBref rotation moves to Mon + Wed–Sat; ISL takes Tuesday.
3. ISL refresh runs locally (launchd), not GitHub Actions.

4. `shots_understat.player_id` holds FotMob ids for ISL rows (option a). Moving
   Big-5 to FotMob ids too (option b) is out of scope.

## Open questions (user)

None.

## Left to the builder

- Exact FotMob → Understat vocab for `result/situation/body_part` (check existing distinct values).
- Shot coordinate orientation check against one known goal.
- FotMob position id → GK/DF/MF/FW mapping.
- Team name normalisation across seasons (e.g. "Mohun Bagan SG" vs "Mohun Bagan Super Giant").
- `age`: FotMob lineup `age` is age *today*, wrong for past seasons. Derive from
  birth date if the payload has one, else leave null for past seasons.

## Side finding (not in scope)

`matches` for ENG-Premier League season `'2026'` stops at 2026-09-20 — the
Actions `matches` job may be failing. Check run history when editing the cron.
