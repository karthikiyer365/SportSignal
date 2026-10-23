# ISL FotMob Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill ISL 2021/22 → 2026/27 from FotMob into the existing Supabase tables plus a new `player_match` table, and refresh it every Tuesday from the local launchd job.

**Architecture:** A reader (`readers/fotmob.py`) fetches and caches raw FotMob JSON and archives it to a private bucket. A pipeline (`pipelines/fotmob_isl.py`) parses one match into rows for `matches`, `team_match_understat`, `shots_understat`, `player_match`, sums `player_match` into `player_season`, and upserts with the existing `supa.upsert_df`. The launchd script gains a Tuesday ISL slot.

**Tech Stack:** Python 3.11, pandas, `supabase` client (existing), urllib (no new deps), pytest.

**Spec:** `docs/superpowers/specs/2026-10-22-isl-fotmob-pipeline-design.md`

All paths below are relative to `Soccer Data Hub/` unless they start with `site/`, `docs/` or `.github/`.

## Global Constraints

- League label: `IND-Indian Super League` (constant `ISL_LEAGUE`).
- Season label: start year as text — FotMob `"2024/2025"` ↔ hub `"2024"`. Backfill seasons `2021`–`2026`.
- FotMob league id `9478`. Endpoints: `https://www.fotmob.com/api/data/leagues?id=9478&season=<YYYY%2FYYYY>`, `https://www.fotmob.com/api/data/matchDetails?matchId=<id>`.
- One FotMob request at a time, ≥2 s apart, browser-like `User-Agent`.
- Missing stat → null, never 0.
- `shots_understat.player_id` = FotMob player id for ISL rows only.
- Raw archive: private bucket `fotmob`, path `isl/<season>/<match_id>.json.gz`.
- No new dependencies.
- **Never run SQL that writes.** Migration `0012` is applied by the user in the SQL editor. Supabase MCP is SELECT-only.
- **No commits or pushes until the user says `do CP` / `do CPR`.** "Commit" steps below mean: stage the files and propose the message. Branch: `feat/isl-fetch`. Message format: `feat:isl-<scope>` (matches repo history, e.g. `feat:pitch-quality …`).
- End commit messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Shots on the wrong end / mirrored y.** FotMob shots attack toward x=105; own goals sit near x≈2. Expect every non-own-goal shot `location_x > 0.5` after scaling, and y orientation matching Understat. Pinned in Task 3 (test + one cross-source check).
2. **Players who never came on.** `playerStats` lists unused subs. Expect them absent from `player_match` (minutes 0 → dropped), so `matches_played` isn't inflated. Pinned in Task 3.
3. **Mid-season movers.** A player with two ISL teams in one season must give two `player_season` rows (PK includes `team`), not one merged row. Pinned in Task 4.
4. **Re-running the weekly job.** `push_isl_new()` run twice in a row must fetch zero matches the second time, and never fetch unfinished matches. Pinned in Task 5.
5. **ISL leaking into Big-5 pages.** Searching a common name (e.g. "Singh") on `player.html` must return no ISL rows; a Big-5 shot map must not pick up ISL shots with a colliding id. Pinned in Task 6 (grep check of both query lines).

---

### Task 1: Migration 0012 + conflict keys

**Files:**
- Create: `supabase/migrations/0012_isl_fotmob.sql`
- Modify: `src/soccerhub/pipelines/__init__.py` (constants block, after `SHOTS_CONFLICT_KEY`)

**Interfaces:**
- Produces: `PLAYER_MATCH_CONFLICT_KEY = "league,season,match_id,fotmob_id"`, `ISL_LEAGUE = "IND-Indian Super League"` in `soccerhub.pipelines`. `pipelines/__init__.py` bottom-imports `fotmob_isl` (Task 5), so `fotmob_isl` must import these constants **inside functions**, the way `understat.py` does, to stay cycle-free.

- [ ] **Step 1: Write `0012_isl_fotmob.sql`**

Header comment style as `0010`/`0011` ("Apply manually in SQL editor."). Contents, in order:
1. `create table if not exists player_match (...)` — exact DDL from the spec's "New table — `player_match`" block, incl. RLS + `"anon read only"` policy.
2. `alter table team_match_understat add column if not exists home_possession real, add column if not exists away_possession real;`
3. `alter table shots_understat add column if not exists xgot real;`
4. `alter table player_season add column if not exists` for: `fotmob_id bigint, fotmob_rating real, xgot real, touches_opp_box int, dribbles int, recoveries int, clearances int, blocks int, aerials_won int, duels_won int, passes_final_third int, accurate_passes int`.
5. `insert into storage.buckets (id, name, public) values ('fotmob', 'fotmob', false) on conflict (id) do nothing;`

