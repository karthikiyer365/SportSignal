# Big-5 Per-Match Player Stats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill `player_match` with FotMob per-match stats for the Big 5 (2021/22 → now), link each FotMob player to his Big-5 `player_season` row via `fotmob_id`, and refresh weekly on each league's launchd day.

**Architecture:** Generalise the ISL FotMob reader and pipeline by league. One code path: ISL writes all five tables, Big-5 writes `player_match` only. A link step reuses the Understat name+minutes matcher to set `player_season.fotmob_id`.

**Tech Stack:** Python 3.11, pandas, existing `supa.upsert_df` / `query.read_hub`, pytest. No new deps, no migration.

**Spec:** `docs/superpowers/specs/2026-10-23-big5-player-match-design.md`

Paths are relative to `Soccer Data Hub/`.

## Global Constraints

- FotMob ids: `IND-Indian Super League` 9478 · `ENG-Premier League` 47 · `ESP-La Liga` 87 · `GER-Bundesliga` 54 · `ITA-Serie A` 55 · `FRA-Ligue 1` 53.
- Archive slugs: `isl`, `eng`, `esp`, `ger`, `ita`, `fra` → bucket `fotmob`, path `<slug>/<season>/<match_id>.json.gz`. ISL path unchanged.
- Big-5 writes **only** `player_match` and `player_season.fotmob_id`. Never `matches`, `shots_understat`, `team_match_understat`, or other `player_season` columns.
- Seasons `2021`–`2026` (start-year text).
- Join FotMob ↔ hub by `fotmob_id`, never by name.
- Budget: stop the backfill if `pg_database_size` > 470 MB. Expected end ≈ 405 MB.
- No migration. No new dependencies.
- Commits: stage only; commit/push only on user's `do CP` / `do CPR`. Branch `feat/isl-fetch`. Format `feat:big5-<scope> …`. Trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Supabase MCP is SELECT-only.

## Review Focus

1. **ISL regression.** Generalising must leave ISL output identical: same tables, same archive path `isl/…`, `push_isl` / `push_isl_new` still work for launchd. Pinned: all existing ISL tests stay green + Task 1 archive-path test + Task 2 alias test.
2. **Big-5 touching shared tables.** A Big-5 push that writes `shots_understat` or `player_season` stat rows duplicates data. Pinned in Task 2.
3. **Wrong link.** Two FotMob players who could both match one hub row (same normalised name, minutes within guard) must leave it unlinked, not guess. Pinned in Task 3.
4. **FBref failure skips FotMob.** On a Big-5 day, an FBref IP block must not stop the FotMob push + link. Pinned in Task 4.
5. **FotMob network error kills the rest of the day.** A non-`SoccerhubError` (HTTPError) in the FotMob step must be logged as a failure and not stop `age_curve`. Pinned in Task 4.

---

### Task 1: Reader takes a league

**Files:**
- Modify: `src/soccerhub/readers/fotmob.py`
- Test: `tests/test_fotmob.py`

**Interfaces:**
- Produces:
  - `FOTMOB_IDS: dict[str, int]`, `SLUGS: dict[str, str]` (league → id / slug, values in Global Constraints). Remove `ISL_ID`.
  - `fetch_league(league: str, season: str | None = None, force: bool = False) -> dict`; cache name `league_<slug>_<season or 'current'>`.
  - `fetch_match(match_id: int, season: str, league: str, force: bool = False, archive: bool = True) -> dict`; cache name stays `match_<id>` (ids are global).
  - `_archive(match_id: int, season: str, gz: bytes, slug: str) -> None` → `<slug>/<season>/<match_id>.json.gz`.

- [ ] **Step 1: Write failing tests**

```python
def test_fetch_league_uses_league_id(monkeypatch):
    import soccerhub.readers.fotmob as fm
    urls = []
    monkeypatch.setattr(fm, "_get_json", lambda u: urls.append(u) or {})
    fm.fetch_league("ENG-Premier League", "2024")
    assert "id=47" in urls[0] and "season=2024%2F2025" in urls[0]

def test_archive_path_uses_league_slug(monkeypatch):
    import soccerhub.readers.fotmob as fm
    paths = []
    monkeypatch.setattr(fm, "_get_json", lambda u: {"general": {}})
    monkeypatch.setattr(fm, "_archive", lambda mid, season, gz, slug: paths.append(f"{slug}/{season}/{mid}"))
    fm.fetch_match(1, "2024", "ENG-Premier League"); fm.fetch_match(2, "2024", "IND-Indian Super League")
    assert paths == ["eng/2024/1", "isl/2024/2"]
```
Update `test_fetch_match_uses_cache` to the new signature.

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_fotmob.py -q` → FAIL.
- [ ] **Step 3: Implement.** Update every caller in `pipelines/fotmob_isl.py` to the new signatures (Task 2 builds on this).
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_fotmob.py tests/test_fotmob_isl.py -q` → PASS.
- [ ] **Step 5: Stage.** Message: `feat:big5-reader fotmob reader takes a league`.

