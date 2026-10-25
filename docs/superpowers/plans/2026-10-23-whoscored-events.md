# WhoScored Events → VAEP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add WhoScored (Opta) as the third provider of `action_score` for Big-5 2025/26 and the current 2026/27 season, link WhoScored players to `player_season.whoscored_id`, and refresh the current season weekly.

**Architecture:** A `whoscored_spadl` reader on the existing `spadl_season.fetch_spadl_season` loop, fed by soccerdata's `OptaLoader`. `action_score.LEAGUE_SEASONS` gains 10 WhoScored league-seasons. The link reuses the FotMob link code. The launchd Big-5 day adds one WhoScored step.

**Tech Stack:** Python 3.11, soccerdata 1.9 (`WhoScored`, seleniumbase Chrome), socceraction (`OptaLoader`, `spadl.opta`), existing VAEP code, pytest.

**Spec:** `docs/superpowers/specs/2026-10-23-whoscored-events-design.md`

Paths are relative to `Soccer Data Hub/` unless they start with `site/` or `docs/`.

## Global Constraints

- Seasons: hub `"2025"` (soccerdata code `"2526"`) and `"2026"` (`"2627"`), all five Big-5 leagues.
- Loader ids are soccerdata's strings: `L.games("ENG-Premier League", "2526")`. The feed pattern is `events/{competition_id}_{season_id}/{game_id}.json` under `~/soccerdata/data/WhoScored` (verified 2026-10-23).
- `soccerdata.WhoScored(leagues=…, seasons=…, headless=False)`. A real Chrome window; runs on the user's Mac only.
- soccerdata bug: Chrome wraps JSON in `<html><head></head><body>…</body></html>`. The patch must be a no-op on clean JSON.
- No raw events in Postgres. One migration only: `0013_whoscored_id.sql` → `player_season.whoscored_id bigint`. User applies it.
- Existing 9 league-seasons, their folders and `team.html` behaviour unchanged.
- Storage stop line: do not upload if Storage > 950 MB (check with MCP before each league's upload).
- No commits/pushes until `do CP` / `do CPR`. Branch `feat/isl-fetch`. Format `feat:whoscored-<scope> …`. Trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Supabase MCP SELECT-only.

## Review Focus

0. **Weekly refresh dirties git / never reaches the live site.** Pinned: WhoScored folders git-ignored, small JSON uploaded to Storage, `team.html` reads them from Storage (Task 3).
1. **Existing providers regress.** StatsBomb/Wyscout league-seasons must rate and export exactly as before. Pinned: existing `tests/test_action_score.py` stays green + Task 3 dispatch test.
2. **Weekly refresh re-downloads the whole season.** `refetch=True` re-downloads every game (20–40 min, or hours for WhoScored). The weekly path must fetch the game list fresh but reuse cached games. Pinned in Task 2.
3. **Patch corrupts good responses.** If soccerdata or Chrome stops wrapping, the patch must leave JSON untouched. Pinned in Task 1.
4. **Wrong WhoScored link.** Same anti-goal as FotMob. Pinned by reusing the tested matcher (Task 4) + a WhoScored-shaped test.
5. **WhoScored block kills the Big-5 day.** A Cloudflare failure must be logged and must not stop FotMob, the link or age_curve. Pinned in Task 5.

---

### Task 1: Patch + `whoscored_spadl` reader

**Files:**
- Create: `src/soccerhub/readers/whoscored_spadl.py`
- Create: `tests/fixtures/whoscored/events/ENG-Premier League_2425/1821049.json`. Copy `~/soccerdata/data/WhoScored/events/ENG-Premier League_2425/1821049.json`, trimmed to the first 300 events of its event list (keep every other key) so the file stays small.
- Test: `tests/test_whoscored_spadl.py`

**Interfaces:**
- Produces:
  - `strip_html_wrapper(text: str) -> str`: removes a leading `<html><head></head><body>` and a trailing `</body></html>`; returns clean JSON unchanged.
  - `_patch_whoscored_json() -> None`: makes `soccerdata.whoscored.json.load` use `strip_html_wrapper` (idempotent).
  - `fetch_whoscored_spadl(league: str, season_code: str, force: bool = False, refresh: bool = False) -> dict[str, Manifest]`: on `fetch_spadl_season(SOURCE="whoscored_spadl", {"league", "season"}, …)`. `make_loader` patches and then returns `WhoScored(...).read_events(output_fmt="loader")`. `games_of = L.games(league, season_code)`. `actions_of` uses `socceraction.spadl.opta.convert_to_actions(L.events(g.game_id), g.home_team_id)`. `players_of = spadl_season.game_players`.

- [ ] **Step 1: Write failing tests**

```python
def test_strip_html_wrapper_unwraps_and_leaves_clean_json_alone():
    from soccerhub.readers.whoscored_spadl import strip_html_wrapper
    assert strip_html_wrapper('<html><head></head><body>{"a": 1}</body></html>') == '{"a": 1}'
    assert strip_html_wrapper('{"a": "<body>"}') == '{"a": "<body>"}'

def test_fixture_match_converts_to_spadl():
    # OptaLoader(root=tests/fixtures/whoscored, parser="whoscored",
    #            feeds={"whoscored": "events/{competition_id}_{season_id}/{game_id}.json"})
    g = L.games("ENG-Premier League", "2425")
    assert list(g.game_id) == [1821049]
    teams = set(L.teams(1821049).team_name)
    assert teams == {"Man Utd", "Fulham"}
    a = _to_spadl(L.events(1821049), int(g.home_team_id.iat[0]))
    assert len(a) > 0 and {"start_x", "end_x", "type_id", "player_id"} <= set(a.columns)
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_whoscored_spadl.py -q` → FAIL.
- [ ] **Step 3: Implement.** Docstring: provider is Opta via WhoScored, scraped through a browser (ToS), one model per league-season, never compared with StatsBomb/Wyscout.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Stage.** Message: `feat:whoscored-reader opta events to SPADL via soccerdata loader`.

---

### Task 2: `refresh` in the season loop

**Files:**
- Modify: `src/soccerhub/readers/spadl_season.py`
- Test: `tests/test_whoscored_spadl.py`

**Interfaces:**
- Produces: `fetch_spadl_season(source, params, make_loader, games_of, actions_of, players_of, force=False, refresh=False)`. `refresh=True` re-reads the game list and re-stacks `actions`/`players`. Each per-game `game_actions`/`game_players` stays cached and is only built for new games. `force` keeps today's meaning: everything is rebuilt.

- [ ] **Step 1: Write failing test**

```python
def test_refresh_lists_new_games_without_refetching_old_ones(tmp_path, monkeypatch):
    # games_of returns [1] first call, [1, 2] second call; actions_of counts calls per game
    fetch_spadl_season(..., refresh=False)          # builds game 1
    fetch_spadl_season(..., refresh=True)           # game list now [1, 2]
    assert built == [1, 2]                          # game 1 not rebuilt
    assert stacked_rows == 2                        # season actions include both
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** this file plus `tests/test_action_score.py` → PASS.
- [ ] **Step 5: Stage.** Message: `feat:whoscored-refresh new games only on refresh`.

---

### Task 3: `action_score` third provider + weekly refresh + `team.html`

**Files:**
- Modify: `src/soccerhub/pipelines/action_score.py`, `site/team.html`
- Test: `tests/test_action_score.py`

**Interfaces:**
- Consumes: `fetch_whoscored_spadl(league, season_code, force, refresh)`.
- Produces:
  - `LEAGUE_SEASONS` += 10 entries: `(league, "2025"): ("whoscored", league, "2526")` and `(league, "2026"): ("whoscored", league, "2627")` for the five leagues.
  - `build_action_score(competition_id, season_id, force=False, refetch=False, provider="statsbomb", refresh=False)` dispatches `"whoscored"` → `fetch_whoscored_spadl(competition_id, season_id, refetch, refresh)`. When `refresh`, `actions_vaep` is rebuilt (`force=True` on that cached_fetch).
  - `refresh_current(league: str) -> dict`: the latest WhoScored season for that league → `build_action_score(..., refresh=True)` → `export_action_score_site` → `upload_player_actions`. Returns `{"games": n, "upload": files}`.
  - `LIABILITIES` adds WhoScored to its provider line.
  - `upload_player_actions(league_dir)` also uploads `players.json`, `zones.json` and `games.json` for WhoScored folders, because they change every week. Storage is their only home.
  - `.gitignore`: ignore `site/data/action_score/*-2025/` and `*-2026/` entirely. Weekly rewrites must not dirty git, and the live site reads them from Storage.
- `site/team.html`: for `provider === "whoscored"`, read `players/zones/games.json` from the Storage base the page already uses for `player_actions` (`…/storage/v1/object/public/action-score/`). Other providers keep reading `data/action_score/`. Append 10 `LEAGUES` rows `["eng-premier-league-2025", "Premier League", "2025/26", "whoscored"]` … and a `PROVIDERS.whoscored` entry `{label: "WhoScored (Opta) · current", source: "WhoScored match centre (Opta event data)"}`, with a note that VAEP is low confidence before 190 matches.

- [ ] **Step 1: Write failing tests**

```python
def test_whoscored_league_seasons_dispatch_to_whoscored_reader(monkeypatch):
    # patch fetch_whoscored_spadl to record args and return tiny manifests
    build_action_score("ENG-Premier League", "2526", provider="whoscored")
    assert called == [("ENG-Premier League", "2526")]

def test_league_seasons_has_ten_whoscored_entries():
    ws = {k: v for k, v in LEAGUE_SEASONS.items() if v[0] == "whoscored"}
    assert len(ws) == 10 and ws[("GER-Bundesliga", "2026")] == ("whoscored", "GER-Bundesliga", "2627")
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `.venv/bin/pytest tests/test_action_score.py -q` → PASS, and `grep -c whoscored site/team.html` → 11 or more.
- [ ] **Step 5: Stage.** Message: `feat:whoscored-action-score third provider, current-season refresh, team page folders`.

---

### Task 4: `whoscored_id` link + migration 0013

**Files:**
- Create: `supabase/migrations/0013_whoscored_id.sql`
- Modify: `src/soccerhub/pipelines/fotmob_isl.py` (extract the shared link body), `src/soccerhub/pipelines/action_score.py`
- Test: `tests/test_fotmob_isl.py` (existing link tests stay green), `tests/test_action_score.py`

**Interfaces:**
- Produces:
  - `link_ids(us: pd.DataFrame, league: str, season: str, cols: dict[str, str]) -> tuple[int, int]` in `fotmob_isl.py`. `us` has `player`, `minutes` and the id column. It reads hub rows, runs `match_players`, upserts only the key columns plus the id column, and returns `(linked, hub_rows)`. `link_fotmob` becomes "build `us` from `player_match`" plus `link_ids(…, {"fotmob_id": "fotmob_id"})`.
  - `link_whoscored(league: str, season: str) -> tuple[int, int]` in `action_score.py`. It takes the season's `players` manifest (`fetch_whoscored_spadl`, cached) and sums `minutes_played` per `(player_id, team_name)` into `us`, then calls `link_ids(us, league, season, {"player_id": "whoscored_id"})`.
- Migration: `alter table player_season add column if not exists whoscored_id bigint;` with a header comment in the 0012 style.

- [ ] **Step 1: Write failing test**

```python
def test_link_whoscored_sets_whoscored_id_only(monkeypatch):
    # players manifest: player_id 77 "Bruno Fernandes" Man Utd 2 games x 90; hub "Bruno Fernandes" Manchester Utd 180
    linked, total = link_whoscored("ENG-Premier League", "2025")
    assert (linked, total) == (1, 1)
    assert set(upserted.columns) == {"league", "season", "team", "player_name", "whoscored_id"}
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `.venv/bin/pytest tests/test_fotmob_isl.py tests/test_action_score.py tests/test_understat.py -q` → PASS.
- [ ] **Step 5: Stage.** Message: `feat:whoscored-link whoscored_id on player_season (migration 0013)`.

---

### Task 5: Big-5 day runs WhoScored

**Files:**
- Modify: `scripts/refresh_fbref_chain.py`, `src/soccerhub/__init__.py` (export `refresh_current`, `link_whoscored`)
- Test: `tests/test_refresh_script.py`

After the FotMob try-block on a Big-5 day: a separate `try/except Exception` runs `refresh_current(league)` then `link_whoscored(league, season)`. A failure is logged as `FAILED whoscored <league>` and appended to `failures`. `age_curve` still runs. The order is FBref → FotMob → WhoScored, so the two browser-gated sources are as far apart as one day allows.

- [ ] **Step 1: Write failing tests** (extend `_big5_day` with `refresh_current` / `link_whoscored` fakes)

```python
def test_big5_day_runs_whoscored_after_fotmob(mod, monkeypatch):
    assert calls == ["fbref", "understat", "understat", "understat", "fotmob", "link", "whoscored", "ws_link", "age"]

def test_whoscored_block_is_logged_not_fatal(mod, monkeypatch):
    # refresh_current raises RuntimeError("Cloudflare")
    assert "age" in calls and "ws_link" not in calls and rc == 1
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `.venv/bin/pytest -q` → all pass except the 2 pre-existing `test_api` failures; `--dry-run` OK.
- [ ] **Step 5: Stage.** Message: `feat:whoscored-schedule weekly current-season refresh on Big-5 days`.

---

### Task 6: Apply 0013, backfill, upload, link, verify

No code.

- [ ] **Step 1:** The user applies `0013_whoscored_id.sql`. Verify with MCP: `select column_name from information_schema.columns where table_name='player_season' and column_name='whoscored_id';` → 1 row.
- [ ] **Step 2: Storage check** (MCP) → expect ≈ 677 MB.
- [ ] **Step 3: Backfill, one league at a time, both seasons** (≈ 1.4 h per league; a Chrome window stays open):

Run: `cd "Soccer Data Hub" && set -a && . ./.env && set +a && .venv/bin/python -u -W ignore -m soccerhub.pipelines.action_score --upload "ENG-Premier League" 2025 2026`
Expected: validation printout per season (games 380 for 2025 and the current count for 2026), `site export bytes` with `player_actions` ≈ 20–25 MB, `uploaded player files` > 0. Before each next league, Storage must be < 950 MB.

- [ ] **Step 4: Link:** `link_whoscored(league, s)` for each league × `2025`, `2026` → print `(linked, hub_rows)`. La Liga 2026 is expected to show `(0, 0)` until FBref has rows.
- [ ] **Step 5: Verify** (MCP):

```sql
select league, season, count(*) filter (where whoscored_id is not null)::float / count(*) row_rate,
       sum(minutes) filter (where whoscored_id is not null)::float / sum(minutes) minutes_rate
from player_season where season in ('2025','2026') and league <> 'IND-Indian Super League' group by 1,2 order by 1,2;
select bucket_id, pg_size_pretty(sum((metadata->>'size')::bigint)) from storage.objects group by 1;
```
Expected: `minutes_rate` ≥ 0.90 per league-season (except La Liga 2026); Storage ≈ 790 MB plus the current season so far.
- [ ] **Step 6: Browser check (user):** `team.html` shows the 10 new league-seasons, and a 2025/26 player's action map loads from Storage.
- [ ] **Step 7:** Confirm `git status` shows no files under the new `site/data/action_score/*-2025|2026/` folders (all git-ignored and in Storage). Report counts for the PR.