- [ ] **Step 2: Add the two constants** to `pipelines/__init__.py` next to the other `*_CONFLICT_KEY` lines, with the `# matches 0012 PK` comment style.

- [ ] **Step 3: User applies 0012** in the Supabase SQL editor. Stop and wait.

- [ ] **Step 4: Verify (read-only, MCP)**

```sql
select table_name, column_name from information_schema.columns
where table_schema='public' and (table_name='player_match'
  or column_name in ('home_possession','xgot','fotmob_id','fotmob_rating','passes_final_third'));
select id, public from storage.buckets where id='fotmob';
```
Expected: `player_match` columns listed; `xgot` on both `shots_understat` and `player_season`; bucket `fotmob` with `public=false`.

- [ ] **Step 5: Stage** `supabase/migrations/0012_isl_fotmob.sql src/soccerhub/pipelines/__init__.py`. Message: `feat:isl-schema player_match table and fotmob columns`.

---

### Task 2: FotMob reader

**Files:**
- Create: `src/soccerhub/readers/fotmob.py`
- Test: `tests/test_fotmob.py`

**Interfaces:**
- Produces:
  - `fotmob_season(season: str) -> str` — `"2024"` → `"2024/2025"`.
  - `fetch_league(season: str, force: bool = False) -> dict` — leagues payload for ISL.
  - `fetch_match(match_id: int, season: str, force: bool = False, archive: bool = True) -> dict` — matchDetails payload.
  - `finished_match_ids(league_payload: dict) -> list[int]` — ids where `status.finished` is true and `status.cancelled` is not.

Local raw cache: `cache_root() / "fotmob" / "raw" / f"{name}.json.gz"` (`name` = `league_<season>` or `match_<id>`). A cached match is never re-fetched unless `force`. League payloads are always re-fetched when `force` (current season changes weekly). Pacing: module-level `_last_call` timestamp, `time.sleep` so calls are ≥ `MIN_GAP_S = 2.0` apart. HTTP via `urllib.request` with `User-Agent: Mozilla/5.0 (Macintosh) Chrome/126`, wrapped in `supa.retry`. Archive: when `archive` and the match was freshly downloaded, upload the gz bytes to bucket `fotmob` at `isl/<season>/<match_id>.json.gz` with `upsert` true, same client pattern as `statcast.upload_season`.

- [ ] **Step 1: Write failing tests**