---

### Task 2: One push path for ISL and Big-5

**Files:**
- Modify: `src/soccerhub/pipelines/fotmob_isl.py`, `src/soccerhub/pipelines/__init__.py`, `src/soccerhub/__init__.py`
- Test: `tests/test_fotmob_isl.py`

**Interfaces:**
- Consumes: Task 1 signatures.
- Produces:
  - `parse_match(raw: dict, season: str, league: str = ISL_LEAGUE) -> dict[str, pd.DataFrame]` — every frame carries the given `league`.
  - `push_fotmob(league: str, season: str, force: bool = False, match_ids: list[int] | None = None) -> dict[str, int]` — ISL: today's `push_isl` body. Big-5: upsert `player_match` only.
  - `push_fotmob_new(league: str) -> dict[str, int]` — today's `push_isl_new` body, by league. Big-5 does not rebuild `player_season`.
  - `push_isl(season, force=False, match_ids=None)` and `push_isl_new()` stay as one-line wrappers.
  - CLI: `python -m soccerhub.pipelines.fotmob_isl <slug> <season>…` (e.g. `eng 2021 2022`). Big-5 seasons also run `link_fotmob` (Task 3).
  - Exports: `push_fotmob`, `push_fotmob_new` in both `__init__` files.

- [ ] **Step 1: Write failing tests** (reuse the `wired` fixture; it patches `fm.fetch_league` / `fm.fetch_match`, so update its lambdas to the Task 1 signatures)

```python
def test_big5_push_writes_only_player_match(wired):
    from soccerhub.pipelines.fotmob_isl import push_fotmob
    out = push_fotmob("ENG-Premier League", "2024", match_ids=[4617934])
    assert [t for t, _ in wired["upserts"]] == ["player_match"]
    assert out == {"player_match": 31}

def test_parse_match_carries_league(raw):
    from soccerhub.pipelines.fotmob_isl import parse_match
    p = parse_match(raw, "2024", "ESP-La Liga")
    assert {f.league.iat[0] for f in p.values()} == {"ESP-La Liga"}

def test_isl_aliases_still_write_all_tables(wired):
    from soccerhub.pipelines.fotmob_isl import push_isl
    push_isl("2024", match_ids=[4617934])
    assert {t for t, _ in wired["upserts"]} == {"matches", "team_match_understat", "shots_understat", "player_match", "player_season"}
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `.venv/bin/pytest -q` → all pass except the 2 pre-existing `test_api` failures.
- [ ] **Step 5: Stage.** Message: `feat:big5-push one fotmob path, ISL full / Big-5 player_match only`.

---

### Task 3: Matcher takes columns + `link_fotmob`

**Files:**
- Modify: `src/soccerhub/pipelines/understat.py` (`match_players`), `src/soccerhub/pipelines/fotmob_isl.py`
- Test: `tests/test_fotmob_isl.py`, `tests/test_understat.py` (one new tie test; existing tests unchanged and green)

**Interfaces:**
- Produces:
  - `match_players(us: pd.DataFrame, hub: pd.DataFrame, cols: dict[str, str] = XG_COLS) -> pd.DataFrame` — every `XG_COLS` use inside becomes `cols`. No other change.
  - `link_fotmob(league: str, season: str) -> tuple[int, int]` → `(linked, hub_rows)`.

`link_fotmob`: `read_hub("player_match", select="fotmob_id,team,player_name,minutes", league, season)` → sum minutes per `(fotmob_id, team)`, keep `player_name` → rename to `player`. Hub: `read_hub("player_season", select="league,season,team,player_name,minutes", league, season)`. `match_players(us, hub, cols={"fotmob_id": "fotmob_id"})` → upsert result (key cols + `fotmob_id` only) with `CONFLICT_KEY_PLAYER_SEASON`. Returns `(len(matched), len(hub))`.

- [ ] **Step 1: Write failing tests** (monkeypatch `query.read_hub` by table, `supa.upsert_df` to capture)

```python
def test_link_fotmob_sets_ids_and_only_that_column(monkeypatch):
    # player_match: "Vinicius Junior" fotmob_id 9 (2 rows: 90+80 min, team "Real Madrid")
    #               mover "Joao Felix" fotmob_id 5: 900 min "Chelsea", 1200 min "Barcelona"
    # hub: "Vinícius Júnior" 170 min; "João Félix" Chelsea 880 min; "João Félix" Barcelona 1250 min
    linked, total = link_fotmob("ESP-La Liga", "2024")
    df = upserted["player_season"]
    assert set(df.columns) == {"league", "season", "team", "player_name", "fotmob_id"}
    assert (linked, total) == (3, 3)
    assert set(df.fotmob_id) == {9, 5}

