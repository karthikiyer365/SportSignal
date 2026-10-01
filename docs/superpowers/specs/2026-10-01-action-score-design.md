# Action Score (SPADL + VAEP) — v1 Design

Branch: `feat/action-score` · Status: draft for review · Date: 2026-10-01

## Objective

Answer one question on StatsBomb open data, Premier League 2015/16:

> Every time a player touched the ball, did the team become more or less likely to score
> (or concede) in the next 10 actions, and by how much?

Output is a value for every on-ball action (VAEP), a player table built from those values,
and two coach-facing views. Also a learning project: each build step is explained as
concept → code → sanity check.

## Non-goals (v1)

- No Supabase push (2015/16 never refreshes; static JSON instead), no cross-league, no
  current-season data (WhoScored loader is a later step).
- No site page in this plan. Page is plan 2, designed after validation says the ratings hold.
- No claim of causality, no "how good is this player" language. The player table means
  "what he added on the ball in this season", not "quality".
- No off-ball or defensive-positioning value. Not measurable from event data.

## Data

- Source: StatsBomb open data, `competition_id=2`, `season_id=27` (Premier League 2015/16),
  380 complete games, 38 per team. **Verify both ids against `competitions.json` in step 1.**
- Loader: `socceraction.data.statsbomb.StatsBombLoader(getter="remote")`, needs `statsbombpy`.
- Events → SPADL via `socceraction.spadl.statsbomb.convert_to_actions`, then
  `socceraction.spadl.add_names`. SPADL coordinates are 105×68. Raw SPADL is NOT per-team
  normalised: the home team attacks left → right, the away team right → left (verified
  2026-10-01: mean shot x 89.3 home vs 13.8 away). VAEP flips internally, so rating uses raw
  actions; zones and site coordinates use `spadl.play_left_to_right` applied after rating.

## Architecture

```
statsbombpy (remote)
   | StatsBombLoader: games / events / players
   v
readers/statsbomb_spadl.py     fetch_statsbomb_spadl(competition_id, season_id, force=False)
   | per game: events -> SPADL; cached_fetch -> parquet + manifest
   v  datasets: actions (all games, 1 row/action), players (game_id, player, team, minutes_played)
pipelines/action_score.py      build_action_score(competition_id, season_id, force=False)
   |- 2-fold split BY GAME     odd/even games by game_date; train odd -> rate even, then swap
   |- VAEP features/labels     game state before each action; scored/conceded in next 10 actions
   |- VAEP.fit per fold        learner = xgboost (socceraction default)
   |- VAEP.rate                offensive_value, defensive_value, vaep_value per action
   |- aggregate                player_table
   '- validation               3 checks, printed to the run log
   v
data/action_score/*.parquet    actions_vaep, player_table
   | export_action_score_site()
   v
site/data/action_score/*.json  players, zones, top_actions   (static, Netlify serves)
```

New code follows the repo pattern: everything goes through `cached_fetch`
(`src/soccerhub/cache.py`); no second cache path. Public fns exported from
`src/soccerhub/__init__.py`.

## Components

| Unit | Does | Depends on |
|---|---|---|
| `readers/statsbomb_spadl.py` | Fetch, convert to SPADL, cache | `socceraction.data`, `statsbombpy`, `cached_fetch` |
| `pipelines/action_score.py` | Split, train, rate, aggregate, validate | `socceraction.vaep`, SPADL parquet |
| `tests/test_action_score.py` | Split-by-game no-overlap check + tiny hand-built game end-to-end | pandas only, no network |

## Output schemas

`actions_vaep` — SPADL columns + `add_names()` + `offensive_value, defensive_value,
vaep_value, start_zone`, plus `fold, p_scores, p_concedes, label_scores, label_concedes`
(kept so validation reads one file, no re-fit).

`player_table` — `player_id, team_id, player_name, team_name, minutes, n_actions, vaep_total,
vaep_per90`. One row per player per team (mid-season movers get two rows). `vaep_per90 = vaep_total / minutes * 90`. Never shown without `minutes`.
Ranking views filter to `minutes >= 900` (**a guess, not derived** — revisit after the
reliability check).

Coach views (in Python, computed from `actions_vaep`; exported for the site, see Delivery):
1. Top/bottom actions — per team per match, the 10 highest and 10 lowest `vaep_value`
   actions, with `period_id`, `time_seconds`/minute, player, type, result.
2. Zone summary — `actions.groupby(["team_id", "start_zone"])["vaep_value"].sum()`.
   `start_zone` = 3 thirds by `start_x` (own / middle / attacking) × 3 lanes by `start_y`
   (left / centre / right) = 9 zones.

## Delivery (site)

Destination: the "Scouting Screens" surface on the site (`site/index.html:185-189`), as an
analysis-format dashboard labelled "Action Score — Premier League 2015/16". It is not the
Moneyball screen the card describes (no prices, no current players); that needs current data.

`export_action_score_site(out_dir="site/data/action_score")` writes 3 static JSON files,
records-oriented (`df.to_json(orient="records")`), served by Netlify as-is:

