# System map — sources to pages

As of 2026-10-25 (`feat/isl-fetch`, PR #32). How each source is fetched, where it lands,
which page reads it, and when every job runs. `docs/TOPICAL_MAP.md` predates the FotMob
and WhoScored work; this file is the current reference until that map is regenerated.

## 1. Ingest: one lane per source

| Source | Fetched by | Runner · when | soccerhub function | Lands in |
|---|---|---|---|---|
| FBref | soccerdata, real Chrome (Cloudflare) | launchd · Mon, Wed–Sat | `run_season` (xref → merge) | `player_season`, `player_xref` |
| Understat | soccerdata, HTTP | launchd · after FBref | `push_player_xg`, `push_shots`, `push_team_match` | `player_season` xG cols, `shots_understat`, `team_match_understat` |
| Transfermarkt | transfermarkt-datasets | Actions · Mon 06:00 UTC | `push_transfers` | `transfers` |
| football-data.co.uk | CSV | Actions · Mon | `push_matches` | `matches` |
| ClubElo | HTTP | Actions · Mon | `push_club_elo` | `club_elo` |
| **FotMob** | JSON API, 2 s between calls | launchd · ISL Tue, Big-5 own day | `push_fotmob_new`, `link_fotmob` | ISL: `matches`, `shots_understat`, `team_match_understat`, `player_season`. ISL + Big-5: `player_match`, `player_season.fotmob_id`. Raw JSON → `fotmob` bucket |
| **WhoScored (Opta)** | soccerdata, real Chrome (Cloudflare) | launchd · Big-5 own day | `whoscored_spadl` → `action_score` VAEP, `refresh_current`, `link_whoscored` | `action-score` bucket, `player_season.whoscored_id` |
| StatsBomb · Wyscout open | files | manual, one-off | `action_score` (2015/16, 2017/18) | `site/data/action_score` (git) + `action-score` bucket |
| Baseball Savant | CSV | manual | `pipelines/statcast.py` | `pitch_arsenal`, `statcast` bucket |
| `player_season` (derived) | — | launchd · end of each day | `push_age_curve` | `age_curve` |

Every write goes through `supa.upsert_df` on the table's primary key, so re-running a
lane never duplicates rows. FBref and WhoScored need a residential IP and a real browser,
so they run on the Mac only (launchd), never on GitHub Actions.

## 2. Serve: what each page reads

```text
site/ (Netlify, static)  ── PostgREST, anon key, RLS select-only ──>  Postgres
                         ── public object URL ─────────────────────>  Storage

player.html    player_season · shots_understat · transfers · age_curve · /api/ask
match.html     matches · club_elo
baseball.html  pitch_arsenal
team.html      action-score bucket (WhoScored seasons) · site/data/action_score (StatsBomb/Wyscout)
index.html     site/data/hero.json (scripts/build_hero.py)
/api/ask       Netlify proxy → Render soccerhub-agent (FastAPI + Gemini) → read_hub (anon)
```

Stored but not on a page yet: `player_match`, `team_match_understat`, `player_xref`,
the `fotmob` and `statcast` buckets. The Scout Desk redesign reads `player_match`.

## 3. Weekly cadence

| | Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---|---|---|---|---|---|---|
| launchd · Mac 06:00 local | Premier League | **ISL** | La Liga | Bundesliga | Serie A | Ligue 1 | — |
| GitHub Actions 06:00 UTC | transfers · matches · club_elo | | | | | | |

A Big-5 day runs FBref → Understat ×3 → FotMob push + link → WhoScored refresh + link →
`age_curve`. The schedule lives in one place: `SCHEDULE` in
`Soccer Data Hub/scripts/refresh_fbref_chain.py`. launchd only wakes the script daily
(`scripts/com.ikarthik.soccerhub-fbref.plist`). After editing the plist, reload it:

```bash
launchctl bootout gui/$(id -u)/com.ikarthik.soccerhub-fbref
cp "Soccer Data Hub/scripts/com.ikarthik.soccerhub-fbref.plist" ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ikarthik.soccerhub-fbref.plist
```

## 4. Failure isolation

Each stage of a day is its own `try/except`: a failure is logged as `FAILED <stage>
<league>` and the next stage still runs. Understat runs only if FBref ran (it updates the
rows FBref writes). FotMob and WhoScored run even when FBref is blocked. `age_curve`
always runs. The day exits non-zero if anything failed.

## 5. Player identity

`player_season` rows are keyed by FBref's names (`league, season, team, player_name`).
Each other source's own id is attached by the same matcher
(`pipelines/understat.py:match_players`):

| Column | Set by | Rule |
|---|---|---|
| `tm_id` | `xref.py` | name + birth year |
| `understat_id` | `push_player_xg` | exact name → movers by minutes → fuzzy within 450 min |
| `fotmob_id` | `link_fotmob` | same ladder; 95–99% of minutes linked (Big-5, 2021/22 →) |
| `whoscored_id` | `link_whoscored` | same ladder; 96.9–98.3% of minutes (Big-5, 2025/26 →) |

Exact-name matches also need minutes within 450, and ties stay unlinked rather than
guessed. Join on these ids, never on names: every source spells players and clubs its
own way ("Freiburg" / "SC Freiburg").

## 6. Stores and free-tier budget

| Store | Kind | Size (2026-10-25) |
|---|---|---|
| `shots_understat` | table | 566k rows · 153 MB |
| `player_match` | table | 304k · 104 MB |
| `transfers` | table | 175k · 48 MB |
| `club_elo` | table | 32 MB |
| `player_season` | table | 53k · 24 MB |
| `player_xref` | table | 13 MB |
| `matches` | table | 33k · 8.8 MB |
| `pitch_arsenal` | table | 19k · 5 MB |
| `team_match_understat` | table | 4.6 MB |
| `action-score` | public bucket | 277 MB (WhoScored folders 109 MB) |
| `statcast` | public bucket | 259 MB |
| `fotmob` | private bucket | 250 MB |

Postgres 423 / 500 MB; over the cap the DB goes read-only and the live site breaks.
Storage 786 / 1000 MB, growing about 10 MB a week until May (WhoScored current season).
Check both with a SELECT before adding anything large.

## Data caveats

- FotMob xG ≠ Understat xG ≠ StatsBomb/Wyscout/Opta VAEP. Filter by `league` (and provider)
  before comparing; `shots_understat.player_id` is a FotMob id for ISL rows and an
  Understat id for Big-5 rows.
- ISL rows keep the team name as of each match (2021/22 Hyderabad FC, now SC Delhi);
  Big-5 FotMob rows use the season fixture list's name.
- Current-season VAEP trains on few games; `team.html` labels it low confidence below 190.
- Event data is on-ball only: the touch heatmap shows where a player had the ball, not
  where he stood.

## Open follow-ups

| Issue | Topic |
|---|---|
| #31 | League-aware player search (ISL hidden from Big-5 search for now) |
| #33 | `test_api` fakes reject the `model` kwarg (2 failing tests) |
| #34 | `read_hub` pages without ORDER BY |
| #35 | Player-id links: stale links, season alignment, link-rate alarm |
| #36 | Data gaps: ISL nationality/age, `IndividualPlay`, La Liga 2022 one match short |
| #37 | Refresh script: unexpected errors still end the day |
| #38 | WhoScored follow-ups (cache headers, dropdown, minutes caveat, next season) |
| #39 | Free-tier budget watch |
| #40 | Regenerate `TOPICAL_MAP.md` |
| #41 | Scout Desk: shortlist → compare → report |
| #42 | Sofascore reader for ISL heatmaps and average positions |
| #43 | Research: off-ball positioning from video |
