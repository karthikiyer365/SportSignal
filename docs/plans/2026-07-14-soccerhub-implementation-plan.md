# Data Hub (`soccerhub`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an installable Python package that fetches open-source soccer data, caches it to disk as parquet, and returns a manifest — plus a thin MCP wrapper exposing the same functions as tools.

**Architecture:** One core package (`soccerhub`) with a shared cache/manifest layer and three per-source reader functions (FBref, StatsBomb, Transfermarkt), each following an identical `fetch → cache → manifest` contract via a shared `cached_fetch` helper. An MCP server (`mcp_server.py`) is a ~40-line adapter that calls the readers and returns manifest dicts.

**Tech Stack:** Python ≥3.10, `soccerdata` (FBref), `kloppy` (StatsBomb events), `pandas`/`pyarrow` (Transfermarkt + parquet), `mcp` (FastMCP), `pytest`.

## Global Constraints

- Python `requires-python = ">=3.10"`.
- Dependencies limited to: `soccerdata`, `kloppy`, `mcp`, `pandas`, `pyarrow` (+ `pytest` as dev extra). No others without cause.
- Package lives at `data-hub/` (folder name has a space); all commands `cd data-hub` first. Package uses **src-layout** (`src/soccerhub/`).
- Cache directory resolved from env var `SOCCERHUB_CACHE`, default `./data`.
- Readers are plain functions — **no base class, no ABC, no unified `fetch()` dispatcher, no entity resolution** (explicit YAGNI).
- Every reader returns a `Manifest`; the MCP tools return `dataclasses.asdict(manifest)`.
- Cache writes are atomic (temp file → rename); a manifest is written only after a successful parquet write.
- Commit style: `feat(soccerhub): …` / `test(soccerhub): …` / `chore(soccerhub): …`.
- All tests mock the network/library call — the suite must run offline.

---

### Task 1: Project scaffold (installable, empty package)

**Files:**
- Create: `data-hub/pyproject.toml`
- Create: `data-hub/src/soccerhub/__init__.py`
- Create: `data-hub/tests/__init__.py`
- Test: `data-hub/tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an importable `soccerhub` package; `pytest` configured.

- [ ] **Step 1: Write the failing test**

`data-hub/tests/test_smoke.py`:
```python
def test_package_imports():
    import soccerhub
    assert soccerhub.__name__ == "soccerhub"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data-hub && python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soccerhub'` (package not installed yet).

- [ ] **Step 3: Write pyproject + package init**

`data-hub/pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "soccerhub"
version = "0.1.0"
description = "Unified fetch layer for open-source soccer data"
requires-python = ">=3.10"
dependencies = [
    "soccerdata>=1.8",
    "kloppy>=3.15",
    "mcp>=1.2",
    "pandas>=2.0",
    "pyarrow>=14",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.setuptools.packages.find]
where = ["src"]
```

`data-hub/src/soccerhub/__init__.py`:
```python
"""soccerhub — unified fetch layer for open-source soccer data."""
```

`data-hub/tests/__init__.py`: (empty file)

- [ ] **Step 4: Install and run the test**

Run: `cd data-hub && pip install -e ".[dev]" && python -m pytest tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd data-hub
git add pyproject.toml src/soccerhub/__init__.py tests/__init__.py tests/test_smoke.py
git commit -m "chore(soccerhub): scaffold installable package"
```

---

### Task 2: Errors + Manifest

**Files:**
- Create: `data-hub/src/soccerhub/errors.py`
- Create: `data-hub/src/soccerhub/manifest.py`
- Test: `data-hub/tests/test_manifest.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class SoccerhubError(Exception)`
  - `@dataclass Manifest(path: str, source: str, dataset: str, params: dict, rows: int, cols: int, date_range: tuple[str, str] | None, fetched_at: str)` with `.to_json() -> str` and `Manifest.from_json(s: str) -> Manifest`.
  - `infer_date_range(df: pandas.DataFrame) -> tuple[str, str] | None`.

- [ ] **Step 1: Write the failing test**

