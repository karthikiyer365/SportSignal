# Data Hub (`soccerhub`) — Design Spec

_Plan · Project #2 · created 2026-07-14_

## Overview

`soccerhub` is a centralized, data-engineered fetch layer over open-source soccer
data. It exists so every downstream data-science project pulls clean, cached data
through one substrate instead of re-scraping sources ad hoc. It is primarily an
**installable Python package**; an MCP server is a thin wrapper on top so a future
LLM agent can call the same functions. Coverage is maximized with the minimum
dependencies: `soccerdata` (tabular providers) + `kloppy` (event/tracking) +
a pre-scraped Transfermarkt dataset (market values).

## Goals

- One import (`from soccerhub import fetch_…`) that DS projects use to pull data.
- Fetches are cached to disk as parquet; repeat calls are instant (cache hit).
- Each fetch returns a **manifest** (path + metadata), not inline rows.
- Adding a new source is one new file + one function — no rewrite.

## Non-goals (v1, explicit YAGNI)

- Unified `fetch()` dispatcher and cross-source column normalization.
- Entity resolution / cross-source player & team ID mapping.
- Sofifa and Understat readers (added later, cheaply).
- Live Transfermarkt scraping API.
- The LLM/agent layer (Layer 3).

## Architecture

Three layers, one core:

```
Layer 1  installable package `soccerhub`  ← the substrate (primary artifact)
           readers + cache + manifest
Layer 2  MCP server (thin adapter)        ← each tool calls a Layer-1 fn
Layer 3  LLM agent over MCP (future)      ← out of scope for v1
```

DS projects import Layer 1 directly (no protocol overhead). The future LLM layer
talks to Layer 2, which just calls Layer 1.

## Repo layout

```
Everything-Football-Soccer/
└── data-hub/
    ├── pyproject.toml              # pip install -e .  (deps: soccerdata, kloppy, mcp, pandas, pyarrow)
    ├── README.md
    ├── src/soccerhub/
    │   ├── __init__.py             # re-exports the 3 fetch_* fns
    │   ├── cache.py                # cache_key(), path helpers, write/read parquet (atomic)
    │   ├── manifest.py             # Manifest dataclass + to/from json
    │   ├── readers/
    │   │   ├── fbref.py            # fetch_fbref_season(league, season)
    │   │   ├── statsbomb.py        # fetch_statsbomb_events(match_id)
    │   │   └── transfermarkt.py    # fetch_transfermarkt_values(competition)
    │   └── mcp_server.py           # Layer 2: FastMCP, 3 tools → the 3 readers
    └── tests/test_cache.py         # one smoke test
```

Cache directory: `SOCCERHUB_CACHE` env var, default `./data/` (gitignored).

## Core contract

Every reader is a plain function following one shape — no base class, no ABC
(over-abstraction for three functions):

```python
def fetch_<source>_<dataset>(**params, force=False) -> Manifest:
    key = cache_key("<source>", "<dataset>", params)
    if not force and cache_hit(key):
        return read_manifest(key)                 # cache hit → instant
    obj  = <library call>                         # soccerdata / kloppy / download
    df   = to_dataframe(obj)                       # kloppy EventDataset → .to_df()
    path = write_parquet(key, df)                  # temp file → atomic rename
    return write_manifest(key, source, dataset, params, path, df)
```

`Manifest` fields: `path, source, dataset, params, rows, cols, date_range,
fetched_at`. All shared logic lives in `cache.py` + `manifest.py`; adding Sofifa
or Understat later is ~15 lines in a new `readers/*.py` reusing those helpers.

## The three tracer readers (one per data shape)

| Reader | Library | Shape proven | Cached output |
|---|---|---|---|
| `fetch_fbref_season(league, season)` | soccerdata | tabular DataFrame | season stats parquet |
| `fetch_statsbomb_events(match_id)` | kloppy | event stream → `.to_df()` | events parquet |
| `fetch_transfermarkt_values(competition)` | pre-scraped download | static file filtered | values parquet |

Three distinct ingestion paths flush out every caching problem now.

## MCP server (Layer 2)

`mcp_server.py` uses FastMCP: three `@mcp.tool()` wrappers, each calls its reader
and returns the manifest dict (~40 lines total). DS projects may bypass this and
`import soccerhub` directly.

## Error handling

- Readers raise `SoccerhubError` on library/network failure.
- Manifest is written only on a complete fetch — cache is never poisoned; the
  next call retries clean.
- Cache writes are atomic: write to a temp path, then rename.

## Testing

One smoke test (`tests/test_cache.py`): a cache miss writes parquet + manifest;
a cache hit returns the manifest without re-fetching (library call mocked). This
is the smallest runnable check on the load-bearing cache/manifest logic.

## Data flow

```
   DS project (import)                 LLM agent (MCP, later)
          │                                    │
          │                                    ▼
          │                       mcp_server.py (Layer 2)
          │                       @mcp.tool → calls reader
          └──────────────┬─────────────────────┘
                         ▼
            READER  fetch_<source>_<dataset>
                         │
              key = cache_key(source, dataset, params)
                         │
                 ┌───────┴────────┐
              HIT│                │MISS
                 ▼                ▼
         read_manifest   library call (fbref/statsbomb/transfermarkt)
                 │                │
                 │        to_dataframe(obj)
                 │                │
                 │        write_parquet(tmp)→rename (atomic)
                 │                │
                 │        write_manifest(key, …)
                 └───────┬────────┘
                         ▼
                   return Manifest
                         │  path →
                         ▼
            data/<source>/<key>.parquet  (gitignored)
                         │
                         ▼
            DS project reads parquet for modeling

   library/network error → raise SoccerhubError, NO manifest written
```

## Key decisions

| Concern | Decision | Rationale |
|---|---|---|
| Interface | Package first, MCP as thin wrapper | DS projects need imports now; LLM layer rides on top later |
| Return shape | Cache-to-disk + manifest | Honest data-eng shape; handles big data; reproducible |
| Unification | Per-source functions, no unified `fetch()` yet | Dodges premature entity-resolution work |
| v1 scope | 3-reader tracer bullet (one per data shape) | Least code that exercises every caching path |
| Extensibility | Shared cache/manifest helpers, plain functions | Adding a reader = one file, no new abstraction |
| Transfermarkt | Pre-scraped dataset, not live scrape | No fragile scraping; gives market values for valuation projects |

## Data coverage note

- Broad tabular stats across many leagues/seasons (FBref).
- Deep event data only for StatsBomb free competitions (World Cups, Euros,
  FA WSL, Messi's La Liga career, select finals) — deep but narrow.
- Transfermarkt market values are weeks-old (pre-scraped snapshot).
