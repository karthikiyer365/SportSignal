# Action Score (SPADL + VAEP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rate every on-ball action of Premier League 2015/16 with VAEP (out-of-fold), build a player table and two coach views, validate the ratings, and export 3 static JSON files for the site's Scouting Screens.

**Architecture:** A new reader turns StatsBomb open data into SPADL actions, cached per game through the existing `cached_fetch`. A new pipeline module splits games into 2 folds (odd/even by date), trains VAEP on one fold, rates the other, then aggregates, validates and exports. All `socceraction` imports stay lazy (inside functions), like `readers/statsbomb.py` does with kloppy.

**Tech Stack:** Python 3.11, pandas 2.3, socceraction 1.5.3, statsbombpy, xgboost, scikit-learn (comes with socceraction), pytest.

**Spec:** `docs/superpowers/specs/2026-10-01-action-score-design.md`

## Global Constraints

- All paths below are relative to `Soccer Data Hub/` unless they start with `site/` or `docs/` (repo root). Run every command from `Soccer Data Hub/` with `.venv/bin/python`.
- Branch `feat/action-score` only. **Never commit or push.** Each task ends with a checkpoint: show `git diff --stat`, stop, and wait for the user to say `do CP`. Commit message format: `feat:action-score <description>`.
- Every dataset goes through `cached_fetch(source, dataset, params, produce, force)` (`src/soccerhub/cache.py`). No second cache path.
- `socceraction`, `statsbombpy`, `xgboost` and `sklearn` are imported inside functions, never at module top. `import soccerhub` must stay fast.
- Data: `competition_id=2`, `season_id=27` (verified in Task 1).
- Split: 2 folds by game, alternating in `(game_date, game_id)` order. A game is never in both folds.
- `vaep_per90 = vaep_total / minutes * 90`; `minutes == 0` gives `NaN`, never `inf`.
- Ranking views: `minutes >= 900` (`MIN_MINUTES_RANK`, a guess). Reliability check: `>= 450` minutes per fold (`MIN_MINUTES_HALF`).
- Zones: 3 thirds by `start_x` (`own`/`middle`/`attacking`, cuts at 35 and 70) × 3 lanes by `start_y` (cuts at 68/3 and 2·68/3) = 9 zones, labelled `"<third>-<lane>"`.
- Site output: `site/data/action_score/{players,zones,top_actions}.json`, `orient="records"`, floats rounded to 4 decimals.
- Wording: the player table means "what he added on the ball this season", never "how good he is". The liabilities text prints with every run.

## Review Focus

1. **A player with 0 minutes (unused sub in the squad list)** should get `vaep_per90 = NaN`, not `inf` or a crash. The Task 3 end-to-end test pins this (player 103).
2. **Coordinates slightly outside 105×68** (StatsBomb occasionally reports 120.1 → 105.1 after conversion) should still get a zone, not `NaN`. `add_zone` clips; the Task 3 test asserts every action has a valid zone.
3. **A season where nobody reaches 450 minutes in each fold** (a short or partial season) should make the reliability check return `NaN` with `n = 0`, not raise. The Task 4 test pins this (4 games, nobody qualifies).
4. **A re-run after a dropped connection at game 200** should resume from game 200, not refetch 199 games. The Task 2 test pins this: a second run makes zero event calls.
5. **Memory on the real season.** About 700k actions × 568 features. `_states` downcasts features to float32 per game. If the real run still runs out of memory, the fallback is `VAEP(nb_prev_actions=1)`; record it in the spec's decision log. The real run in Task 5 watches for this; there is no test.

---

### Task 1: Dependencies, baseline and data ids

**Files:**
- Modify: `pyproject.toml:10-19`

**Interfaces:**
- Consumes: nothing
- Produces: an installed venv where `import xgboost, statsbombpy, socceraction.data, socceraction.vaep` works; verified ids `competition_id=2, season_id=27`.

- [ ] **Step 1: Add the dependencies**

In `pyproject.toml`, the `dependencies` list becomes:

```toml
dependencies = [
    "soccerdata>=1.8",
    "kloppy>=3.15",
    "mcp>=1.2",
    "pandas>=2.0",
    "pyarrow>=14",
    "supabase>=2",
    "google-genai>=1.9",
    "socceraction>=1.5",
    "multimethod<1.11",  # pandera 0.17 (via socceraction) breaks on multimethod 2.x
    "statsbombpy",
    "xgboost>=2",
]
```

- [ ] **Step 2: Install and check the imports**

Run:
```bash
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -c "import xgboost, statsbombpy, socceraction.data, socceraction.vaep; print('ok', xgboost.__version__)"
```
Expected: `ok 2.x.x`.
If it fails with `XGBoost Library (libxgboost.dylib) could not be loaded`: run `brew install libomp`, then repeat the import line.