`data-hub/tests/test_manifest.py`:
```python
import pandas as pd
from soccerhub.manifest import Manifest, infer_date_range


def test_manifest_roundtrip():
    m = Manifest(
        path="data/fbref/abc.parquet",
        source="fbref",
        dataset="player_season",
        params={"league": "ENG-Premier League", "season": "2023"},
        rows=500,
        cols=30,
        date_range=None,
        fetched_at="2026-07-14T00:00:00+00:00",
    )
    restored = Manifest.from_json(m.to_json())
    assert restored == m


def test_infer_date_range_uses_year_column():
    df = pd.DataFrame({"year": [2019, 2021, 2020], "x": [1, 2, 3]})
    assert infer_date_range(df) == ("2019", "2021")


def test_infer_date_range_none_when_no_date_column():
    df = pd.DataFrame({"x": [1, 2, 3]})
    assert infer_date_range(df) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data-hub && python -m pytest tests/test_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soccerhub.manifest'`.

- [ ] **Step 3: Write the implementation**

`data-hub/src/soccerhub/errors.py`:
```python
class SoccerhubError(Exception):
    """Raised when a data fetch fails."""
```

`data-hub/src/soccerhub/manifest.py`:
```python
import json
from dataclasses import asdict, dataclass


DATE_COLS = ("date", "datetime", "timestamp", "year")


@dataclass
class Manifest:
    path: str
    source: str
    dataset: str
    params: dict
    rows: int
    cols: int
    date_range: tuple | None
    fetched_at: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "Manifest":
        d = json.loads(s)
        if d.get("date_range") is not None:
            d["date_range"] = tuple(d["date_range"])
        return cls(**d)


def infer_date_range(df) -> tuple | None:
    for col in DATE_COLS:
        if col in df.columns and len(df):
            series = df[col].dropna()
            if len(series):
                return (str(series.min()), str(series.max()))
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd data-hub && python -m pytest tests/test_manifest.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd data-hub
git add src/soccerhub/errors.py src/soccerhub/manifest.py tests/test_manifest.py
git commit -m "feat(soccerhub): add Manifest, SoccerhubError, date-range inference"
```

---

### Task 3: Cache core + `cached_fetch`

**Files:**
- Create: `data-hub/src/soccerhub/cache.py`
- Test: `data-hub/tests/test_cache.py`

**Interfaces:**
- Consumes: `Manifest`, `infer_date_range` (Task 2); `SoccerhubError` (Task 2).
- Produces:
  - `cache_root() -> pathlib.Path`
  - `cache_key(source: str, dataset: str, params: dict) -> str`
  - `parquet_path(source: str, key: str) -> pathlib.Path`
  - `manifest_path(source: str, key: str) -> pathlib.Path`
  - `cache_hit(source: str, key: str) -> bool`
  - `write_parquet(path: pathlib.Path, df) -> None` (atomic)
  - `read_manifest(source: str, key: str) -> Manifest`
  - `cached_fetch(source: str, dataset: str, params: dict, produce: Callable[[], pandas.DataFrame], force: bool = False) -> Manifest`

- [ ] **Step 1: Write the failing test**

`data-hub/tests/test_cache.py`:
```python
import pandas as pd
import pytest

from soccerhub.cache import cache_key, cached_fetch, cache_hit
from soccerhub.errors import SoccerhubError


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_cache_key_is_stable_and_order_independent():
    a = cache_key("fbref", "player_season", {"league": "ENG", "season": "2023"})
    b = cache_key("fbref", "player_season", {"season": "2023", "league": "ENG"})
    assert a == b
    assert a != cache_key("fbref", "player_season", {"league": "ESP", "season": "2023"})


def test_cached_fetch_writes_then_hits_cache():
    calls = {"n": 0}

    def produce():
        calls["n"] += 1
        return pd.DataFrame({"year": [2020, 2021], "x": [1, 2]})

    params = {"league": "ENG", "season": "2023"}
    m1 = cached_fetch("fbref", "player_season", params, produce)
    assert calls["n"] == 1
    assert m1.rows == 2 and m1.cols == 2
    assert m1.date_range == ("2020", "2021")
    assert cache_hit("fbref", cache_key("fbref", "player_season", params))

    # second call is a cache hit — produce must NOT run again
    m2 = cached_fetch("fbref", "player_season", params, produce)
    assert calls["n"] == 1
    assert m2 == m1

    # force bypasses the cache
    cached_fetch("fbref", "player_season", params, produce, force=True)
    assert calls["n"] == 2


def test_cached_fetch_wraps_errors_and_writes_no_manifest():
    def produce():
        raise ValueError("boom")

    params = {"league": "ENG", "season": "2023"}
    with pytest.raises(SoccerhubError):
        cached_fetch("fbref", "player_season", params, produce)
    assert not cache_hit("fbref", cache_key("fbref", "player_season", params))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data-hub && python -m pytest tests/test_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soccerhub.cache'`.

