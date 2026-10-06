# Baseball Analytics

Quantitative baseball research projects aimed at a Baseball Analytics / Baseball Systems role. Python (`pybaseball`) + SQL, free public data only.

Last verified: 2026-10-05. Source availability and trend scores come from web checks on that date; re-verify before relying on them.

## Role being targeted

- Build statistical models for baseball operations questions, with sound judgment on model choice.
- Interpret data and report conclusions.
- Present outputs to technical and non-technical audiences.
- Work with Baseball Analytics and Baseball Ops to scope research.
- Advise data engineering on desired outputs; guide Baseball Systems on presenting model results.
- Evaluate new data sources and technologies for validity and usefulness.
- Track public analytics research to improve modeling.

## Active scope

Two separate projects. Nothing else starts until both are done.

| # | Project | Domain | Techniques | Data | Depth |
|---|---|---|---|---|---|
| 1 | Pitch-quality model (Stuff+ / run value per pitch) | Pitching, player dev | GBM, hierarchical models, SHAP | Statcast | 2015-26 |
| 3 | Bat-tracking swing model (swing speed and path -> damage / whiff) | Hitting, player dev | Mixed models, GAM, clustering of swing types | Savant bat tracking | 2023-26 (short) |

Project 3 has about 3 seasons of data, so frame it partly as a data-validity study. That also covers the "evaluate new data sources" bullet.

## Data source check

Trending = how actively the industry pursues what the source supports (1 low, 5 high). Scores are judgment from search evidence.

| Source | Depth | Status | Trending |
|---|---|---|---|
| Statcast / Baseball Savant | Pitch-level 2008+; true Statcast velo 2017+; 700k+ pitches per season; fielder IDs 2-9, alignment, spin and release fields | verified | 5 |
| Savant bat tracking | Swing speed, attack angle, swing path tilt, intercept point; 2H 2023+ | verified, short | 5 |
| Retrosheet | Play-by-play 1908-2025, box scores back to 1871. Free for any use with attribution. | verified | 2 |
| Lahman DB | 1871-2025, released Jan 2026. Negro Leagues data from Seamheads. | verified | 2 |
| pybaseball | Wraps Savant, FanGraphs, BRef, Lahman, Chadwick, Retrosheet | verified | 3 |
| Minor-league Statcast | Triple-A 2023+, Single-A Florida State League 2021+, no Double-A. MLB reportedly harmonizing minors tech, so Double-A / High-A may open. | verified, thin | 4 |
| Injury data | Retrosheet transactions frozen; public IL data 2000-2016 only | stale | 4 |
| Draft / prospect rankings | No bulk export or API; scraping only | weak | 3 |
| Salaries (recent) | Lahman salary years unverified; Spotrac / Cot's need scraping | partial | 3 |
| Skeletal / biomech tracking | Not public | gap | 5 (no public access) |

Notes:
- pybaseball caveat: each season is 700k+ pitches and subject to update; BRef queries return one season per request.
- Retrosheet license: free to use including commercial, must carry the Retrosheet attribution line.
- Statcast docs state no CSV row limit; pull by date chunks anyway.

## Full project menu (backlog after the two active ones)

| # | Project | Domain | Data | Feasible | Trending |
|---|---|---|---|---|---|
| 1 | Pitch-quality model (active) | Pitching, player dev | Statcast | high | 5 |
| 2 | Hitter true-talent and breakout forecast | Hitting, projections | Lahman, FanGraphs, Statcast | high | 4 |
| 3 | Bat-tracking swing model (active) | Hitting, player dev | Savant bat tracking | high, short history | 5 |
| 4 | Catcher framing and strike-zone model | Defense, umpires | Statcast | high | 4 |
| 5 | Defense and positioning, shift-ban impact | Defense, strategy | Statcast fielder IDs / alignment | high | 3 |
| 6 | Win probability, leverage, bullpen/manager decisions | Strategy | Retrosheet | very high | 3 |
| 7 | Aging curves and survival | Roster planning | Lahman, FanGraphs | very high | 3 |
| 8 | Pitcher workload and injury risk | Health | Statcast + IL | labels stale after 2016 | 4 |
| 9 | Minor-league to MLB translation | Scouting | MLB Stats API, Savant MiLB | thin | 4 |
| 10 | Pitch sequencing, tunneling, arsenal optimization | Pitching strategy | Statcast | high | 4 |
| 11 | Park factors and environment | Evaluation | Retrosheet, Statcast | high | 3 |
| 12 | Salary vs WAR / contract valuation | Front office | Lahman, scraped Spotrac | weak | 3 |

