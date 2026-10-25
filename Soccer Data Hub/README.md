# Soccer Data Hub (`soccerhub`)

Unified fetch layer for open-source soccer data. Fetch → cache to parquet →
return a manifest; pipelines upsert into Supabase, the source of truth. Primary
interface is the Python package; an MCP server wraps the same functions for agent use.
How everything connects: [`../docs/SYSTEM_MAP.md`](../docs/SYSTEM_MAP.md).

## Install

    cd "Soccer Data Hub"
    pip install -e ".[dev]"

Secrets live in `.env` (gitignored): `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` (reads),
`SUPABASE_SERVICE_ROLE_KEY` (writes).

## Use (package)

    from soccerhub import fetch_fbref_season, fetch_statsbomb_events, fetch_transfermarkt_values

    m = fetch_fbref_season("ENG-Premier League", "2023")
    print(m.path, m.rows, m.cols)      # parquet path + shape

    import pandas as pd
    df = pd.read_parquet(m.path)        # projects read the cached parquet directly

Cache directory: `SOCCERHUB_CACHE` env var, default `./data`. Seasons are the start year as
text everywhere: `"2025"` = 2025/26.

## Use (MCP server)

    python -m soccerhub.mcp_server

Tools: `fbref_season`, `statsbomb_events`, `transfermarkt_values` — each returns
a manifest dict — plus `hub_table` to query the Supabase source of truth
(player_season, transfers, player_xref) with league/season/tm_id filters.

## Readers

| Function | Source | Returns |
|---|---|---|
| `fetch_fbref_season(league, season)` | FBref (soccerdata, real Chrome) | player season stats |
| `fetch_understat(league, season, dataset)` | Understat (soccerdata) | xG, team xG, shots |
| `fetch_statsbomb_events(match_id)` | StatsBomb open data (kloppy) | match events |
| `fetch_transfermarkt_values(competition)` | Transfermarkt (pre-scraped) | player valuations |
| `readers.fotmob.fetch_league / fetch_match` | FotMob JSON (ISL + Big 5) | fixtures, match details (gz cache + `fotmob` bucket archive) |
| `readers.whoscored_spadl.fetch_whoscored_spadl(league, code)` | WhoScored / Opta (soccerdata, real Chrome) | SPADL actions + player minutes, finished games only |
| `readers.statsbomb_spadl` · `readers.wyscout_spadl` | open event data | SPADL actions |

Adding a source is one new file in `readers/` reusing `cached_fetch` — see
`docs/plans/2026-07-14-soccerhub-data-layer-design.md`.

## Pipelines (write to Supabase)

| Function | Writes |
|---|---|
| `run_season(league, season)` | `player_xref`, `player_season` (FBref + Transfermarkt) |
| `push_player_xg` · `push_shots` · `push_team_match` | Understat columns, `shots_understat`, `team_match_understat` |
| `push_matches` · `push_club_elo` · `push_transfers` · `push_age_curve` | `matches`, `club_elo`, `transfers`, `age_curve` |
| `push_fotmob(league, season)` · `push_fotmob_new(league)` | ISL: all five tables; Big 5: `player_match` only |
| `link_fotmob(league, season)` | `player_season.fotmob_id` |
| `action_score` CLI · `refresh_current(league, season)` | VAEP site files → `action-score` bucket |
| `link_whoscored(league, season)` | `player_season.whoscored_id` |

Backfills:

    python -m soccerhub.pipelines.fotmob_isl isl 2021 2022 2023 2024 2025 2026
    python -m soccerhub.pipelines.fotmob_isl eng 2021 2022 2023 2024 2025 2026   # + link
    python -m soccerhub.pipelines.action_score --upload "ENG-Premier League" 2025 2026

Weekly refresh: `scripts/refresh_fbref_chain.py` (launchd, daily 06:00; `SCHEDULE` picks the
league) and `.github/workflows/run-season.yml` (Monday). Migrations in `supabase/migrations/`
are applied by hand in the Supabase SQL editor; the latest are `0012_isl_fotmob.sql`
(`player_match`, FotMob columns, `fotmob` bucket) and `0013_whoscored_id.sql`.