```python
def test_fotmob_season_label():
    from soccerhub.readers.fotmob import fotmob_season
    assert fotmob_season("2021") == "2021/2022"
    assert fotmob_season("2026") == "2026/2027"

def test_fetch_match_uses_cache(monkeypatch):
    import soccerhub.readers.fotmob as fm
    calls = []
    monkeypatch.setattr(fm, "_get_json", lambda url: calls.append(url) or {"general": {"matchId": "1"}})
    monkeypatch.setattr(fm, "_archive", lambda *a: None)
    fm.fetch_match(1, "2024"); fm.fetch_match(1, "2024")
    assert len(calls) == 1

def test_finished_match_ids_skips_unplayed_and_cancelled():
    from soccerhub.readers.fotmob import finished_match_ids
    payload = {"fixtures": {"allMatches": [
        {"id": "10", "status": {"finished": True}},
        {"id": "11", "status": {"finished": False}},
        {"id": "12", "status": {"finished": True, "cancelled": True}},
    ]}}
    assert finished_match_ids(payload) == [10]
```
(Use the repo's autouse `SOCCERHUB_CACHE` → `tmp_path` fixture, as in `tests/test_understat.py`.)

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_fotmob.py -v` → FAIL (module not found).
- [ ] **Step 3: Implement** the four functions plus private `_get_json(url) -> dict` and `_archive(match_id, season, gz_bytes) -> None`.
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_fotmob.py -v` → PASS.
- [ ] **Step 5: Stage** reader + test. Message: `feat:isl-reader fotmob fetch, cache and archive`.

---

### Task 3: Match parser

**Files:**
- Create: `src/soccerhub/pipelines/fotmob_isl.py`
- Create: `tests/fixtures/fotmob_4617934.json.gz` (download once: `fetch_match(4617934, "2024", archive=False)` and copy the cached gz)
- Test: `tests/test_fotmob_isl.py`

**Interfaces:**
- Consumes: payload dict from Task 2.
- Produces: `parse_match(raw: dict, season: str) -> dict[str, pd.DataFrame]` with keys `"matches"`, `"team_match"`, `"shots"`, `"player_match"`, each already carrying `league`, `season` and only columns that exist in the target table.
- Produces: module constants `POSITION = {0: "GK", 1: "DF", 2: "MF", 3: "FW"}` (from `usualPlayingPositionId`), `TEAM_NAMES: dict[int, str] = {}` (FotMob team id → canonical name; filled in Task 7).

Mappings the implementer can't guess (verified on real payloads 2026-10-23):

| Target | FotMob source |
|---|---|
| teams, score | `header.teams[0]` = home, `[1]` = away: `name`, `id`, `score` |
| date | `general.matchTimeUTCDate[:10]` |
| referee | `content.matchFacts.infoBox.Referee.text` (empty string → null) |
| team stats `[home, away]` | `content.stats.Periods.All.stats[*].stats[*]` by `key`: `BallPossesion`, `expected_goals`, `expected_goals_non_penalty`, `total_shots`, `ShotsOnTarget`, `corners`, `fouls`, `yellow_cards`, `red_cards` — values may be strings (`"1.10"`); first occurrence of a key wins |
| HT score | score on the `matchFacts.events` entry with `type == "Half"` that ends the first half |
| shots | `content.shotmap.shots`; `location_x = x/105`, `location_y = y/68`; `xg = expectedGoals`, `xgot = expectedGoalsOnTarget`; `player_id = playerId`; `game_id = matchId` |
| shot `result` | `isOwnGoal` → `Own Goal`; `Goal` → `Goal`; `AttemptSaved` + `isBlocked` → `Blocked Shot`; `AttemptSaved` → `Saved Shot`; `Miss` → `Missed Shot`; `Post` → `Shot On Post` |
| shot `situation` | `RegularPlay`/`FastBreak` → `Open Play`; `FromCorner` → `From Corner`; `SetPiece`/`ThrowInSetPiece` → `Set Piece`; `FreeKick` → `Direct Freekick`; `Penalty` → `Penalty`; unknown → raw value |
| shot `body_part` | `RightFoot` → `Right Foot`; `LeftFoot` → `Left Foot`; `Header` → `Head`; else null |
| player stats | `content.playerStats[pid].stats[*].stats[title]` → read by inner `key`, value `stat.value` (missing `value` → null): `minutes_played, rating_title, goals, assists, expected_goals, expected_goals_on_target_variant, expected_assists, expected_goals_non_penalty, total_shots, ShotsOnTarget, big_chance_missed_title, chances_created, accurate_passes (value=accurate, total=passes), passes_into_final_third, long_balls_accurate, touches, touches_opp_box, dribbles_succeeded, dispossessed, matchstats.headers.tackles, interceptions, clearances, shot_blocks, recoveries, dribbled_past, duel_won, duel_lost, aerials_won, ground_duels_won, fouls, was_fouled, saves, goals_conceded` |
| starters | ids in `content.lineup.{homeTeam,awayTeam}.starters` |
| position | `POSITION[usualPosition or usualPlayingPositionId]` |
| cards per player | `matchFacts.events` with `type == "Card"`, `card` ∈ `Yellow`/`Red`, by `player.id` |

- [ ] **Step 1: Write failing tests** (load the fixture with `gzip` + `json`):

```python
def test_parse_match_row(parsed):
    m = parsed["matches"].iloc[0]
    assert (m.home_team, m.away_team, m.home_goals, m.away_goals) == ("Mohun Bagan SG", "Mumbai City FC", 2, 2)
    assert m.league == "IND-Indian Super League" and m.season == "2024" and m.date == "2024-09-13"
    assert m.home_shots + m.away_shots == 20 and m.home_yellow + m.away_yellow == 8

def test_team_match_possession(parsed):
    t = parsed["team_match"].iloc[0]
    assert (t.home_possession, t.away_possession) == (46, 54)
    assert t.game_id == 4617934 and pd.isna(t.home_ppda)

def test_shots_scaled_and_vocab(parsed):
    s = parsed["shots"]
    assert len(s) == 21
    assert s.location_x.between(0, 1).all() and s.location_y.between(0, 1).all()
    assert (s[s.result != "Own Goal"].location_x > 0.5).all()
    assert set(s.result) <= {"Goal", "Own Goal", "Saved Shot", "Missed Shot", "Blocked Shot", "Shot On Post"}
    assert (s.result == "Own Goal").sum() == 1

def test_player_match_drops_unused_and_keeps_nulls(parsed):
    p = parsed["player_match"]
    assert (p.minutes > 0).all()
    assert p.is_starter.sum() == 22
    toral = p[p.player_name == "Jon Toral"].iloc[0]
    assert pd.isna(toral.xgot)          # stat present, no value -> null, not 0
    assert p.yellow_cards.sum() == 8
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_fotmob_isl.py -v` → FAIL.
- [ ] **Step 3: Implement `parse_match`** with the mapping table above. Apply `TEAM_NAMES.get(team_id, name)` wherever a team name is written.
- [ ] **Step 4: Run** the tests → PASS.
- [ ] **Step 5: Cross-source y check (one-off, not a test).** Fetch one 2024/25 Premier League match from FotMob (league id 47), pick one goal, and find the same goal in `shots_understat` (MCP SELECT by date, team and minute). Confirm `y/68` and Understat `location_y` agree within 0.05. If they're mirrored, change to `1 - y/68` and add a `ponytail:` comment naming the check. Record the result in the PR body.
- [ ] **Step 6: Stage** parser, fixture and tests. Message: `feat:isl-parser fotmob match to hub rows`.

---

### Task 4: Season aggregation

**Files:**
- Modify: `src/soccerhub/pipelines/fotmob_isl.py`
- Test: `tests/test_fotmob_isl.py`

**Interfaces:**
- Consumes: concatenated `player_match` DataFrame from Task 3.
- Produces: `season_rows(pm: pd.DataFrame, shots: pd.DataFrame) -> pd.DataFrame`. One row per `(league, season, team, player_name)` with `player_season` columns only.

Rules: sums for counts, xg, np_xg, xa, xgot. `matches_played` = rows, `starts` = `is_starter` sum, `nineties = minutes/90` rounded to 1, `*_per90` = total / nineties (null when nineties = 0). `primary_position` = most common `position`, with `position` the same. `fotmob_rating` = minutes-weighted mean of `rating`. Penalties come from `shots` where `situation == "Penalty"`: `penalties_attempted` = count, `penalties_scored` = goals, and `non_penalty_goals = goals - penalties_scored`. `key_passes` = `chances_created`. `xref_method`, `tm_id`, `age`, `nationality` and market value are not set, so DB defaults or nulls apply. (`nationality` is a deliberate deviation from the spec: `player_match` has no nationality column, and adding one just for this isn't worth it. Add it when the dashboard needs it.)

- [ ] **Step 1: Write failing tests**

```python
def test_season_rows_sums_and_per90():
    pm = _pm([  # helper builds player_match rows
        dict(match_id=1, fotmob_id=7, team="FC Goa", player_name="A", minutes=90, goals=1, is_starter=True, position="FW", rating=7.0),
        dict(match_id=2, fotmob_id=7, team="FC Goa", player_name="A", minutes=45, goals=0, is_starter=False, position="FW", rating=6.0),
    ])
    r = season_rows(pm, _shots([])).iloc[0]
    assert (r.matches_played, r.starts, r.minutes, r.goals) == (2, 1, 135, 1)
    assert r.nineties == 1.5 and round(r.goals_per90, 3) == 0.667
    assert round(r.fotmob_rating, 3) == 6.667

def test_mover_gets_one_row_per_team():
    pm = _pm([dict(match_id=1, fotmob_id=7, team="FC Goa", player_name="A", minutes=90),
              dict(match_id=9, fotmob_id=7, team="Odisha FC", player_name="A", minutes=90)])
    assert set(season_rows(pm, _shots([])).team) == {"FC Goa", "Odisha FC"}

def test_penalties_split_from_open_play():
    pm = _pm([dict(match_id=1, fotmob_id=7, team="FC Goa", player_name="A", minutes=90, goals=2)])
    shots = _shots([dict(player_id=7, team="FC Goa", situation="Penalty", result="Goal")])
    r = season_rows(pm, shots).iloc[0]
    assert (r.penalties_attempted, r.penalties_scored, r.non_penalty_goals) == (1, 1, 1)
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Stage.** Message: `feat:isl-season player_season rows from player_match`.

---

### Task 5: Push functions

**Files:**
- Modify: `src/soccerhub/pipelines/fotmob_isl.py`, `src/soccerhub/pipelines/__init__.py` (export + bottom import like the Understat block), `src/soccerhub/__init__.py` (re-export, matching how `push_shots` is exported)
- Test: `tests/test_fotmob_isl.py`

**Interfaces:**
- Consumes: Tasks 2–4. `upsert_df(df, table, on_conflict)`, `read_hub(table, select, **eq)`.
- Produces:
  - `push_isl(season: str, force: bool = False, match_ids: list[int] | None = None) -> dict[str, int]` — fetch league → finished ids (or `match_ids`) → `fetch_match` each → `parse_match` → concat → upsert `matches` (`MATCHES_CONFLICT_KEY`), `team_match_understat` (`TEAM_MATCH_CONFLICT_KEY`), `shots_understat` (`SHOTS_CONFLICT_KEY`), `player_match` (`PLAYER_MATCH_CONFLICT_KEY`). Then re-read the season's full `player_match` + ISL `shots_understat` via `read_hub`, run `season_rows`, and upsert `player_season` (`CONFLICT_KEY_PLAYER_SEASON`). Returns rows per table.
  - `push_isl_new() -> dict[str, int]` — season = latest entry in `fetch_league(..., force=True)["allAvailableSeasons"]` converted to a start year (not `current_season()`: ISL 2025/26 started in Feb 2026). Stored ids = distinct `match_id` from `read_hub("player_match", select="match_id", league=ISL_LEAGUE, season=s)`. Calls `push_isl(s, match_ids=new)` only when there are new ids. Otherwise returns `{}`.
  - `__main__`: `python -m soccerhub.pipelines.fotmob_isl 2021 2022 …` runs `push_isl` per season and prints the counts.

- [ ] **Step 1: Write failing tests** (monkeypatch `fetch_league`, `fetch_match`, `read_hub`, `upsert_df`, using the fixture as every match payload):

```python
def test_push_isl_new_fetches_only_missing(monkeypatch):
    # league lists finished ids [4617934, 555]; player_match already has 4617934
    ...
    assert fetched == [555]

def test_push_isl_new_is_noop_when_up_to_date(monkeypatch):
    # stored == finished
    assert push_isl_new() == {} and fetched == []

def test_push_isl_upserts_every_table_with_its_key(monkeypatch):
    out = push_isl("2024", match_ids=[4617934])
    assert {t for t, _ in upserts} == {"matches", "team_match_understat", "shots_understat", "player_match", "player_season"}
    assert dict(upserts)["player_match"] == "league,season,match_id,fotmob_id"
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run the whole suite** `.venv/bin/pytest -q` → all PASS, including `tests/test_exports.py`.
- [ ] **Step 5: Stage.** Message: `feat:isl-push backfill and weekly-new upserts`.

---

### Task 6: Keep ISL off the Big-5 pages

**Files:**
- Modify: `site/player.html:301-303` (search), `site/player.html:1382-1384` (shot map)

- [ ] **Step 1: Add the filter to both queries.** The value is identical in both:

```js
league: "neq.IND-Indian Super League",
```
Search: add it after `player_name: …`. Shot map: add it after `player_id:`eq.${uid}``.

- [ ] **Step 2: Verify**

Run: `grep -n 'neq.IND-Indian Super League' site/player.html`
Expected: exactly 2 lines, one near 302 and one near 1383.

- [ ] **Step 3: User checks in browser** (per user preference, no Playwright loop). After Task 8 data lands, search "Singh" on `player.html`; expected: no ISL clubs in the results.
- [ ] **Step 4: Stage.** Message: `fix:player-page hide ISL rows from Big-5 search and shot map (#31)`.

---

### Task 7: Weekly schedule

**Files:**
- Modify: `scripts/refresh_fbref_chain.py`, `scripts/com.ikarthik.soccerhub-fbref.plist`, `tests/test_refresh_script.py`
- Modify: `.github/workflows/run-season.yml` (repo root)

**Interfaces:**
- Consumes: `push_isl_new` from Task 5.
- Produces: `SCHEDULE: dict[int, str]` in the script, `{0: "ENG-Premier League", 1: "IND-Indian Super League", 2: "ESP-La Liga", 3: "GER-Bundesliga", 4: "ITA-Serie A", 5: "FRA-Ligue 1"}`. `LEAGUES` is kept as `list(SCHEDULE.values())` so `--all` and `LEAGUE=` still work. `leagues_for_today` returns `[SCHEDULE[weekday]]` or `[]`.

- [ ] **Step 1: Update the tests.** Replace the parametrize table:

```python
("2026-09-28", "ENG-Premier League"),       # Monday
("2026-09-29", "IND-Indian Super League"),  # Tuesday
("2026-09-30", "ESP-La Liga"),              # Wednesday
("2026-10-01", "GER-Bundesliga"),           # Thursday
("2026-10-02", "ITA-Serie A"),              # Friday
("2026-10-03", "FRA-Ligue 1"),              # Saturday
```
Weekend test becomes Sunday only (`"2026-10-04"`). Replace `test_every_league_has_a_weekday` with `assert len(mod.SCHEDULE) <= 7 and set(mod.LEAGUES) == set(mod.SCHEDULE.values())`. Add:

```python
def test_isl_day_runs_isl_not_fbref(mod, monkeypatch):
    # main() on a Tuesday calls push_isl_new once and never run_season / push_age_curve
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_refresh_script.py -v` → FAIL.
- [ ] **Step 3: Implement.** In `main()`, when the league is `ISL_LEAGUE`, log and call `push_isl_new()` inside the same `SoccerhubError` try/failure-list pattern, skip the FBref stages and `push_age_curve`, and return. Update the module docstring's schedule sentence to "Mon + Wed–Sat FBref, Tue ISL".
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: plist.** Add a sixth `StartCalendarInterval` dict, `Weekday 6, Hour 6, Minute 0`. Verify with `plutil -lint scripts/com.ikarthik.soccerhub-fbref.plist` → `OK`.
- [ ] **Step 6: Actions cron.** In `run-season.yml`, change `- cron: "0 6 * * 1,4"` to `- cron: "0 6 * * 1"` and the comment `# Mon + Thu 06:00 UTC` to `# Mon 06:00 UTC`.
- [ ] **Step 7: Side check** (spec "Side finding"). Run `gh run list --workflow run-season.yml --limit 10`, and report whether the `matches` job has been failing since about 2026-09-20. Report only; no fix in this plan.
- [ ] **Step 8: Stage** all four files. Message: `chore:schedule ISL on Tue, FBref Mon+Wed-Sat, Actions Mon only`.
- [ ] **Step 9: User reloads launchd** (local machine, not the repo):

```bash
launchctl unload ~/Library/LaunchAgents/com.ikarthik.soccerhub-fbref.plist
cp "Soccer Data Hub/scripts/com.ikarthik.soccerhub-fbref.plist" ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ikarthik.soccerhub-fbref.plist
```
(Check the installed plist path first with `launchctl list | grep soccerhub`.)

---

### Task 8: Team names + backfill run

**Files:**
- Modify: `src/soccerhub/pipelines/fotmob_isl.py` (`TEAM_NAMES`)

- [ ] **Step 1: Scan team names.** For each season `2021`–`2026`, `fetch_league(season)` and collect `(team id, name)` from fixtures. Any team id with more than one name gets one canonical name, the most recent season's. Put those ids in `TEAM_NAMES`, and leave it empty if there are none. Print the table for the user.
- [ ] **Step 2: Dry check the DB budget** (MCP SELECT): `select pg_size_pretty(pg_database_size(current_database()));`. Expected about 300 MB. Stop if it's over 440 MB.
- [ ] **Step 3: Backfill** (about 700 matches, about 25–30 min):

Run: `cd "Soccer Data Hub" && .venv/bin/python -m soccerhub.pipelines.fotmob_isl 2021 2022 2023 2024 2025 2026`
Expected: per-season counts printed and no exception.

- [ ] **Step 4: Verify the counts** (MCP SELECT):

```sql
select season, count(*) from matches where league='IND-Indian Super League' group by 1 order by 1;
select season, count(distinct match_id), count(*) from player_match where league='IND-Indian Super League' group by 1 order by 1;
select count(*) from shots_understat where league='IND-Indian Super League';
select pg_size_pretty(pg_database_size(current_database()));
```
Expected matches: 2021 115 · 2022 117 · 2023 139 · 2024 163 · 2025 91 · 2026 = finished so far. Shots about 18–22k. DB about 325 MB.

- [ ] **Step 5: Stage** `fotmob_isl.py` if `TEAM_NAMES` changed. Message: `feat:isl-backfill canonical team names`.