Dropped for lack of public bulk data: draft-pick value model, biomechanics.

Job-fit mapping:

| Requirement | Best projects |
|---|---|
| Statistical breadth | 2, 4, 7 |
| Answer ops questions | 6, 5, 12 |
| Present to non-technical users | 1, 6 |
| Evaluate new data sources | 3, 9 |
| Advise data engineering | 1, 6 |

Suggested follow-ups after the two active projects: #10 (same Statcast backbone) then #2.

## Trend evidence

| Trending | Evidence |
|---|---|
| 5, pitch quality (#1) | FanGraphs hosts PitchingBot and Stuff+ leaderboards. THE BAT X for pitchers launched Feb 2026. Apr 2026: arm-angle-adjusted movement is already a main driver of Stuff+. Risk: crowded, FanGraphs already ships it. |
| 5, bat tracking (#3) | FanGraphs added Statcast bat tracking to player pages and leaderboards Mar 2026. A BP bat-and-pitch-tracking article was a 2026 SABR Analytics research-award finalist. Risk: crowded, short history. |
| 4, hitter projections (#2) | ZiPS, Steamer, THE BAT X, PECOTA all published 2026 systems. Mature and crowded. |
| 4, framing (#4) | ABS challenge system live in MLB 2026. Coverage argues framing still matters. |
| 4, injury risk (#8) | 2025-26 papers on XGBoost with pitch tracking, Tommy John models, broadcast-video screening (AUC 0.81-0.93). Authors use non-public data. |
| 4, MiLB translation (#9) | Stuff models on Triple-A, Prospect Savant, PECOTA 2026 update. |
| 4, sequencing (#10) | Counterfactual pitch-sequence arXiv paper (Jun 2026); Mix+/Match+ tunneling metrics. |
| 3, shift ban (#5) | Ban dates to 2023; groundball-hit gains plateaued by 2025. |
| 3, win probability (#6) | Mature; evidence thin, mostly low-quality blogs. Least supported score. |
| 3, aging (#7) | FanGraphs revisits regularly; publication dates unconfirmed. |
| 3, park factors (#11) | Active in betting/fantasy, little front-office research. |
| 3, $/WAR (#12) | Annual FanGraphs free-agency piece; niche. |
| 2, Retrosheet / Lahman | Stable archives; judgment only. |

## Sources

- Statcast CSV docs: https://baseballsavant.mlb.com/csv-docs
- Retrosheet: https://www.retrosheet.org/game.htm
- Retrosheet transactions: https://www.retrosheet.org/transactions/
- pybaseball: https://github.com/jldbc/pybaseball
- Lahman / SABR: https://sabr.org/lahman-database/
- Savant minors: https://baseballsavant.mlb.com/statcast-search-minors
- Savant bat tracking: https://baseballsavant.mlb.com/leaderboard/bat-tracking/swing-path-attack-angle
- FanGraphs pitch modeling: https://blogs.fangraphs.com/pitchingbot-and-stuff-pitch-modeling-are-now-on-fangraphs/
- THE BAT X pitchers: https://blogs.fangraphs.com/introducing-the-bat-x-for-pitchers-and-the-batcast-stuff-model/
- FanGraphs bat tracking: https://blogs.fangraphs.com/instagraphs/statcast-bat-tracking-metrics-are-now-on-fangraphs/
- BP swing processes: https://www.baseballprospectus.com/news/article/103703/best-of-bp-2025-understanding-swing-processes-through-bat-and-pitch-tracking/
- SABR 2026 finalists: https://sabr.org/latest/announcing-finalists-for-2026-sabr-analytics-conference-research-awards/
- ESPN ABS: https://www.espn.com/mlb/story/_/id/48807610/mlb-2026-abs-automated-balls-strikes-system-early-numbers-lessons-analytics
- Injury ML (PMC): https://pmc.ncbi.nlm.nih.gov/articles/PMC11369970/
- Broadcast-video injury screening: https://arxiv.org/html/2603.04864v1
- Tommy John models: https://link.springer.com/article/10.1186/s40537-025-01138-1
- Pitch-sequence arXiv: https://arxiv.org/abs/2606.17345
- Triple-A stuff models: https://www.prospectslive.com/an-introduction-to-the-application-of-stuff-models-on-triple-a-data/
- PECOTA 2026: https://www.baseballprospectus.com/news/article/104636/pecota-2026-updates-and-ongoing-challenges/
- Prospect Savant: https://prospectsavant.com/
- FanGraphs $/WAR 2026: https://blogs.fangraphs.com/what-are-teams-paying-for-a-win-in-free-agency-2026-edition/

## Pitch-quality build (phases 1-3)

Branch `feat/pitch-quality`. Seasons 2020-2026 regular season (Hawk-Eye era).

| Piece | Where |
|---|---|
| Pipeline | `Soccer Data Hub/src/soccerhub/pipelines/statcast.py` (reuses `upsert_df`, `cached_fetch`) |
| Run | `python -m soccerhub.pipelines.statcast [--force] [--upload] [2024 2025 ...]` |
| Raw cache | `Soccer Data Hub/data/statcast/*.parquet`, one per month, all ~119 cols (bat-tracking reuses it) |
| Pitch files for Colab | Supabase Storage, public bucket `statcast`, `pitches/<season>/<MM>.parquet` (~7 MB each) |
| DB table | `pitch_arsenal`, season x pitcher x pitch_type with n >= 25 (~25k rows), migration `0011` |
| Notebook | `pitch-quality/pitch_quality_baseline.ipynb` (Colab) |
| Tests | `Soccer Data Hub/tests/test_statcast.py` |

Decisions:
- Pitch-level data stays out of Postgres: a raw season is ~0.4-0.8 GB vs the 500 MB free-plan DB cap, and going over makes the DB read-only, which would break the live football site.
- One Storage file per month, not per season: a slim season is ~45-50 MB, at the 50 MB free-plan file limit.
- Left-handed pitchers are mirrored once in the pipeline (`pfx_x`, `release_pos_x`, `vx0`, `ax`, `spin_axis -> 360 - axis`). `plate_x` and `arm_angle` stay raw.
- Pitcher run value = `-delta_run_exp`. Checked on real data: a ball averages +0.058 and a called strike -0.064, so the raw column is the batter's view.
- `player_name` in `statcast()` output is the pitcher (checked on real data).
- `xwobacon` is xwOBA on contact only (`estimated_woba_using_speedangle` exists only for batted balls).
- pybaseball's own cache stays off; `cached_fetch` is the only cache, which avoids the two-cache stale-data trap.

Model decisions (analyst review, 2026-10-05), validated by the notebook's charts V1-V7:

| Decision | Choice | Evidence |
|---|---|---|
| Target | `xrv`: balls in play valued by their xwOBA bin, everything else actual `-delta_run_exp` | Tied 2-2 with actual rv over four season-pair forecasts (mean diff +0.009). Kept for theory: strips defense and luck. |
| Split | Train 2021-24, validate 2025, test 2026, plus 2020 as an extra test season | 2020 per-pitch R² 0.00278 with arm angle vs 0.00271 without; missing arm angle barely hurts |
| Stuff+ scale | `stuff_plus` (one scale, all pitches) and `stuff_plus_type` (within pitch type) | Pitch-mix questions need one scale; "best changeup" needs within-type |
| Site skill number | Stuff+ planned, on hold until it beats CSW% (see scrutiny result below) | Actual RV/100 is 0.20 at 400 pitches, so it's shown as "results", not skill |
| Site cutoff | `MIN_PITCHES_RV = 50` gates `whiff_pct` | Whiff split-half reaches 0.5 at 50 pitches |
| Explainability | xgboost `pred_contribs` (exact TreeSHAP) instead of the shap package | shap 0.49 can't read xgboost 3.x models; avoids a numpy-2 dependency that breaks socceraction |

Scrutiny result (analyst review 2, same day): **the baseline model does not beat CSW%.**

| Test | Stuff (XGBoost xrv) | CSW% |
|---|---|---|
| 2025 -> 2026 RV/100 (V3) | 0.184 | 0.186 (diff -0.002, 95% CI -0.066 to +0.061) |
| First 25 pitches of 2026 -> rest of season (V8) | 0.118 | 0.133 |
| First 50 | 0.118 | 0.168 |
| First 100 | 0.169 | 0.178 |
| First 200 | 0.133 | 0.200 |

CSW% carries location and command through called strikes; this model is physics only. Stuff is stable early (V4), but stable is not the same as predictive.

Next phase, in order:
1. Fix the scoring target. Next-season RV/100 per pitcher-pitch type has only 0.20 split-half reliability at 400 pitches, so any forecast's r is capped near sqrt(0.2) ≈ 0.45 and every result looks small. Add pitcher-level next-season K% and BB% (from the stored `events` column) as forecast targets alongside RV/100. They are less noisy and are what front offices act on.
2. Stuff + CSW% blend weighted by sample size.
3. Location + count Pitching+ variant, the like-for-like comparison with CSW%.
4. Shrinkage: pitcher-level Stuff over-predicts the top decile (1.22 vs 0.88 xrv per 100).
5. Per-pitch-type models; merge slider and sweeper into one family (sweeper share went 2.3% in 2021 to 8.3% in 2026).
6. Stuff+ columns to `pitch_arsenal` (migration 0012), only after 2-3 show it adds signal.

Caveat on the 2020 test season: 2020 was a 60-game COVID season (no fans, universal DH, 7-inning doubleheaders, runner on second in extras). Its score only answers "does the model cope with missing arm angle"; never quote it as overall model quality.

Manual steps (user): apply `0011_pitch_arsenal.sql` in the SQL editor; create a public Storage bucket `statcast`.

## Pitcher Perfect (live site page)

`site/baseball.html`, linked from the Baseball button in the landing page's sport switcher. URL state: `?p=<MLBAM id>&s=<season>`; defaults to Paul Skenes.

| Part | Source | Load |
|---|---|---|
| Search, arsenal table, velo by season | `pitch_arsenal` via `hub()` (publishable key) | instant |
| Pitcher percentile radar | `pitch_arsenal`, whole season as the pool (pitchers with 300+ pitches) | instant |
| K-zone, movement, release point, spin clock, velo + d_velo, arm angle and velo by game, pitch mix by situation | Baseball Savant `statcast_search/csv`, fetched live in the browser | ~5 s per pitcher-season |

- Savant serves the CSV with `access-control-allow-origin: *`, so there is no proxy, no export and no Storage cost. If Savant is down, the database sections still render and the live section shows a retry message.
- The radar axes all point "higher is better": fastball velo, ride and spin; extension; best secondary whiff; overall whiff; arsenal depth. Arm angle and release height are style, so they get their own charts.
- Pitch-type colors were validated against the dark panel (`--card #0f4a36`) with the dataviz validator: FF `#ef5d51`, SL `#4f93ec`, SI `#d47a14`, ST `#9f7bee`, FC `#b08f18`, CU/KC `#16a0a8`, CH `#74a42a`, FS `#dc60a8`.
- `pitch_arsenal` stores left-handers mirrored, so the page un-mirrors `spin_axis` before showing tilt. Live Savant data is raw.
- Stuff+ is not on the page until it beats CSW%.

## Open questions

- Bat-tracking project layout: `bat-tracking/` exists, empty until pitch-quality is done.
