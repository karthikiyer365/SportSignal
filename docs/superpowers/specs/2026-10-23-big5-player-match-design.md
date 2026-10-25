# Big-5 per-match player stats (FotMob → `player_match`) — design

Branch: `feat/isl-fetch` (follows PR #32) · Date: 2026-10-23 · Status: **draft, awaiting approval**

## Why

The scouting redesign (shortlist → compare → player report → signing decision) has to
work the same way for the ISL and the Big 5. Today only the ISL has match-by-match player
stats (`player_match`). The Big 5 have season totals only (FBref + Understat +
Transfermarkt), so a Big-5 report can't show form, consistency, or the FotMob-only stats
(dribbles, recoveries, duels, rating). This design fills that gap by reusing the ISL
FotMob pipeline. The scouting pages themselves are a separate, later design.

## Goals

1. Backfill FotMob per-match player stats for the Big 5, seasons 2021/22 → current (user decision).
2. Link every FotMob player to his existing Big-5 `player_season` row (`player_season.fotmob_id`),
   so a report opened by `tm_id` / FBref name can find his matches.
3. Keep it fresh weekly on each league's existing launchd day.

## Non-goals

- Writing Big-5 rows to `matches`, `shots_understat`, `team_match_understat` or Big-5
  `player_season` stat columns. Those already come from football-data / Understat / FBref.
- Seasons before 2021/22 (no FotMob xG; ~17 MB DB per season).
- ISL nationality / age gaps (separate small fix).
- Scouting UI, cross-league comparison / league adjustment.

## Anti-goals

- **Duplicates in existing tables.** FotMob uses different shot ids and player spellings;
  writing Big-5 FotMob shots or season rows would double every Big-5 shot and create a
  second `player_season` row per player.
- **Wrong links.** Attaching one player's matches to another player is worse than no link.
  Ambiguous matches stay unlinked.
- **Breaking the DB cap.** Over 500 MB the DB goes read-only and the live site breaks.

## Constraints (verified 2026-10-23)

| Fact | Value |
|---|---|
| FotMob league ids | ENG-Premier League 47 · ESP-La Liga 87 · GER-Bundesliga 54 · ITA-Serie A 55 · FRA-Ligue 1 53 |
| Matches / season | 380 · 380 · 306 · 380 · 306 = **1,752** |
| FotMob detail depth (PL) | 2014/15 none · 2017/18–2019/20 players but no xG/shots · **2021/22+ full** |
| `player_match` measured | 326 B/row incl. indexes · 30.3 rows/match |
| Cost per Big-5 season | ≈ 53k rows ≈ **17 MB DB** · ≈ 42 MB raw archive |
| 2021/22 → now (≈5.3 seasons) | ≈ 280k rows ≈ **92 MB → DB 312 → ~405 MB / 500** · Storage ~444 → ~665 MB / 1 GB |
| Fetch time | ≈ 9.3k matches × 2 s ≈ **5–6 h**, local, resumable (gz cache) |
| Season label | start year text (`'2021'` = 2021/22), same as all hub tables |
| Big-5 `player_season` key | `league, season, team, player_name` (FBref names); has `fotmob_id` column (0012) |

## Data model

No migration needed: `player_match` and `player_season.fotmob_id` already exist (0012).

- `player_match`: Big-5 rows with `league` = hub league name (`ENG-Premier League`, …).
  `team` / `opponent` / `player_name` are **FotMob's** spellings. Join to the hub by
  `fotmob_id`, never by name.
- `player_season.fotmob_id`: set on existing Big-5 rows by the link step. Only this
  column is written for Big-5 (partial upsert, same pattern as `push_player_xg`).
- Raw archive: bucket `fotmob`, path `<slug>/<season>/<match_id>.json.gz`
  (`isl/` stays as is; Big-5 slugs `eng`, `esp`, `ger`, `ita`, `fra`).

## Link step (FotMob player → Big-5 `player_season` row)

Per league-season:
1. FotMob side: sum `player_match` minutes per `(fotmob_id, team)` → one row per stint.
2. Hub side: `player_season` rows `league, season, team, player_name, minutes`.
3. Match with the existing **Understat matcher ladder** (`pipelines/understat.py:match_players`):
   exact normalised name → duplicate names paired by minutes (movers) → fuzzy name,
   minutes-guarded (`MINUTES_GUARD = 450`), ties rejected. Generalise it to take a
   value-column map instead of the hard-coded `XG_COLS`; do not fork it.
4. Upsert `fotmob_id` onto matched hub rows only. Unmatched rows stay null.
5. Report the link rate per league-season.

Team names are not compared (FotMob "Manchester United" vs FBref "Manchester Utd"); the
pool is one league-season and minutes guard the match, as the Understat matcher already does.

## Code changes

| File | Change |
|---|---|
| `readers/fotmob.py` | league id becomes a parameter: `FOTMOB_IDS = {league: id}`, `fetch_league(league, season=None, force)`, archive path by league slug. ISL behaviour unchanged. |
| `pipelines/fotmob_isl.py` → keep file, generalise | `parse_match(raw, season, league)`; `push_fotmob(league, season, match_ids=None)` writes **all five tables for ISL, `player_match` only for Big-5**; `push_fotmob_new(league)`. `push_isl` / `push_isl_new` stay as thin aliases (scripts + exports use them). |
| `pipelines/understat.py` | `match_players` takes the value-column map (default = today's `XG_COLS`). |
| new `link_fotmob(league, season)` | link step above; lives beside the push functions. |
| `scripts/refresh_fbref_chain.py` | after a Big-5 league's FBref chain on its day: `push_fotmob_new(league)` then `link_fotmob(league, current season)`. ISL Tuesday unchanged. |
| tests | Big-5 path writes only `player_match`; link ladder on a mover + a spelling-drift case; archive path per league. |

## Backfill

Local, once, resumable: `python -m soccerhub.pipelines.fotmob_isl <league> 2021 … 2026`
per league, then `link_fotmob` per league-season. Budget check (`pg_database_size`)
before each league; **stop if over 470 MB**. Expected end state ≈ 405 MB.

## Schedule (unchanged days)

| Day | Job |
|---|---|
| Mon | FBref ENG → FotMob ENG `player_match` → link |
| Tue | ISL (all five tables) |
| Wed–Sat | same as Mon for ESP, GER, ITA, FRA |

## Affected surfaces

| Surface | Effect | Handling |
|---|---|---|
| `site/player.html` | none — doesn't read `player_match` yet | — |
| `player_season` Big-5 rows | only `fotmob_id` changes | partial upsert on PK |
| launchd day length | +~15 min/day (≈40 new matches/week/league at 2 s + uploads) | — |
| DB headroom after | ~95 MB left | future big tables need a budget check first |

## Calls made in this doc (not user decisions — check these)

- Big-5 raw payloads are archived too (≈220 MB Storage), same as ISL, so a FotMob change
  never costs re-fetching 9k matches. Dropping the archive would save the Storage, not DB.
- The FotMob step runs even if that day's FBref chain fails (FBref IP blocks are common);
  linking then uses whatever `player_season` rows exist and retries next week.
- One code path for ISL and Big-5 (league flag decides which tables are written) rather
  than a second pipeline.

## Open questions (user)

None.

## Left to the builder

- Exact generalisation of `match_players` (signature, keep current callers passing unchanged).
- Whether `fotmob_isl.py` is renamed; if so keep the old module path importable for launchd.
- Link-rate threshold that should fail the weekly job loudly (suggest < 90% of minutes-weighted rows).