- [ ] **Step 3: Write the implementation**

`data-hub/src/soccerhub/cache.py`:
```python
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from soccerhub.errors import SoccerhubError
from soccerhub.manifest import Manifest, infer_date_range


def cache_root() -> Path:
    return Path(os.environ.get("SOCCERHUB_CACHE", "./data")).resolve()


def cache_key(source: str, dataset: str, params: dict) -> str:
    payload = json.dumps(
        {"source": source, "dataset": dataset, "params": params}, sort_keys=True
    )
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def parquet_path(source: str, key: str) -> Path:
    return cache_root() / source / f"{key}.parquet"


def manifest_path(source: str, key: str) -> Path:
    return cache_root() / source / f"{key}.json"


def cache_hit(source: str, key: str) -> bool:
    return parquet_path(source, key).exists() and manifest_path(source, key).exists()


def write_parquet(path: Path, df) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp)
    tmp.replace(path)


def read_manifest(source: str, key: str) -> Manifest:
    return Manifest.from_json(manifest_path(source, key).read_text())


def cached_fetch(
    source: str,
    dataset: str,
    params: dict,
    produce: Callable[[], "object"],
    force: bool = False,
) -> Manifest:
    key = cache_key(source, dataset, params)
    if not force and cache_hit(source, key):
        return read_manifest(source, key)

    try:
        df = produce()
    except Exception as exc:  # noqa: BLE001 — wrap any library/network failure
        raise SoccerhubError(f"{source}.{dataset} fetch failed: {exc}") from exc

    ppath = parquet_path(source, key)
    write_parquet(ppath, df)

    manifest = Manifest(
        path=str(ppath),
        source=source,
        dataset=dataset,
        params=params,
        rows=len(df),
        cols=len(df.columns),
        date_range=infer_date_range(df),
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    manifest_path(source, key).write_text(manifest.to_json())
    return manifest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd data-hub && python -m pytest tests/test_cache.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd data-hub
git add src/soccerhub/cache.py tests/test_cache.py
git commit -m "feat(soccerhub): add cache core and cached_fetch contract"
```

---

### Task 4: FBref reader

**Files:**
- Create: `data-hub/src/soccerhub/readers/__init__.py`
- Create: `data-hub/src/soccerhub/readers/fbref.py`
- Test: `data-hub/tests/test_fbref.py`

**Interfaces:**
- Consumes: `cached_fetch` (Task 3).
- Produces: `fetch_fbref_season(league: str, season: str, force: bool = False) -> Manifest`.

- [ ] **Step 1: Write the failing test**

`data-hub/tests/test_fbref.py`:
```python
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_fetch_fbref_season_caches_reader_output(monkeypatch):
    import soccerhub.readers.fbref as fbref

    class FakeFBref:
        def __init__(self, leagues, seasons):
            self.leagues = leagues
            self.seasons = seasons

        def read_player_season_stats(self):
            return pd.DataFrame({"player": ["A", "B"], "goals": [3, 1]})

    monkeypatch.setattr(fbref.sd, "FBref", FakeFBref)

    m = fbref.fetch_fbref_season("ENG-Premier League", "2023")
    assert m.source == "fbref"
    assert m.dataset == "player_season"
    assert m.rows == 2
    assert m.params == {"league": "ENG-Premier League", "season": "2023"}
    assert pd.read_parquet(m.path).shape == (2, 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data-hub && python -m pytest tests/test_fbref.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soccerhub.readers'`.

- [ ] **Step 3: Write the implementation**

`data-hub/src/soccerhub/readers/__init__.py`: (empty file)