- [ ] **Step 3: Run the full suite and record the baseline**

Run: `.venv/bin/python -m pytest -q`
Expected: everything passes except the 2 known failures `tests/test_api.py::test_ask_returns_answer` and `tests/test_api.py::test_ask_maps_agent_error_to_502` (`TypeError: ... got an unexpected keyword argument`). Those are in test stubs for the agent call and are out of scope. Any **other** failure is caused by the pandas 3 → 2.3 downgrade: stop and report it to the user before continuing.

- [ ] **Step 4: Verify the season ids**

Run:
```bash
.venv/bin/python -c "
from socceraction.data.statsbomb import StatsBombLoader
c = StatsBombLoader(getter='remote').competitions()
print(c[(c.competition_name == 'Premier League') & (c.season_name == '2015/2016')][['competition_id', 'season_id']])"
```
Expected: `competition_id 2`, `season_id 27`. If different, use the printed values everywhere this plan says `2, 27` and update the spec's Data section.

- [ ] **Step 5: Checkpoint**

Show `git diff --stat`. Stop. Wait for `do CP` (message: `feat:action-score add socceraction, statsbombpy, xgboost deps`).

---

### Task 2: StatsBomb → SPADL reader

**Files:**
- Create: `src/soccerhub/readers/statsbomb_spadl.py`
- Modify: `src/soccerhub/__init__.py` (import + `__all__`)
- Test: `tests/test_statsbomb_spadl.py`

**Interfaces:**
- Consumes: `cached_fetch` from `soccerhub.cache`; `Manifest` from `soccerhub.manifest`.
- Produces: `fetch_statsbomb_spadl(competition_id: int, season_id: int, force: bool = False) -> dict[str, Manifest]` with keys `"games"`, `"actions"`, `"players"`.
  - `games` parquet columns: `game_id, season_id, competition_id, game_day, game_date, home_team_id, away_team_id, competition_stage, home_score, away_score, venue, referee`
  - `actions` parquet: SPADL columns with names: `game_id, original_event_id, action_id, period_id, time_seconds, team_id, player_id, start_x, start_y, end_x, end_y, bodypart_id, bodypart_name, type_id, type_name, result_id, result_name`
  - `players` parquet: `game_id, team_id, player_id, player_name, is_starter, minutes_played, jersey_number, nickname, starting_position_id, starting_position_name, team_name`

- [ ] **Step 1: Write the failing test**

Create `tests/test_statsbomb_spadl.py`:

```python
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


class FakeLoader:
    def __init__(self):
        self.event_calls = 0

    def games(self, competition_id, season_id):
        assert (competition_id, season_id) == (2, 27)
        return pd.DataFrame({
            "game_id": [1, 2],
            "home_team_id": [10, 20],
            "away_team_id": [20, 10],
            "game_date": pd.to_datetime(["2015-08-08", "2015-08-15"]),
            "home_score": [1, 0],
            "away_score": [0, 2],
        })

    def events(self, game_id):
        self.event_calls += 1
        return pd.DataFrame({"game_id": [game_id, game_id]})

    def players(self, game_id):
        return pd.DataFrame({
            "game_id": [game_id] * 2,
            "team_id": [10, 20],
            "player_id": [100, 200],
            "player_name": ["Jamie Vardy", "Mesut Ozil"],
            "minutes_played": [90, 90],
        })

    def teams(self, game_id):
        return pd.DataFrame({"team_id": [10, 20], "team_name": ["Leicester City", "Arsenal"]})


def test_fetch_statsbomb_spadl_caches_each_game_and_stacks_season(monkeypatch):
    import soccerhub.readers.statsbomb_spadl as r

    fake = FakeLoader()
    monkeypatch.setattr(r, "_loader", lambda: fake)
    monkeypatch.setattr(r, "_to_spadl", lambda events, home_team_id: events.assign(home=home_team_id))

    m = r.fetch_statsbomb_spadl(2, 27)
    actions = pd.read_parquet(m["actions"].path)
    players = pd.read_parquet(m["players"].path)
    assert set(m) == {"games", "actions", "players"}
    assert len(actions) == 4
    assert sorted(actions.home.unique()) == [10, 20]
    assert set(players.team_name) == {"Leicester City", "Arsenal"}
    assert fake.event_calls == 2

    r.fetch_statsbomb_spadl(2, 27)  # second run: every game is a cache hit
    assert fake.event_calls == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_statsbomb_spadl.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'soccerhub.readers.statsbomb_spadl'`

- [ ] **Step 3: Write the reader**

Create `src/soccerhub/readers/statsbomb_spadl.py`:

```python
"""StatsBomb open data -> SPADL actions for one competition-season.

Each game is cached on its own, so a dropped connection at game 200 resumes
at game 200 instead of starting over.
"""
import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest

SOURCE = "statsbomb_spadl"


def _loader():
    from socceraction.data.statsbomb import StatsBombLoader  # lazy: heavy import

    return StatsBombLoader(getter="remote")


def _to_spadl(events: pd.DataFrame, home_team_id: int) -> pd.DataFrame:
    import socceraction.spadl as spadl
    from socceraction.spadl.statsbomb import convert_to_actions

    return spadl.add_names(convert_to_actions(events, home_team_id=home_team_id))


def _game_players(loader, game_id: int) -> pd.DataFrame:
    teams = loader.teams(game_id)[["team_id", "team_name"]]
    return loader.players(game_id).merge(teams, on="team_id", how="left")


def fetch_statsbomb_spadl(
    competition_id: int, season_id: int, force: bool = False
) -> dict[str, Manifest]:
    """Games, SPADL actions and player minutes for one StatsBomb competition-season."""
    params = {"competition_id": competition_id, "season_id": season_id}
    loader = None

    def get_loader():
        nonlocal loader
        loader = loader or _loader()  # only built on a cache miss
        return loader

    games_m = cached_fetch(
        SOURCE, "games", params, lambda: get_loader().games(competition_id, season_id), force
    )
    games = pd.read_parquet(games_m.path)

    paths = []
    for g in games.itertuples(index=False):
        gp = {"game_id": int(g.game_id)}
        a = cached_fetch(
            SOURCE, "game_actions", gp,
            lambda g=g: _to_spadl(get_loader().events(g.game_id), g.home_team_id), force,
        )
        p = cached_fetch(
            SOURCE, "game_players", gp, lambda g=g: _game_players(get_loader(), g.game_id), force
        )
        paths.append((a.path, p.path))

    def stack(i):
        return lambda: pd.concat([pd.read_parquet(pp[i]) for pp in paths], ignore_index=True)

    return {
        "games": games_m,
        "actions": cached_fetch(SOURCE, "actions", params, stack(0), force),
        "players": cached_fetch(SOURCE, "players", params, stack(1), force),
    }
```

- [ ] **Step 4: Export it from the package**

In `src/soccerhub/__init__.py`, after `from soccerhub.readers.statsbomb import fetch_statsbomb_events` add:

```python
from soccerhub.readers.statsbomb_spadl import fetch_statsbomb_spadl
```

