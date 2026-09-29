# Everything Football / Soccer

Football (soccer) data and analytics projects. Full topology (product, developer,
data flows): [`docs/TOPICAL_MAP.md`](docs/TOPICAL_MAP.md).

```
FBref · Transfermarkt · StatsBomb
        │  soccerhub readers (fetch → parquet cache → manifest)
        v
  pipelines: xref (entity resolution) → player_season (merge + clean)
        │  Actions cron Mon+Thu (HTTP sources)
        │  + local launchd, one league per weekday (FBref — see TOPICAL_MAP B8)
        v
  Supabase Postgres  ←  source of truth (RLS: anon read-only)
        │
        v
  site/ dashboards (Netlify)
```

## Projects

### 1. Soccer Data Hub (`soccerhub`)
Python package: unified fetch layer + pipelines for open football data. 18 seasons
(2008–2025) of the Big-5 leagues — player season stats, market values, transfers —
entity-resolved across FBref and Transfermarkt into Supabase.
See [`Soccer Data Hub/README.md`](Soccer%20Data%20Hub/README.md).

### 2. Site (`site/`)
Static dashboards on Netlify reading Supabase directly (anon key, select-only).
Live: pitch-themed landing + player dashboard (career values, G+A, transfers).
Live at <https://sports.karthikiyer.info> (Netlify custom domain).
Deployed by Netlify on push to main (`netlify.toml`, publish dir `site/`).
`netlify.toml` also rewrites `/api/ask` to the Render agent — same-origin, no CORS.

### 3. Player Performance Analysis (legacy, frozen)
FIFA player-scouting toolkit, 2015–2022 datasets: ETL, Dash dashboard, statistical
EDA. Standalone — shares no code with soccerhub.
See [`docs/product/football-scout-machine.md`](docs/product/football-scout-machine.md).

---

_Copyright © 2024–2026 Karthik Sivaraman Iyer. All rights reserved._