`data-hub/src/soccerhub/readers/fbref.py`:
```python
import soccerdata as sd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest


def fetch_fbref_season(league: str, season: str, force: bool = False) -> Manifest:
    """Player season stats for one league-season from FBref."""

    def produce():
        return sd.FBref(leagues=league, seasons=season).read_player_season_stats()

    return cached_fetch(
        "fbref", "player_season", {"league": league, "season": season}, produce, force
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd data-hub && python -m pytest tests/test_fbref.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd data-hub
git add src/soccerhub/readers/__init__.py src/soccerhub/readers/fbref.py tests/test_fbref.py
git commit -m "feat(soccerhub): add FBref season reader"
```

---

### Task 5: StatsBomb events reader

**Files:**
- Create: `data-hub/src/soccerhub/readers/statsbomb.py`
- Test: `data-hub/tests/test_statsbomb.py`

**Interfaces:**
- Consumes: `cached_fetch` (Task 3).
- Produces: `fetch_statsbomb_events(match_id: str, force: bool = False) -> Manifest`.

- [ ] **Step 1: Write the failing test**

`data-hub/tests/test_statsbomb.py`:
```python
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_fetch_statsbomb_events_converts_dataset_to_df(monkeypatch):
    import soccerhub.readers.statsbomb as sb

    class FakeDataset:
        def to_df(self):
            return pd.DataFrame({"event_type": ["pass", "shot"], "minute": [1, 2]})

    def fake_load_open_data(match_id):
        assert match_id == "3788741"
        return FakeDataset()

    monkeypatch.setattr(sb.statsbomb, "load_open_data", fake_load_open_data)

    m = sb.fetch_statsbomb_events("3788741")
    assert m.source == "statsbomb"
    assert m.dataset == "events"
    assert m.rows == 2
    assert m.params == {"match_id": "3788741"}
    assert pd.read_parquet(m.path).shape == (2, 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data-hub && python -m pytest tests/test_statsbomb.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soccerhub.readers.statsbomb'`.

- [ ] **Step 3: Write the implementation**

`data-hub/src/soccerhub/readers/statsbomb.py`:
```python
from kloppy import statsbomb

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest


def fetch_statsbomb_events(match_id: str, force: bool = False) -> Manifest:
    """Event stream for one StatsBomb open-data match, flattened to a DataFrame."""

    def produce():
        return statsbomb.load_open_data(match_id=match_id).to_df()

    return cached_fetch(
        "statsbomb", "events", {"match_id": match_id}, produce, force
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd data-hub && python -m pytest tests/test_statsbomb.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd data-hub
git add src/soccerhub/readers/statsbomb.py tests/test_statsbomb.py
git commit -m "feat(soccerhub): add StatsBomb events reader"
```

---

### Task 6: Transfermarkt values reader

**Files:**
- Create: `data-hub/src/soccerhub/readers/transfermarkt.py`
- Test: `data-hub/tests/test_transfermarkt.py`

**Interfaces:**
- Consumes: `cached_fetch` (Task 3).
- Produces: `fetch_transfermarkt_values(competition: str, force: bool = False) -> Manifest`; module constant `TM_VALUATIONS_URL: str`.

> Note: `TM_VALUATIONS_URL` points at the pre-scraped `dcaribou/transfermarkt-datasets` `player_valuations.csv`. It is a **calibration knob** — if the upstream path moves, update this constant. The filter column is `player_club_domestic_competition_id`.

- [ ] **Step 1: Write the failing test**

`data-hub/tests/test_transfermarkt.py`:
```python
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_fetch_transfermarkt_values_filters_by_competition(monkeypatch):
    import soccerhub.readers.transfermarkt as tm

    fake = pd.DataFrame(
        {
            "player_id": [1, 2, 3],
            "market_value_in_eur": [100, 200, 300],
            "player_club_domestic_competition_id": ["GB1", "ES1", "GB1"],
        }
    )
    monkeypatch.setattr(tm.pd, "read_csv", lambda url: fake)

    m = tm.fetch_transfermarkt_values("GB1")
    assert m.source == "transfermarkt"
    assert m.dataset == "valuations"
    assert m.rows == 2  # only GB1 rows
    assert m.params == {"competition": "GB1"}
    assert set(pd.read_parquet(m.path)["player_id"]) == {1, 3}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data-hub && python -m pytest tests/test_transfermarkt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soccerhub.readers.transfermarkt'`.