and add `"fetch_statsbomb_spadl",` to `__all__` after `"fetch_statsbomb_events",`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_statsbomb_spadl.py tests/test_exports.py -v`
Expected: PASS

- [ ] **Step 6: Teach and inspect: one real game, raw events next to SPADL (network)**

Run:
```bash
.venv/bin/python -c "
import socceraction.spadl as spadl
from socceraction.data.statsbomb import StatsBombLoader
from socceraction.spadl.statsbomb import convert_to_actions
L = StatsBombLoader(getter='remote')
g = L.games(2, 27).iloc[0]
ev = L.events(g.game_id)
act = spadl.add_names(convert_to_actions(ev, home_team_id=g.home_team_id))
print(len(ev), 'events ->', len(act), 'SPADL actions')
print(ev[['type_name', 'player_name', 'location']].head(8).to_string())
print(act[['type_name', 'result_name', 'start_x', 'start_y', 'end_x', 'end_y']].head(8).to_string())
pl = L.players(g.game_id)
rb = pl[pl.starting_position_name == 'Right Back'].player_id
print('right-back mean start_y:', act[act.player_id.isin(rb)].start_y.mean())"
```
If a column is missing, print `ev.columns` and pick the equivalents.

Walk the user through: events outnumber SPADL actions (non-ball events dropped); StatsBomb's 120×80 becomes 105×68.
**Lane check:** if the right-back's mean `start_y` is below 34, low `y` is the right flank, which matches `LANES = ["right", "centre", "left"]` in Task 3. If it is above 34, reverse `LANES` in Task 3.

- [ ] **Step 7: Checkpoint**

Show `git diff --stat`. Stop. Wait for `do CP` (message: `feat:action-score StatsBomb to SPADL reader, cached per game`).

---

### Task 3: Out-of-fold VAEP rating, zones, player table

**Files:**
- Create: `src/soccerhub/pipelines/action_score.py`
- Test: `tests/test_action_score.py`

**Interfaces:**
- Consumes: the DataFrames from Task 2 (`games`, `actions`, `players` columns as listed there).
- Produces (all in `soccerhub.pipelines.action_score`):
  - `split_by_game(games: pd.DataFrame) -> pd.Series`: index `game_id`, values `0`/`1`, name `"fold"`
  - `rate_out_of_fold(games: pd.DataFrame, actions: pd.DataFrame, learner: str = "xgboost") -> pd.DataFrame`: `actions` sorted by `game_id, action_id`, plus `fold, label_scores, label_concedes, p_scores, p_concedes, offensive_value, defensive_value, vaep_value`
  - `add_zone(actions: pd.DataFrame) -> pd.DataFrame`: adds `start_zone` (str)
  - `player_table(rated: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame`: `player_id, team_id, player_name, team_name, minutes, n_actions, vaep_total, vaep_per90`
  - Constants: `PL_2015 = {"competition_id": 2, "season_id": 27}`, `MIN_MINUTES_RANK = 900`, `MIN_MINUTES_HALF = 450`, `TOP_N = 10`, `THIRDS`, `LANES`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_action_score.py`:

```python
import json

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def _game_actions(game_id, home, away, n=120):
    """Synthetic but valid SPADL game: possession flips every 6 actions,
    every possession ends in a shot, every 3rd shot is a goal (alternating teams)."""
    import socceraction.spadl as spadl
    import socceraction.spadl.config as cfg

    i = np.arange(n)
    team = np.where(i // 6 % 2 == 0, home, away)
    shot, pas = cfg.actiontypes.index("shot"), cfg.actiontypes.index("pass")
    ok, fail = cfg.results.index("success"), cfg.results.index("fail")
    rng = np.random.default_rng(game_id)
    return spadl.add_names(pd.DataFrame({
        "game_id": game_id,
        "original_event_id": [f"{game_id}-{k}" for k in i],  # non-null: VAEP features fillna on it
        "action_id": i,
        "period_id": np.where(i < n // 2, 1, 2),
        "time_seconds": (i % (n // 2)) * 20.0,
        "team_id": team,
        "player_id": team * 10 + i % 3,
        "start_x": rng.uniform(-1, 106, n),  # a few off-pitch coords on purpose
        "start_y": rng.uniform(-1, 69, n),
        "end_x": rng.uniform(0, 105, n),
        "end_y": rng.uniform(0, 68, n),
        "bodypart_id": cfg.bodyparts.index("foot"),
        "type_id": np.where(i % 6 == 5, shot, pas),
        "result_id": np.where(i % 18 == 5, ok, fail),
    }))


@pytest.fixture
def season():
    games = pd.DataFrame({
        "game_id": [1, 2, 3, 4],
        "home_team_id": [10, 20, 10, 20],
        "away_team_id": [20, 10, 20, 10],
        "game_date": pd.to_datetime(["2015-08-08", "2015-08-15", "2015-08-22", "2015-08-29"]),
        "home_score": [2, 1, 0, 1],
        "away_score": [1, 1, 0, 3],
    })
    actions = pd.concat(
        [_game_actions(g.game_id, g.home_team_id, g.away_team_id) for g in games.itertuples()],
        ignore_index=True,
    )
    rows = []
    for gid in games.game_id:
        for team, name in ((10, "Leicester City"), (20, "Arsenal")):
            for k in range(3):
                rows.append({"game_id": gid, "team_id": team, "team_name": name,
                             "player_id": team * 10 + k, "player_name": f"{name} {k}",
                             "minutes_played": 90})
        rows.append({"game_id": gid, "team_id": 10, "team_name": "Leicester City",
                     "player_id": 103, "player_name": "Unused Sub", "minutes_played": 0})
    return games, actions, pd.DataFrame(rows)


def test_split_by_game_alternates_by_date_and_never_overlaps():
    from soccerhub.pipelines.action_score import split_by_game

    games = pd.DataFrame({
        "game_id": [7, 3, 9, 1],
        "game_date": pd.to_datetime(["2015-09-01", "2015-08-01", "2015-10-01", "2015-08-01"]),
    })
    assert split_by_game(games).to_dict() == {1: 0, 3: 1, 7: 0, 9: 1}


def test_rating_zones_and_player_table(season):
    from soccerhub.pipelines import action_score as a

    games, actions, players = season
    rated = a.add_zone(a.rate_out_of_fold(games, actions))

    assert len(rated) == len(actions)
    assert rated.groupby("game_id").fold.nunique().eq(1).all()
    assert rated[["offensive_value", "defensive_value", "vaep_value"]].notna().all().all()
    assert rated.p_scores.between(0, 1).all()
    zones = {f"{t}-{l}" for t in a.THIRDS for l in a.LANES}
    assert rated.start_zone.isin(zones).all()

    table = a.player_table(rated, players).set_index("player_id")
    assert table.loc[100, "minutes"] == 360
    assert table.loc[100, "vaep_per90"] == pytest.approx(table.loc[100, "vaep_total"] / 360 * 90)
    assert np.isnan(table.loc[103, "vaep_per90"])  # 0 minutes -> no rate, never inf
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_action_score.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'soccerhub.pipelines.action_score'`

- [ ] **Step 3: Write the module**

Create `src/soccerhub/pipelines/action_score.py`:

```python
"""Action Score: VAEP value for every on-ball action, rated out-of-fold.

Question: every time a player touched the ball, did his team become more or
less likely to score (or concede) in the next 10 actions, and by how much?
Spec: docs/superpowers/specs/2026-10-01-action-score-design.md
"""
import numpy as np
import pandas as pd

PL_2015 = {"competition_id": 2, "season_id": 27}  # verified in plan Task 1
MIN_MINUTES_RANK = 900  # guess, not derived: revisit after the reliability check
MIN_MINUTES_HALF = 450  # reliability check: minutes needed in each fold
TOP_N = 10
THIRDS = ["own", "middle", "attacking"]
LANES = ["right", "centre", "left"]  # attacking left->right, low y = right flank (checked in Task 2)


def split_by_game(games: pd.DataFrame) -> pd.Series:
    """Fold 0/1 per game_id: alternate games in date order."""
    order = games.sort_values(["game_date", "game_id"]).game_id.to_numpy()
    return pd.Series(np.arange(len(order)) % 2, index=order, name="fold")


def _states(vaep, games: pd.DataFrame, actions: pd.DataFrame):
    """Features + labels for every action. VAEP works one game at a time."""
    by_id = games.set_index("game_id", drop=False)
    X, y = [], []
    for gid, ga in actions.groupby("game_id", sort=True):
        game = by_id.loc[gid]
        Xg = vaep.compute_features(game, ga)
        X.append(Xg.astype({c: "float32" for c in Xg.select_dtypes("float64").columns}))
        y.append(vaep.compute_labels(game, ga))
    return pd.concat(X, ignore_index=True), pd.concat(y, ignore_index=True)


def rate_out_of_fold(games: pd.DataFrame, actions: pd.DataFrame, learner: str = "xgboost") -> pd.DataFrame:
    """Each game is rated by the model trained on the other fold, so no game grades itself."""
    from socceraction.vaep import VAEP, formula

    actions = actions.sort_values(["game_id", "action_id"]).reset_index(drop=True)
    X, y = _states(VAEP(), games, actions)
    fold = actions.game_id.map(split_by_game(games)).to_numpy()
    out = actions.assign(
        fold=fold,
        label_scores=y.scores.to_numpy(),
        label_concedes=y.concedes.to_numpy(),
        p_scores=np.nan,
        p_concedes=np.nan,
    )
    for k in (0, 1):
        model = VAEP().fit(X[fold != k], y[fold != k], learner=learner)
        # ponytail: private call, socceraction has no public predict_proba
        probs = model._estimate_probabilities(X[fold == k])
        out.loc[fold == k, "p_scores"] = probs.scores.to_numpy()
        out.loc[fold == k, "p_concedes"] = probs.concedes.to_numpy()
    # formula.value compares each action with the one before it, so it must run per game
    values = [
        formula.value(ga.reset_index(drop=True), ga.p_scores.reset_index(drop=True),
                      ga.p_concedes.reset_index(drop=True))
        for _, ga in out.groupby("game_id", sort=True)
    ]
    return pd.concat([out, pd.concat(values, ignore_index=True)], axis=1)


def add_zone(actions: pd.DataFrame) -> pd.DataFrame:
    """9 pitch zones: third (by start_x) x lane (by start_y), e.g. 'attacking-left'."""
    third = pd.cut(actions.start_x.clip(0, 105), [0, 35, 70, 105], labels=THIRDS, include_lowest=True)
    lane = pd.cut(actions.start_y.clip(0, 68), [0, 68 / 3, 2 * 68 / 3, 68], labels=LANES, include_lowest=True)
    return actions.assign(start_zone=third.astype(str) + "-" + lane.astype(str))


def player_table(rated: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    """One row per player per team: what he added on the ball, total and per 90."""
    minutes = players.groupby(["player_id", "team_id"], as_index=False).agg(
        player_name=("player_name", "first"),
        team_name=("team_name", "first"),
        minutes=("minutes_played", "sum"),
    )
    value = rated.groupby(["player_id", "team_id"], as_index=False).agg(
        n_actions=("vaep_value", "size"), vaep_total=("vaep_value", "sum")
    )
    t = minutes.merge(value, on=["player_id", "team_id"], how="left").fillna(
        {"n_actions": 0, "vaep_total": 0.0}
    )
    t["vaep_per90"] = t.vaep_total / t.minutes.where(t.minutes > 0) * 90
    return t.sort_values("vaep_total", ascending=False, ignore_index=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_action_score.py -v`
Expected: PASS (2 tests). `FutureWarning: DataFrameGroupBy.apply operated on the grouping columns` comes from inside socceraction and is expected.

- [ ] **Step 5: Teach: read one game's features and labels**

Run:
```bash
.venv/bin/python -c "
import pandas as pd, sys
sys.path.insert(0, 'tests')
from test_action_score import _game_actions
from socceraction.vaep import VAEP
a = _game_actions(1, 10, 20)
g = pd.Series({'game_id': 1, 'home_team_id': 10, 'away_team_id': 20})
X, y = VAEP().compute_features(g, a), VAEP().compute_labels(g, a)
print(X.shape)
print(X.filter(like='a0').columns[:15].tolist())
print(pd.concat([a[['team_id', 'type_name', 'result_name']], y], axis=1).iloc[:12].to_string())"
```
Walk the user through: `a0` is the current action, `a1`/`a2` are the 2 before it (that's `nb_prev_actions=3`). Labels are `True` when a goal for (scores) or against (concedes) comes within the next 10 actions, so actions just before a goal light up.

- [ ] **Step 6: Checkpoint**

Show `git diff --stat`. Stop. Wait for `do CP` (message: `feat:action-score out-of-fold VAEP rating, zones, player table`).

---

### Task 4: Validation, coach views, site export

**Files:**
- Modify: `src/soccerhub/pipelines/action_score.py` (append)
- Test: `tests/test_action_score.py` (append)

**Interfaces:**
- Consumes: `split_by_game`, `rate_out_of_fold`, `add_zone`, `player_table`, `TOP_N`, `MIN_MINUTES_HALF` from Task 3.
- Produces:
  - `validate(rated: pd.DataFrame, games: pd.DataFrame, players: pd.DataFrame) -> dict` with keys `auc_scores, brier_scores, auc_concedes, calibration_max_gap, team_spearman, team_table, reliability_spearman, reliability_n`
  - `top_actions(rated: pd.DataFrame, n: int = TOP_N) -> pd.DataFrame`: `game_id, team_id, player_id, period_id, time_seconds, minute, type_name, result_name, start_x, start_y, end_x, end_y, vaep_value, kind` (`kind` is `"best"` or `"worst"`)
  - `zone_summary(rated: pd.DataFrame) -> pd.DataFrame`: `team_id, start_zone, vaep_total, n_actions`
  - `export_action_score_site(games, players, rated, table, out_dir=SITE_DIR) -> dict[str, int]`: bytes written per file name
  - `SITE_DIR`: `<repo>/site/data/action_score`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_action_score.py`:

```python
def test_validation_and_site_export(season, tmp_path):
    from soccerhub.pipelines import action_score as a

    games, actions, players = season
    rated = a.add_zone(a.rate_out_of_fold(games, actions))
    table = a.player_table(rated, players)

    report = a.validate(rated, games, players)
    assert {"auc_scores", "brier_scores", "auc_concedes", "calibration_max_gap",
            "team_spearman", "team_table", "reliability_spearman", "reliability_n"} <= report.keys()
    assert 0 <= report["auc_scores"] <= 1
    assert report["reliability_n"] == 0  # 2 games per fold = 180 min, nobody reaches 450
    assert np.isnan(report["reliability_spearman"])

    sizes = a.export_action_score_site(games, players, rated, table, tmp_path)
    assert set(sizes) == {"players", "zones", "top_actions"}

    top = pd.DataFrame(json.loads((tmp_path / "top_actions.json").read_text()))
    assert top.groupby(["game_id", "team_id", "kind"]).size().max() <= a.TOP_N
    assert {"player_name", "team_name", "opponent_name", "minute", "game_date"} <= set(top.columns)
    assert (top.loc[top.team_name == "Leicester City", "opponent_name"] == "Arsenal").all()
    assert top.game_date.str.match(r"\d{4}-\d{2}-\d{2}$").all()

    zones = json.loads((tmp_path / "zones.json").read_text())
    assert len(zones) <= 2 * 9
    first = json.loads((tmp_path / "players.json").read_text())[0]
    assert {"player_name", "team_name", "minutes", "vaep_per90"} <= first.keys()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_action_score.py::test_validation_and_site_export -v`
Expected: FAIL with `AttributeError: module 'soccerhub.pipelines.action_score' has no attribute 'validate'`

- [ ] **Step 3: Write validation, coach views and export**

At the top of `src/soccerhub/pipelines/action_score.py`, add `from pathlib import Path` above `import numpy as np`, and add this constant after `LANES`:

```python
SITE_DIR = Path(__file__).resolve().parents[4] / "site" / "data" / "action_score"
```

Append to the end of the file:

```python
def _points(games: pd.DataFrame) -> pd.Series:
    h, a = games.home_score, games.away_score
    home = pd.Series(np.select([h > a, h == a], [3, 1], 0), index=games.home_team_id)
    away = pd.Series(np.select([a > h, h == a], [3, 1], 0), index=games.away_team_id)
    return pd.concat([home, away]).groupby(level=0).sum().rename("points")


def _reliability(rated: pd.DataFrame, players: pd.DataFrame, games: pd.DataFrame):
    """Spearman of per-90 value, fold 0 vs fold 1, for players with enough minutes in both."""
    fold = split_by_game(games)
    mins = players.assign(fold=players.game_id.map(fold)).groupby(["player_id", "fold"]).minutes_played.sum()
    vaep = rated.groupby(["player_id", "fold"]).vaep_value.sum().reindex(mins.index, fill_value=0.0)
    per90 = (vaep / mins * 90)[mins >= MIN_MINUTES_HALF].unstack("fold").reindex(columns=[0, 1]).dropna()
    if len(per90) < 3:
        return float("nan"), len(per90)
    return per90[0].corr(per90[1], method="spearman"), len(per90)


def validate(rated: pd.DataFrame, games: pd.DataFrame, players: pd.DataFrame) -> dict:
    """Calibration, team sanity, reliability. Says whether the ratings mean anything."""
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import brier_score_loss, roc_auc_score

    ys, yc = rated.label_scores.astype(int), rated.label_concedes.astype(int)
    prob_true, prob_pred = calibration_curve(ys, rated.p_scores, n_bins=10, strategy="quantile")
    team = pd.concat([rated.groupby("team_id").vaep_value.sum(), _points(games)], axis=1, join="inner")
    rel, n = _reliability(rated, players, games)
    return {
        "auc_scores": roc_auc_score(ys, rated.p_scores),
        "brier_scores": brier_score_loss(ys, rated.p_scores),
        "auc_concedes": roc_auc_score(yc, rated.p_concedes),
        "calibration_max_gap": float(np.abs(prob_true - prob_pred).max()),
        "team_spearman": team.vaep_value.corr(team.points, method="spearman"),
        "team_table": team.sort_values("vaep_value", ascending=False),
        "reliability_spearman": rel,
        "reliability_n": n,
    }


def top_actions(rated: pd.DataFrame, n: int = TOP_N) -> pd.DataFrame:
    """Per team per match: the n most valuable and n most costly actions."""
    cols = ["game_id", "team_id", "player_id", "period_id", "time_seconds", "type_name",
            "result_name", "start_x", "start_y", "end_x", "end_y", "vaep_value"]
    # ponytail: real team-matches have ~800 actions; under 2n, best and worst would overlap
    g = rated.sort_values("vaep_value")[cols].groupby(["game_id", "team_id"])
    out = pd.concat([g.tail(n).assign(kind="best"), g.head(n).assign(kind="worst")], ignore_index=True)
    out["minute"] = (out.time_seconds // 60 + 45 * (out.period_id - 1)).astype(int)
    return out


def zone_summary(rated: pd.DataFrame) -> pd.DataFrame:
    """Where on the pitch each team gains or loses value."""
    return rated.groupby(["team_id", "start_zone"], as_index=False).agg(
        vaep_total=("vaep_value", "sum"), n_actions=("vaep_value", "size")
    )


def export_action_score_site(games, players, rated, table, out_dir=SITE_DIR) -> dict[str, int]:
    """Write players/zones/top_actions JSON for the site's Scouting Screens. Returns bytes per file."""
    teams = players.drop_duplicates("team_id").set_index("team_id").team_name
    names = players.drop_duplicates("player_id").set_index("player_id").player_name
    top = top_actions(rated).merge(
        games[["game_id", "game_date", "home_team_id", "away_team_id"]], on="game_id"
    )
    opponent = top.away_team_id.where(top.team_id == top.home_team_id, top.home_team_id)
    top = top.assign(
        player_name=top.player_id.map(names),
        team_name=top.team_id.map(teams),
        opponent_name=opponent.map(teams),
        game_date=pd.to_datetime(top.game_date).dt.strftime("%Y-%m-%d"),
    ).drop(columns=["home_team_id", "away_team_id", "time_seconds"])
    zones = zone_summary(rated).assign(team_name=lambda d: d.team_id.map(teams))

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for name, df in {"players": table, "zones": zones, "top_actions": top}.items():
        path = out_dir / f"{name}.json"
        df.round(4).to_json(path, orient="records")
        sizes[name] = path.stat().st_size
    return sizes
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_action_score.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Checkpoint**

Show `git diff --stat`. Stop. Wait for `do CP` (message: `feat:action-score validation, coach views, site JSON export`).

---

### Task 5: Orchestration, real run, readout

**Files:**
- Modify: `src/soccerhub/pipelines/action_score.py` (append)
- Modify: `src/soccerhub/__init__.py` (import + `__all__`)
- Create (by running): `site/data/action_score/players.json`, `zones.json`, `top_actions.json`

**Interfaces:**
- Consumes: `fetch_statsbomb_spadl` (Task 2), everything in Task 3 and Task 4.
- Produces:
  - `build_action_score(competition_id: int = 2, season_id: int = 27, force: bool = False) -> dict[str, Manifest]`, keys `games, players, actions_vaep, player_table`
  - `main()`, run with `.venv/bin/python -m soccerhub.pipelines.action_score`

- [ ] **Step 1: Write the orchestration**

Add to the imports at the top of `src/soccerhub/pipelines/action_score.py`:

```python
from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest
from soccerhub.readers.statsbomb_spadl import fetch_statsbomb_spadl
```

Append to the end of the file:

```python
LIABILITIES = """\
Liabilities (read before quoting any number):
- Model dependence: one StatsBomb season, one learner (xgboost), 2-fold out-of-fold.
- Blind spots: undervalues defending; off-ball runs are invisible.
- Team style inflates players: Leicester's counter-attacking shapes their numbers.
- Meaning: "what he added on the ball this season", not "how good he is"."""


def build_action_score(competition_id: int = 2, season_id: int = 27, force: bool = False) -> dict[str, Manifest]:
    src = fetch_statsbomb_spadl(competition_id, season_id, force)
    params = {"competition_id": competition_id, "season_id": season_id}
    games = pd.read_parquet(src["games"].path)
    actions_m = cached_fetch(
        "action_score", "actions_vaep", params,
        lambda: add_zone(rate_out_of_fold(games, pd.read_parquet(src["actions"].path))), force,
    )
    table_m = cached_fetch(
        "action_score", "player_table", params,
        lambda: player_table(pd.read_parquet(actions_m.path), pd.read_parquet(src["players"].path)),
        force,
    )
    return {"games": src["games"], "players": src["players"],
            "actions_vaep": actions_m, "player_table": table_m}


def main():
    m = build_action_score(**PL_2015)
    games, players = pd.read_parquet(m["games"].path), pd.read_parquet(m["players"].path)
    rated, table = pd.read_parquet(m["actions_vaep"].path), pd.read_parquet(m["player_table"].path)

    report = validate(rated, games, players)
    for k, v in report.items():
        if k != "team_table":
            print(f"{k:22} {v:.3f}" if isinstance(v, float) else f"{k:22} {v}")
    teams = players.drop_duplicates("team_id").set_index("team_id").team_name
    print(report["team_table"].rename(index=teams).to_string())

    ranked = table[table.minutes >= MIN_MINUTES_RANK].sort_values("vaep_per90", ascending=False)
    print(ranked.head(20).to_string(index=False))
    print(LIABILITIES)
    print("site export bytes:", export_action_score_site(games, players, rated, table))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Export from the package**

In `src/soccerhub/__init__.py`, after the `from soccerhub.pipelines import (...)` block add:

```python
from soccerhub.pipelines.action_score import build_action_score, export_action_score_site
```

and add `"build_action_score",` and `"export_action_score_site",` to `__all__`.

- [ ] **Step 3: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass except the 2 known `tests/test_api.py` failures from Task 1.

- [ ] **Step 4: Real run (network, about 20–40 min the first time)**

Run: `.venv/bin/python -m soccerhub.pipelines.action_score`
If it stops partway (network), re-run the same command: finished games are cache hits.
If it runs out of memory, change `VAEP()` to `VAEP(nb_prev_actions=1)` in both places in `rate_out_of_fold`, re-run with `python -m soccerhub.pipelines.action_score --force` (re-rates only, no re-download), and add a row to the spec's decision log.

- [ ] **Step 5: Teach and read the validation with the user**

From the printed report, go through each check with the user. Each line reads like this:

| Line | Reads as |
|---|---|
| `auc_scores` | 0.5 = coin flip. Published VAEP models sit around 0.75–0.8 for scoring |
| `brier_scores` | Lower is better; compare against the base rate of `label_scores` |
| `calibration_max_gap` | Largest gap between predicted and observed goal rate across 10 bins |
| `team_spearman` + team table | Should be clearly positive. Is Leicester near the top? If Aston Villa (last) is high, treat it as a bug |
| `reliability_spearman`, `reliability_n` | Near 0 = player ranking is noise. Note `n` |

Then read the top 20 players and the most valuable action of one match. Ask the user whether the names make football sense. Write the 5 numbers and the verdict ("ranking trustworthy / not") into the spec under a new `## v1 results` heading.

- [ ] **Step 6: Check the site files**

Run: `ls -la ../site/data/action_score/`
Expected: 3 files. If `top_actions.json` is over 2 MB, tell the user: per the spec, the next step is splitting it per team (`top_actions/<team_id>.json`). Don't split it in this plan.

- [ ] **Step 7: Checkpoint**

Show `git diff --stat`. Stop. Wait for `do CP` (message: `feat:action-score orchestration, PL 2015/16 run, site JSON`).
