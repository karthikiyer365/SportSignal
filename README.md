# Everything Football / Soccer

Football (soccer) data and analytics projects. Current data flow, schedule and stores:
[`docs/architecture/system-map.md`](docs/architecture/system-map.md). Older full topology:
[`docs/architecture/topical-map.md`](docs/architecture/topical-map.md) (predates the FotMob/WhoScored work).

```
FBref · Understat · Transfermarkt · football-data · ClubElo · FotMob · WhoScored (Opta)
StatsBomb/Wyscout open · Baseball Savant
        │  soccerhub readers (fetch → parquet cache → manifest)
        v
  pipelines: xref → player_season · player_match · shots · VAEP (action_score) · links
        │  GitHub Actions, Mon (plain HTTP/CSV sources)
        │  + local launchd, daily 06:00: one Big-5 league per day, ISL on Tuesday
        v
  Supabase Postgres + Storage  ←  source of truth (RLS: anon read-only)
        │
        v
  site/ dashboards (Netlify)  ·  /api/ask → Render agent
```

## Layout

```
data-hub/          Python package soccerhub: readers → pipelines → db (Supabase read/write)
site/              static dashboards (Netlify publish dir)
baseball/          Statcast pitch-quality notebook + plan
docs/              product/ · architecture/ · specs/ · plans/
```

Names: kebab-case folders and doc files, no spaces; `README.md` is the only uppercase file.

## Projects

### 1. Data Hub (`soccerhub`)
Python package: unified fetch layer + pipelines for open football data, into Supabase.
- Big 5: 18 seasons (2008–) of player season stats, market values and transfers, entity-resolved
  across FBref and Transfermarkt; Understat xG and shots (2014–).
- Per-match player stats from FotMob for the Big 5 and the **Indian Super League**, 2021/22 →.
- On-ball action values (VAEP) from StatsBomb 2015/16, Wyscout 2017/18 and **WhoScored (Opta)
  2025/26 → current season**.

See [`data-hub/README.md`](data-hub/README.md).

### 2. Site (`site/`)
Static dashboards on Netlify reading Supabase directly (anon key, select-only).
Live: landing page, player dashboard (career values, G+A, transfers, shot map),
match centre, team analysis (VAEP action maps with per-match filter and touch heatmap),
baseball pitch quality.
Live at <https://sports.karthikiyer.info> (Netlify custom domain).
Deployed by Netlify on push to main (`netlify.toml`, publish dir `site/`).
`netlify.toml` also rewrites `/api/ask` to the Render agent — same-origin, no CORS.

### 3. Baseball (`baseball/`)
Pitch-quality pipeline on Statcast. See [`baseball/README.md`](baseball/README.md).

---

_Copyright © 2024–2026 Karthik Sivaraman Iyer. All rights reserved._