- [ ] **Step 3: Write the implementation**

`data-hub/src/soccerhub/readers/transfermarkt.py`:
```python
import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest

# Pre-scraped Transfermarkt valuations (dcaribou/transfermarkt-datasets).
# Calibration knob: update if the upstream path moves.
TM_VALUATIONS_URL = (
    "https://raw.githubusercontent.com/dcaribou/transfermarkt-datasets/"
    "master/data/prep/player_valuations.csv"
)


def fetch_transfermarkt_values(competition: str, force: bool = False) -> Manifest:
    """Player market valuations filtered to one domestic competition."""

    def produce():
        df = pd.read_csv(TM_VALUATIONS_URL)
        return df[df["player_club_domestic_competition_id"] == competition]

    return cached_fetch(
        "transfermarkt", "valuations", {"competition": competition}, produce, force
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd data-hub && python -m pytest tests/test_transfermarkt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd data-hub
git add src/soccerhub/readers/transfermarkt.py tests/test_transfermarkt.py
git commit -m "feat(soccerhub): add Transfermarkt valuations reader"
```

---

### Task 7: MCP server (Layer 2)

**Files:**
- Create: `data-hub/src/soccerhub/mcp_server.py`
- Test: `data-hub/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `fetch_fbref_season`, `fetch_statsbomb_events`, `fetch_transfermarkt_values` (Tasks 4–6).
- Produces: module-level `mcp` (FastMCP) and three tool functions `fbref_season`, `statsbomb_events`, `transfermarkt_values`, each returning `dict`.

- [ ] **Step 1: Write the failing test**

`data-hub/tests/test_mcp_server.py`:
```python
from dataclasses import asdict

from soccerhub.manifest import Manifest


def _fake_manifest(source):
    return Manifest(
        path=f"data/{source}/x.parquet",
        source=source,
        dataset="events",
        params={},
        rows=1,
        cols=1,
        date_range=None,
        fetched_at="2026-07-14T00:00:00+00:00",
    )


def test_fbref_tool_returns_manifest_dict(monkeypatch):
    import soccerhub.mcp_server as server

    monkeypatch.setattr(
        server, "fetch_fbref_season", lambda league, season: _fake_manifest("fbref")
    )
    result = server.fbref_season("ENG-Premier League", "2023")
    assert result == asdict(_fake_manifest("fbref"))
    assert result["source"] == "fbref"


def test_server_registers_three_tools():
    import soccerhub.mcp_server as server

    for name in ("fbref_season", "statsbomb_events", "transfermarkt_values"):
        assert callable(getattr(server, name))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data-hub && python -m pytest tests/test_mcp_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soccerhub.mcp_server'`.

- [ ] **Step 3: Write the implementation**

`data-hub/src/soccerhub/mcp_server.py`:
```python
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from soccerhub.readers.fbref import fetch_fbref_season
from soccerhub.readers.statsbomb import fetch_statsbomb_events
from soccerhub.readers.transfermarkt import fetch_transfermarkt_values

mcp = FastMCP("soccerhub")


@mcp.tool()
def fbref_season(league: str, season: str) -> dict:
    """Fetch + cache FBref player season stats; returns a manifest."""
    return asdict(fetch_fbref_season(league, season))


@mcp.tool()
def statsbomb_events(match_id: str) -> dict:
    """Fetch + cache StatsBomb open-data match events; returns a manifest."""
    return asdict(fetch_statsbomb_events(match_id))


@mcp.tool()
def transfermarkt_values(competition: str) -> dict:
    """Fetch + cache Transfermarkt valuations for a competition; returns a manifest."""
    return asdict(fetch_transfermarkt_values(competition))


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd data-hub && python -m pytest tests/test_mcp_server.py -v`
Expected: PASS (2 tests).

> If `@mcp.tool()` does not return the wrapped function (so `server.fbref_season` is not directly callable), adjust the test to call `fbref_season.fn(...)` per the installed FastMCP API. Verify against the installed `mcp` package before assuming.