def test_link_fotmob_leaves_equal_distance_tie_unlinked(monkeypatch):
    # two FotMob "Gabriel" (ids 1, 2): 1000 and 1100 min; hub one "Gabriel" 1050 min
    linked, _ = link_fotmob("ENG-Premier League", "2024")
    assert linked == 0  # both are 50 min away: unknowable, so no guess
```
This needs one change in `match_players` rung 2: when the two closest candidates are equally far in minutes, skip that hub row (today `min()` silently takes the first). It applies to the Understat caller too, which is intended (same anti-goal). Add `test_match_players_rung2_rejects_minutes_tie` to `tests/test_understat.py`, and keep every existing Understat test green.

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `.venv/bin/pytest tests/test_understat.py tests/test_fotmob_isl.py -q` → PASS.
- [ ] **Step 5: Stage.** Message: `feat:big5-link fotmob_id onto player_season via understat matcher`.

---

### Task 4: Big-5 days run FotMob + link

**Files:**
- Modify: `scripts/refresh_fbref_chain.py`
- Test: `tests/test_refresh_script.py`

**Interfaces:**
- Consumes: `push_fotmob_new(league)`, `link_fotmob(league, season)`.

In the `for league in todays` loop, after the FBref stages and **also when `run_season` failed** (replace that `continue` so the FotMob steps still run), run `push_fotmob_new(league)` then `link_fotmob(league, season)`. Each is in a `try/except Exception` that logs `FAILED fotmob/<league>: …` or `FAILED link/<league>: …` and appends to `failures`. Use a `# ponytail:` comment saying broad except on purpose, FotMob raises plain HTTP/KeyErrors. `age_curve` still runs after the loop.

- [ ] **Step 1: Write failing tests**

```python
def test_big5_day_runs_fotmob_even_when_fbref_blocked(mod, monkeypatch):
    # LEAGUE=ENG-Premier League; run_season raises SoccerhubError
    assert calls == ["fbref", "fotmob", "link", "age"] and mod.main() == 1

def test_fotmob_http_error_is_logged_not_fatal(mod, monkeypatch):
    # push_fotmob_new raises urllib.error.HTTPError
    assert "age" in calls and mod.main() == 1
```
(Patching follows `test_isl_day_runs_isl_not_fbref`. The ISL test stays green.)

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `.venv/bin/pytest tests/test_refresh_script.py -q` → PASS, and `.venv/bin/python scripts/refresh_fbref_chain.py --dry-run` → `OK env + imports fine`.
- [ ] **Step 5: Stage.** Message: `feat:big5-schedule fotmob push + link on each Big-5 day`.

---

### Task 5: Backfill + link + verify

No code. Run locally, one league at a time; each league is ≈1–1.2 h and resumable.

- [ ] **Step 1: Budget check** (MCP): `select pg_size_pretty(pg_database_size(current_database()));` → expect ≈312 MB.
- [ ] **Step 2: Per league, in order eng, esp, ger, ita, fra:**

Run: `cd "Soccer Data Hub" && set -a && . ./.env && set +a && .venv/bin/python -u -W ignore -m soccerhub.pipelines.fotmob_isl eng 2021 2022 2023 2024 2025 2026`
Expected: one line per season with `player_match` rows (≈11–12k for full seasons) and a `link` `(linked, hub_rows)` tuple. Re-check the budget after each league and **stop if over 470 MB**.

- [ ] **Step 3: Verify** (MCP):

```sql
select league, season, count(distinct match_id) matches, count(*) rows
from player_match where league <> 'IND-Indian Super League' group by 1,2 order by 1,2;
select league, season, count(*) filter (where fotmob_id is not null)::float / count(*) link_rate,
       sum(minutes) filter (where fotmob_id is not null)::float / sum(minutes) minutes_link_rate
from player_season where league <> 'IND-Indian Super League' and season >= '2021' group by 1,2 order by 1,2;
select pg_size_pretty(pg_database_size(current_database()));
```
Expected: full seasons 380 / 306 matches; `minutes_link_rate` ≥ 0.90 (report any league-season below that); DB ≈ 405 MB; 0 Big-5 rows added to `shots_understat` (`select count(*) … where updated_at > <backfill start>` and league Big-5 → only Understat's own refresh).

- [ ] **Step 4: Stage** nothing unless a fix was needed. Report the counts table to the user for the PR.