| File | Rows (approx) | Content |
|---|---|---|
| `players.json` | ~500 | `player_table` + `team_name` |
| `zones.json` | ~180 | zone summary per team |
| `top_actions.json` | ~15k | per team per match, 10 highest + 10 lowest actions |

No Supabase table, no migration, no RLS. If `top_actions.json` exceeds ~2 MB, split per team
(`top_actions/<team_id>.json`) — decide after measuring, not before.

## Validation (every run, printed to the run log)

| Check | Pass condition |
|---|---|
| Calibration | Out-of-fold P(score): `sklearn.calibration.calibration_curve`, `roc_auc_score`, `brier_score_loss` |
| Team sanity | Σ `vaep_value` per team correlates with points across 20 teams; points from StatsBomb match `home_score`/`away_score` (verify field present). Leicester and Spurs near the top, else treat as a bug |
| Reliability | Per-90 `vaep_value` on odd vs even games (same split as training) per player, Spearman correlation; only players with ≥450 min in each half. Near 0 means the ranking is noise |

Liabilities printed with the table: model dependence (one StatsBomb season, one learner);
blind spots (undervalues defending; off-ball runs invisible; team style, e.g. Leicester's
counter-attacking, inflates their players).

## Dependencies (pyproject.toml)

- `socceraction>=1.5` (already added on this branch)
- `multimethod<1.11` — `pandera` 0.17.2 crashes on multimethod 2.x
  (`ImportError: cannot import name 'overload'`); verified locally
- `statsbombpy` (remote getter)
- `xgboost` — `VAEP.fit` defaults to it; none of xgboost/lightgbm/catboost installed. May need
  `libomp` on macOS (verify)
- socceraction pulls `pandas<3`, `numpy<2`, `lxml<5`; this downgrades pandas 3.0.3 → 2.3.3
  for the whole package, including CI and launchd. Run full test suite on the branch first.

## Decision log

| Concern | Decision | Why | Open |
|---|---|---|---|
| Leakage | 2-fold split by `game_id` (odd/even by `game_date`), rate each game out-of-fold | Actions in a match are correlated; in-sample ratings flatter the model. Same split feeds the reliability check | Each model trains on 190 games, not 304. Move to 5-fold if calibration looks poor |
| Scope | Single season, single league | Complete coverage = fair table | Cross-league needs `context-adjustment` |

## Teaching build order (each step: concept → code → check)

1. Load one game; look at raw events next to its SPADL rows.
2. Convert + cache all 380 games.
3. Game-state features; labels; inspect a few rows by hand.
4. Fit one fold; read AUC/Brier/calibration.
5. Rate actions; sanity-read the best and worst actions of one match.
6. Player table + coach views.
7. Run the three validation checks; decide whether the ranking is trustworthy.

## Risks

- Remote fetch of 380 games is slow and may rate-limit; cache converts once, `force` re-fetches.
- StatsBomb coverage claims above were verified on 2026-09-30 from `competitions.json` /
  `matches/` only; the two season ids are still to be confirmed in step 1.
- The 3 validation checks might say the ranking is noise. That is a valid outcome, not a failure.

## v1 results (2026-10-01, seeded run, PL 2015/16)

758,434 actions rated out-of-fold. Rating run: 56 s, peak memory 4.1 GB (no fallback needed).

| Check | Value | Reading |
|---|---|---|
| AUC scores / concedes | 0.795 / 0.792 | In the range published VAEP models report |
| Brier scores | 0.0090 vs 0.0108 base-rate baseline | ~17% better than always predicting the 1.09% base rate |
| Calibration max gap | 0.005 | Predicted goal odds track observed rates |
| Team sanity (Spearman vs points) | 0.768 | Strong. Aston Villa last. Spurs 4th, Leicester 6th — not "near the top": team VAEP sums volume of on-ball actions, and counter-attacking Leicester had less of the ball. A known VAEP property, not a bug |
| Reliability (odd vs even games, n=293) | 0.313 | Real but weak signal: per-90 ranking is directional, not precise; neighbours within a few places are a coin flip |

Verdict: model trustworthy; player ranking usable as tiers (top/middle/bottom), not as exact ranks.
The site must show it that way. `top_actions.json` is 5.2 MB (> 2 MB): split per team in plan 2.

## v1.1 — four leagues (2026-10-01)

Same pipeline, one model per league (styles differ; compare within a league only).

| League 2015/16 | AUC | Team Spearman | Reliability (n) |
|---|---|---|---|
| Premier League | 0.795 | 0.768 | 0.313 (293) |
| La Liga | 0.806 | 0.587 | 0.253 (298) |
| Serie A | 0.790 | 0.792 | 0.359 (292) |
| Ligue 1 | 0.791 | 0.452 | 0.266 (300) |

Ligue 1's low team Spearman: PSG top (93 pts) and Troyes near bottom (18) as expected, but the middle
is bunched (Lille 60 pts sits 14th on VAEP). Site export changed: per-match top actions replaced by
every action per player (`player_actions/`, ~25 MB/league, git-ignored, live copy in Supabase Storage).