- [ ] **Step 5: Commit**

```bash
cd data-hub
git add src/soccerhub/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(soccerhub): add MCP server exposing the three readers"
```

---

### Task 8: Package exports + README + full-suite check

**Files:**
- Modify: `data-hub/src/soccerhub/__init__.py`
- Create: `data-hub/README.md`
- Test: `data-hub/tests/test_exports.py`

**Interfaces:**
- Consumes: all reader functions, `Manifest`, `SoccerhubError`.
- Produces: top-level imports `from soccerhub import fetch_fbref_season, fetch_statsbomb_events, fetch_transfermarkt_values, Manifest, SoccerhubError`.

- [ ] **Step 1: Write the failing test**

`data-hub/tests/test_exports.py`:
```python
def test_top_level_exports():
    import soccerhub

    for name in (
        "fetch_fbref_season",
        "fetch_statsbomb_events",
        "fetch_transfermarkt_values",
        "Manifest",
        "SoccerhubError",
    ):
        assert hasattr(soccerhub, name), name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data-hub && python -m pytest tests/test_exports.py -v`
Expected: FAIL — `AssertionError: fetch_fbref_season`.

- [ ] **Step 3: Wire exports + write README**

`data-hub/src/soccerhub/__init__.py`:
```python
"""soccerhub — unified fetch layer for open-source soccer data."""

from soccerhub.errors import SoccerhubError
from soccerhub.manifest import Manifest
from soccerhub.readers.fbref import fetch_fbref_season
from soccerhub.readers.statsbomb import fetch_statsbomb_events
from soccerhub.readers.transfermarkt import fetch_transfermarkt_values

__all__ = [
    "SoccerhubError",
    "Manifest",
    "fetch_fbref_season",
    "fetch_statsbomb_events",
    "fetch_transfermarkt_values",
]
```

`data-hub/README.md`:
```markdown
# Data Hub (`soccerhub`)

Unified fetch layer for open-source soccer data. Fetch → cache to parquet →
return a manifest. Primary interface is the Python package; an MCP server wraps
the same functions for agent use.

## Install

    cd data-hub
    pip install -e ".[dev]"

## Use (package)

    from soccerhub import fetch_fbref_season, fetch_statsbomb_events, fetch_transfermarkt_values

    m = fetch_fbref_season("ENG-Premier League", "2023")
    print(m.path, m.rows, m.cols)      # parquet path + shape

    import pandas as pd
    df = pd.read_parquet(m.path)        # projects read the cached parquet directly

Cache directory: `SOCCERHUB_CACHE` env var, default `./data`.

## Use (MCP server)

    python -m soccerhub.mcp_server

Tools: `fbref_season`, `statsbomb_events`, `transfermarkt_values` — each returns
a manifest dict.

## Readers (v1 tracer bullet)

| Function | Source | Returns |
|---|---|---|
| `fetch_fbref_season(league, season)` | FBref (soccerdata) | player season stats |
| `fetch_statsbomb_events(match_id)` | StatsBomb open data (kloppy) | match events |
| `fetch_transfermarkt_values(competition)` | Transfermarkt (pre-scraped) | player valuations |

Adding a source is one new file in `readers/` reusing `cached_fetch` — see
`docs/specs/2026-07-14-soccerhub-data-layer-design.md`.
```

- [ ] **Step 4: Run the full suite**

Run: `cd data-hub && python -m pytest -v`
Expected: PASS — all tests across every file (smoke, manifest, cache, fbref, statsbomb, transfermarkt, mcp_server, exports).

- [ ] **Step 5: Commit**

```bash
cd data-hub
git add src/soccerhub/__init__.py README.md tests/test_exports.py
git commit -m "feat(soccerhub): wire top-level exports and add README"
```

---

## Optional follow-up (not part of v1)

- Live integration test hitting real FBref/StatsBomb/Transfermarkt, marked `@pytest.mark.network` and skipped by default.
- Add Sofifa and Understat readers (one file each, reusing `cached_fetch`).
- Root `README.md`: add project #2 (Data Hub) to the numbered project list.
