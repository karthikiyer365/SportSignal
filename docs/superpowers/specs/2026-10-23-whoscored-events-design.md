# WhoScored events → SPADL / VAEP for current Big-5 seasons — design

Branch: `feat/isl-fetch` (follows PR #32) · Date: 2026-10-23 · Status: **draft, awaiting approval**

## Why

The scouting report (shortlist → compare → report) needs pass maps, heatmaps, average
positions and a real on-ball value (VAEP) for **current** seasons. Today the only event data
is StatsBomb 2015/16 and Wyscout 2017/18 (`pipelines/action_score.py`). FotMob, Understat
and FBref have no event coordinates. A read-only probe on 2026-10-23 showed WhoScored (Opta)
works from the user's Mac through `soccerdata`'s browser: Man Utd v Fulham 2024-08-16 →
1,581 events, 944 passes with start + end x/y.

The action-score design (2026-10-01) already planned this: *"WhoScored loader is a later
step."* This design adds WhoScored as the **third provider** of the existing pipeline. No
parallel system.

## Goals

1. `readers/whoscored_spadl.py`: WhoScored events → SPADL per league-season, same contract
   as `statsbomb_spadl.py` / `wyscout_spadl.py` (`fetch_spadl_season` → games, actions, players).
2. `action_score.LEAGUE_SEASONS` gains WhoScored league-seasons. Same VAEP, same
   out-of-fold rating, same site export (`team.html` works unchanged).
3. Link WhoScored players to `player_season` (new `whoscored_id` column) so a report opened
   by `tm_id` can load that player's action file. Same matcher as `link_fotmob`.
4. Weekly refresh of the current season on each league's launchd day.

## Non-goals

- ISL (WhoScored has no ISL; Sofascore is the next design).
- Seasons before 2025/26 (Storage budget, below).
- Scouting UI (separate design; this delivers the data and files it reads).
- Comparing VAEP across providers or leagues. The existing rule stands: one model per
  league-season, never mixed.
- Off-ball value.

## Anti-goals

- **Breaking `team.html` or the existing 9 league-seasons.** Their files and folder names stay.
- **Storing raw events in Postgres.** About 560k events per league-season. Raw events go to
  the local cache, and only the existing per-player JSON goes to Storage.
- **Over the Storage cap.** Over 1 GB, uploads fail and the live site loses new files.

## Constraints (verified 2026-10-23)

| Fact | Value |
|---|---|
| Access | `soccerdata.WhoScored(..., headless=False)` = real Chrome via seleniumbase, user's Mac only (like FBref) |
| soccerdata bug | Chrome wraps JSON responses in `<html><head></head><body>…</body></html>`; `whoscored.py` `json.load` fails. Probe fixed it by stripping the wrapper. |
| Speed | schedule ≈ 105 s per league-season · events ≈ 12 s per match |
| Volume | ≈ 1.6k events per match; Big-5 season = 1,752 matches ≈ 2.8M events |
| Backfill time | 2025/26 ≈ 5.8 h · current season so far (≈ 350 matches) ≈ 1.2 h |
| Storage | 677 MB used / 1 GB (statcast 259, fotmob 250, action-score 168) |
| Site export size | ≈ 22 MB of `player_actions/*.json` per league-season (measured on Wyscout/StatsBomb) |
| DB | 422 MB / 500. This design adds one `bigint` column only. |
| Loader | `WhoScored.read_events(output_fmt="loader")` returns a socceraction `OptaLoader` → `socceraction.spadl.opta.convert_to_actions` |

## Seasons and Storage budget

| Option | Storage after | Note |
|---|---|---|
| **2025/26 only** | ≈ 787 MB | 5 × 22 MB |
| **2025/26 + current 2026/27** (weekly) | ≈ 900 MB by season end | tight; the current season grows each week |
| 2021/22 → now | ≈ 1.3 GB | over the cap: not possible on the free tier |

**Open question 1** decides between the first two.

## Data model

Migration `0013_whoscored_id.sql` (user applies):

```sql
alter table player_season add column if not exists whoscored_id bigint;
```

Nothing else in Postgres. Per league-season the existing export writes `players.json`,
`zones.json`, `games.json` (small, in git) and `player_actions/<player_id>.json` (Storage
bucket `action-score`, path `<league-slug>-<season>/player_actions/<id>.json`, same as today).

## Code changes

| File | Change |
|---|---|
| new `readers/whoscored_spadl.py` | `fetch_whoscored_spadl(league, season, force)` on `spadl_season.fetch_spadl_season`; loader from `soccerdata.WhoScored(...).read_events(output_fmt="loader")`; patches the HTML-wrapper bug at call time (same pattern as `fbref._patch_league_config`). Docstring states provider differences, as Wyscout's does. |
| `pipelines/action_score.py` | `LEAGUE_SEASONS` gets `("ENG-Premier League", "2025"): ("whoscored", None, None)` etc.; `build_action_score` dispatches the third provider. Nothing else changes. |
| `pipelines/fotmob_isl.py` (or beside `action_score`) | `link_whoscored(league, season) -> (linked, hub_rows)`: the `link_fotmob` pattern on `players` minutes → `player_season.whoscored_id`. |
| `scripts/refresh_fbref_chain.py` | on each Big-5 day after FotMob: WhoScored fetch of new matches → rebuild that league's current action score → upload player files → link. Broad `except` like FotMob (it fails with plain errors). |
| `site/team.html` | add the new folders to its `[folder, league, season, provider]` list (one line each). |
| tests | reader on a saved small loader fixture (2 games); `LEAGUE_SEASONS` dispatch; link reuse; refresh-day order. |

## Rating the current season

Out-of-fold, exactly like the other league-seasons, rebuilt each week. Early in a season the
model trains on few matches, so the export carries `matches_played` and the report labels
VAEP **low confidence below 190 matches** (half a season). My call: it reuses existing code
and is honest about the uncertainty. The alternative, training on last season and rating
this one, is a new code path.

## Weekly cost

About 10 new matches per league per week ≈ 2 min of WhoScored, plus a VAEP rebuild for one
league-season (minutes) and re-upload of that league's ≈ 22 MB of player files (all values
move when the model retrains).

## Risks

- **WhoScored blocks or changes.** It's behind Cloudflare and scraping breaks the ToS (same
  as FBref). A block fails that day's step loudly; other steps still run.
- **soccerdata update** may fix or move the bug; the patch must be a no-op on clean JSON.
- **FBref + WhoScored on the same day** = two browser-gated sources from one IP. If WhoScored
  blocks after FBref, it may need its own day. Watch the first weeks' logs.

## Calls made in this doc (not user decisions — check these)

- WhoScored joins `action_score` as a provider rather than a new pipeline or table.
- Raw events stay in the local cache only; the published artefact is the existing per-player JSON.
- Current season rated out-of-fold, with a 190-match confidence label.
- Player link via a new `player_season.whoscored_id` column, reusing the FotMob link code.

## Decided (user, 2026-10-23)

1. **Seasons: 2025/26 + current 2026/27, weekly.** Storage ≈ 900 MB by May 2027. The next
   big Storage user needs a budget check (or a paid tier) first.

## Open questions (user)

None.

## Left to the builder

- Mapping WhoScored team names to `team.html` labels.
- Whether the HTML-wrapper patch lives in the reader or in a shared soccerdata-patch helper next to `fbref._patch_league_config`.
- Upload only changed player files if a whole-league re-upload proves slow.
