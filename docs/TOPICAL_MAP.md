# Topical Map

Generated 2026-07-17 at `8fb49fd` (+ match-center branch) · `⟶` = dependency edge ·
`▓ planned ▓` = claimed in docs/UI but absent from code · regenerate stale sections,
don't patch prose.

---

## MAP A — Product Topology

```
                       ┌────────────────────────┐
                       │ A0 Landing (pitch)     │
                       │ site/index.html        │
                       └───────────┬────────────┘
        ┌──────────────────┬───────┴────────────┬──────────────────────┐
        v                  v                    v                      v
┌──────────────────┐ ┌──────────────────┐ ┌─────────────────┐ ┌───────────────────┐
│ A1 Player        │ │ A7 Match Center  │ │ ▓ A2 player     │ │ ▓ A3 market       │
│ Dashboard        │ │ site/match.html  │ │ screens:        │ │ screens: transfer │
│ site/player.html │ │ standings, form, │ │ scouting,       │ │ market, inflation,│
└────────┬─────────┘ │ elo              │ │ value-vs-output │ │ age curves        │
         │           └────────┬─────────┘ └─────────────────┘ └───────────────────┘
         v                    v                  ┌──────────────────────┐
┌────────────────────────────────────┐           │ ▓ A4 event screens   │
│ Supabase (read, anon key, RLS)     │           │ shot maps, xG studio │
└────────────────────────────────────┘           └──────────────────────┘
┌──────────────────────────┐   ┌───────────────────────────┐
│ A5 FootballScout Machine │   │ A6 MCP server (agents)    │
│ legacy, standalone       │   │ soccerhub/mcp_server.py   │
└──────────────────────────┘   └───────────────────────────┘
```

**[A0] Landing page**
- What: pitch-themed hub; formation grid of 9 dashboard cards — 2 live (Player,
  Match Center), 7 `▓ planned ▓` ("In training" / "Next window" in the UI).
- Where: `site/index.html` (static — no JS beyond SMIL ball animation).
- Docs: none dedicated; deployed by Netlify (`netlify.toml`).
- Edges: ⟶ A1, ⟶ A7.
- Note: footer's "refreshed twice weekly" holds — cron covers all tables (C2/C3/C6/C7).

---

**[A1] Player Dashboard**
- What: player search → FIFA-style card per season: output-percentile rating vs
  positional peers, Bargain/Fair/Premium verdict (output pct − value pct, ±15 band),
  position-specific bars (FW/MF npG+A/90 · DF Tkl+Int/90 · GK save%), booking-card
  dots, value-vs-output peer scatter, career trend with age-curve overlay,
  market-value chart with transfer markers, collapsed transfer/season tables.
- Where: `site/player.html` (single file, inline JS; `hub()`, `cardModel()`,
  `pctsOf()` midrank percentiles, `scatter()`, `trendChart()`, `valueChart()`).
- Docs: none.
- Edges: ⟶ Supabase PostgREST (anon key, RLS select-only) reading `player_season`,
  `transfers`, `age_curve`; ⟵ A0 (nav).

---

**[▓ A2] Player screens — Scouting Screens, Value vs Output**
- What: moneyball filters; production-vs-price views. UI cards only, zero code.
- Where: `site/index.html:114-123` (cards marked `pos soon`).
- Edges: would read same `player_season` table as A1.

---

**[▓ A3] Market screens — Transfer Market, League Inflation, Age Curves**
- What: fees/moves explorer, league value growth, positional age arcs. Cards only.
- Where: `site/index.html:126-140`.
- Edges: would read `transfers` + `player_season` (both cron-refreshed, see C2/C3).

---

**[▓ A4] Event screens — Shot Maps, xG Studio**
- What: event-level shot data, xG-vs-goals. Cards only.
- Where: `site/index.html` (cards marked `pos soon`).
- Edges: would need StatsBomb events / Understat (B1 statsbomb reader exists,
  nothing downstream of it) — Phase C/D.

---

**[A7] Match Center**
- What: league + season picker → standings table computed client-side from match
  results, per-team panel (form chips, recent matches, Elo trend line).
- Where: `site/match.html` (single file, inline JS, same theme tokens as A1).
- Docs: none.
- Edges: ⟶ Supabase reading `matches`, `club_elo`; ⟵ A0 (nav).
- Known seam: club names differ per source (football-data "Bayern Munich" vs
  ClubElo "Bayern") — interim JS alias map; a proper `club_xref` table is the
  future fix (same ladder pattern as `player_xref`).

---

**[A5] FootballScout Machine (legacy)**
- What: FIFA-attribute scouting toolkit 2015–2022 — ETL to canonical CSVs, 3-tab Dash
  app on localhost:8080, offline EDA/statistics scripts.
- Where: `Player Performance Analysis/` — `player_data_generate.py` (ETL, 124 LOC),
  `player_static_analysis.py` (Dash app, 422 LOC), `football_data_cleaner.py`
  (EDA, 469 LOC).
- Docs: `docs/product/football-scout-machine.md` (notes the filename/content swap:
  cleaner = EDA script, static_analysis = dashboard).
- Edges: none — reads FIFA CSVs from a GitHub raw URL; shares nothing with soccerhub.

---

**[A6] MCP server (agent surface)**
- What: FastMCP wrapper — three reader tools (`fbref_season`, `statsbomb_events`,
  `transfermarkt_values`, each returns a manifest dict) plus `hub_table`
  (league/season/tm_id-filtered reads of the Supabase source of truth,
  truncated at `max_rows`).
- Where: `Soccer Data Hub/src/soccerhub/mcp_server.py`.
- Docs: `Soccer Data Hub/README.md` "Use (MCP server)".
- Edges: ⟶ B1 readers, ⟶ B5 `read_hub`.

---

## MAP B — Developer Topology

```
┌─────────────────────────── soccerhub package ("Soccer Data Hub/src") ─────────────┐
│                                                                                   │
│  ┌──────────────────┐      ┌─────────────────────────────────────────┐            │
│  │ B0 cache core    │<─────│ B1 readers: fbref / transfermarkt /     │            │
│  │ cache, manifest, │      │ statsbomb (fetch → parquet → Manifest)  │            │
│  │ errors           │      └───────────────┬─────────────────────────┘            │
│  └──────────────────┘                      │                                      │
│                          ┌─────────────────┴───────────┐                          │
│                          v                             v                          │
│               ┌────────────────────┐        ┌─────────────────────┐               │
│               │ B2 xref pipeline   │───────>│ B3 player_season    │               │
│               │ (entity resolution)│  ids   │ (merge + clean())   │               │
│               └─────────┬──────────┘        └──────────┬──────────┘               │
│                         │       ┌──────────────────────┤                          │
│                         v       v                      v                          │
│               ┌────────────────────┐        ┌─────────────────────┐               │
│               │ B6 run_season      │───────>│ B4 supa (upsert,    │               │
│               │ orchestrator       │        │ service role)       │               │
│               └────────────────────┘        └──────────┬──────────┘               │
│                                                        v                          │
│  ┌────────────────────┐                     ┌─────────────────────┐               │
│  │ B5 query.read_hub  │<────────────────────│   Supabase Postgres │               │
│  │ (anon, paginated)  │                     │   B7 migrations     │               │
│  └────────────────────┘                     └──────────┬──────────┘               │
└────────────────────────────────────────────────────────┼──────────────────────────┘
                                                         v
   ┌──────────────┐  ┌──────────────────┐     ┌────────────────────┐
   │ B8 CI: cron  │  │ B9 tests (13     │     │ B10 site frontend  │
   │ + pages      │  │ files, 817 LOC)  │     │ (inline JS, no     │
   │ deploy       │  └──────────────────┘     │ build step)        │
   └──────────────┘                           └────────────────────┘
```

**[B0] Cache core**
- What: content-addressed parquet cache + fetch memoizer; every reader routes through
  `cached_fetch(source, dataset, params, produce, force)`.
- Where: `soccerhub/cache.py` (76 LOC), `manifest.py` (36 — `Manifest` dataclass,
  `infer_date_range`), `errors.py` (2 — `SoccerhubError`).
- Docs: `Soccer Data Hub/README.md` (cache dir: `SOCCERHUB_CACHE`, default `./data`).
- Edges: ⟵ B1, B2, B3 (all builds are `cached_fetch` closures).

---

**[B1] Readers**
- What: source fetchers, one file per source; return `Manifest`, never DataFrames.
- Where: `soccerhub/readers/` — `fbref.py` (`_patch_league_config()` writes
  soccerdata's `league_dict.json` before import; `_season_to_code()` disambiguates
  "2021"→"2122"; `stat_type` param for misc/keeper pages), `transfermarkt.py`
  (players/transfers/values from transfermarkt-datasets), `matchhistory.py`
  (football-data.co.uk CSVs via bare `pandas.read_csv` — soccerdata's own
  MatchHistory reader 503s on this host), `clubelo.py` (snapshot by date +
  per-team history, plain HTTPS), `statsbomb.py` (events via kloppy, unused).
- Docs: hub README "Use (package)".
- Edges: ⟶ B0; ⟵ B2/B3 (`refetch` param forwards as `force`), ⟵ B6 presets, ⟵ A6.
- Note: only fbref needs a browser (Cloudflare/selenium) — the source of past
  zombie-Chrome memory leaks; every other source is a plain HTTP fetch.

---

**[B2] xref pipeline (entity resolution)**
- What: FBref (player, team) → Transfermarkt id; ladder OVERRIDES → mapping_file →
  exact → fuzzy, every rung birth-year-guarded; token blocking for fuzzy speed.
- Where: `soccerhub/pipelines/xref.py` (174 LOC) — `build_player_xref(league, season,
  force, refetch)`, `normalize()`, `_score()`.
- Docs: `docs/plans/2026-07-14-soccerhub-implementation-plan.md` (pre-dates OVERRIDES
  and the mononym rule — stale on matching details).
- Edges: ⟶ B1 (fbref + TM registry), ⟶ B0; ⟵ B6.

---

**[B3] player_season pipeline**
- What: flatten FBref stats, join xref ids + TM values, disambiguate same-name-same-team,
  then `clean()`: rate stats nulled < 450 min, age from birth_year, primary_position,
  value_is_stale flag.
- Where: `soccerhub/pipelines/player_season.py` (150 LOC) — `build_player_season()`,
  `flatten_fbref()`, `clean()`, `season_end()`.
- Docs: same plan doc as B2 (clean() rules only exist in code + tests).
- Edges: ⟶ B1, B2 output parquet, B0; ⟵ B6.

---

**[B4] Supabase write path**
- What: chunked upserts (500/req) with float→Int64 repair; service-role key, bypasses
  RLS. `CONFLICT_KEY = "league,season,team,player_name"`.
- Where: `soccerhub/pipelines/supa.py` (36 LOC) — `push_to_supabase()`, `upsert_df()`.
- Edges: ⟵ B6 (`push_to_supabase`, `push_xref`); ⟶ Supabase.
- Note: upsert can't delete — re-labeled seasons leave orphans; manual `DELETE` needed
  (happened once for the mislabeled 2021 season).

---

**[B5] Supabase read path**
- What: `read_hub(table, select, **eq_filters)` — paginated PostgREST reads (1000/page),
  anon key, RLS select-only. The API for all downstream analysis phases.
- Where: `soccerhub/pipelines/query.py` (36 LOC).
- Edges: ⟵ future analysis code; the site (B10) duplicates this logic in JS (`hub()`).

---

**[B6] Pipeline presets (cron entry points)**
- What: `run_season()` — xref (refetch) → push_xref → player_season (refetch) →
  upsert; `force=True` means re-download sources, not just re-merge. Plus
  `push_transfers()`, `push_age_curve()` (derived from the hub itself —
  PostgREST aggregates disabled), `push_matches(league, season)`,
  `push_club_elo(date)` and `push_club_elo_history(team)` (level==1 +
  country→league map; relegation spells dropped, not mislabeled).
- Where: `soccerhub/pipelines/__init__.py` + `pipelines/matches.py`; conflict
  keys mirror each table's PK.
- Edges: ⟶ B1, B2, B3, B4, B5; ⟵ B8 cron.

---

**[B7] Migrations (manual apply)**
- What: 7 SQL files — schema + RLS anon-read policies. **No migration runner**: user
  applies each in the Supabase SQL editor by hand; files are the record, not the tool.
  Tables: player_season (+0003 clean cols, +0006 defense/keeper cols), transfers,
  player_xref, age_curve, matches, club_elo.
- Where: `Soccer Data Hub/supabase/migrations/0001 … 0007`.
- Edges: defines tables B4 writes and B5/B10 read.

---

**[B8] CI / automation — split by IP trust**
- What: the refresh runs in two places, split on whether the source needs a browser.
  - GitHub Actions `run-season.yml`, cron Mon+Thu 06:00 UTC, three jobs:
    `transfers`, `matches` (5-league matrix, full parallel — plain CSV), `club-elo`
    (tolerates a fetch failure and emits a `::warning::` instead of failing the run).
  - This Mac, launchd `com.ikarthik.soccerhub-fbref`, 06:00 local Mon-Fri, **one
    league per weekday** (Mon=ENG, Tue=ESP, Wed=GER, Thu=ITA, Fri=FRA — the script
    picks it from the weekday, so the plist needs no per-day config):
    `scripts/refresh_fbref_chain.py` runs seasons -> understat -> age_curve. Ordered,
    not parallel — understat and age_curve update rows that `run_season` writes.
    `LEAGUE=<name>` re-runs a missed day; `--all` does five (expect a block).
- Why split: FBref sits behind a Cloudflare interactive challenge. `soccerdata`
  clears it with a real Chrome (`class FBref(BaseSeleniumReader)`) but only from a
  residential IP. On a runner the browser starts, burns all five attempts and raises
  `Could not download https://fbref.com/en/comps/`. Verified 2026-09-28: identical
  code returned 551 rows locally and failed on every runner. Adding Chrome or Xvfb
  to CI does not help — Chrome was already there.
- Season: derived from the date by `current_season()` (August cutover), so nothing
  needs an annual bump. Override with `SEASON=` for a backfill.
- Where: `.github/workflows/run-season.yml`, `Soccer Data Hub/scripts/`,
  `~/Library/LaunchAgents/com.ikarthik.soccerhub-fbref.plist`, `netlify.toml`.
- Why one league per day: the pipeline pulls three FBref pages per league
  (`standard`, `misc`, `keeper`), each behind its own challenge. All five leagues in
  one pass is 15 gated fetches and trips FBref's per-IP limit. Measured 2026-09-29:
  ENG completed in 35 min, ESP got 2 of 3 pages then was refused with "failed
  CAPTCHA, IP block or network issues", and the run was abandoned. Spread over
  weekdays each league still refreshes weekly — better than a twice-weekly target
  that cannot finish.
- Note: launchd skips a fire while the Mac sleeps and catches up on wake, so a
  refresh can land late. Logs: `~/.soccerhub/logs/fbref-{out,err}.log`.
- Note: soccerdata leaks a `uc_driver` process per retry (it re-inits without
  quitting the dead session); the script reaps them at exit.
- Note: the workflow is still named `run-season` though `seasons` now runs locally.

---

**[B9] Tests**
- What: pytest, 15 files / 45 tests, all monkeypatch-based (no network). Cover season
  codes, xref ladder, disambiguation, clean() rules, defense/keeper merge, upsert
  chunking, read_hub pagination, refetch propagation, every push_* preset's table +
  conflict key, MCP tools, exports.
- Where: `Soccer Data Hub/tests/test_*.py`.
- Edges: ⟶ every B0–B6 unit.

---

**[B10] Site frontend**
- What: three static HTML files, inline CSS/JS, zero dependencies and no build step.
  Talks straight to PostgREST with the publishable anon key (safe: RLS select-only).
- Where: `site/index.html`, `site/player.html`, `site/match.html`.
- Edges: ⟶ Supabase REST; deployed by B8. Duplicates B5's pagination/read logic in JS —
  intentional (no shared runtime between Python and browser).

---

**[B11] Legacy: Player Performance Analysis**
- What: pre-soccerhub standalone project (FIFA CSVs, Dash). No imports in or out of
  the soccerhub package; frozen since 2024.
- Where: `Player Performance Analysis/` (1,015 LOC across 3 scripts).
- Docs: `docs/product/football-scout-machine.md`, root `README.md` §3.

---

## MAP C — Per-feature backend processing

**C1 · Player dashboard read path (live)**

```
player.html search box
  └──> runSearch(q)  ── 300ms debounce ──> hub("player_season",
                                            {player_name: "ilike.*q*"})
         │                                  GET {SUPABASE_URL}/rest/v1/… apikey=anon
         v
       load()  ── ?tm=<id> or ?name= ──> hub("player_season", …)   [career rows]
         │                          └──> hub("transfers", {tm_id: eq})  [moves]
         v
       render(rows, moves)
         ├──> valueChart(rows, moves)   amber line; dashed markers = recorded
         │                              transfers, dotted = synthetic club changes
         ├──> gaChart(rows)             green bars + minutes / G+A/90 overlays
         ├──> transfers table           fee null -> "free / undisclosed"
         └──> season log                per-90 "—" under 450 min; stale-value ⚠
```
No writes. Anon key only; RLS blocks everything but SELECT.

---

**C2 · Cron season refresh (write path)** — runs on this Mac, not CI (see B8)

```
launchd com.ikarthik.soccerhub-fbref (Mon+Thu 06:00 local)
  └──> scripts/refresh_fbref_chain.py   season = SEASON or current_season()
  └──> run_season(league, season, force=True)          pipelines/__init__.py:34
         ├──> build_player_xref(refetch=True)          pipelines/xref.py:69
         │      ├──> fetch_fbref_season(force=True)    readers/fbref.py:54
         │      ├──> fetch_transfermarkt_players(force=True)
         │      └──> ladder: OVERRIDES → mapping → exact → fuzzy (year-guarded)
         ├──> push_xref(m, league, season)             upsert player_xref
         │                                             key: league,season,team,fbref_name
         ├──> build_player_season(refetch=True)        pipelines/player_season.py:81
         │      ├──> flatten_fbref() → join xref → join TM values
         │      ├──> same-name disambiguation (birth-year suffix)
         │      └──> clean()  rates<450min→null · age · primary_position · stale flag
         └──> push_to_supabase(m, "player_season")     upsert, 500-row chunks
                                                       key: league,season,team,player_name
```
Side effects live in app code only — no DB triggers. Upsert never deletes (orphan risk
on key changes). After the five leagues, the same script runs understat then age_curve —
both update rows this stage writes, so the order is load-bearing.

---

**C3 · Transfers refresh (write path)**

```
run-season.yml `transfers` job (same cron)
  └──> push_transfers(force=True)              pipelines/__init__.py
         └──> fetch_transfermarkt_transfers()  readers/transfermarkt.py:55
                (rename player_id→tm_id, drop future-dated placeholders, dedup)
                └──> upsert_df(df, "transfers", "tm_id,transfer_date")
```
Upstream coverage is still partial (big historic moves can be missing) — the player
page's synthetic club-change markers stay necessary.

---

**C6 · Match results refresh (write path)**

```
run-season.yml `matches` job (5-league matrix, parallel)
  └──> push_matches(league, SEASON, force=True)   pipelines/__init__.py
         └──> build_matches()                     pipelines/matches.py
                └──> fetch_match_history()        readers/matchhistory.py
                       pd.read_csv(football-data.co.uk/mmz4281/<code>/<div>.csv)
                       └──> column map, DD/MM/YY(YY) → ISO, drop void rows
                └──> + league/season key cols
         └──> upsert_df(df, "matches", "league,season,date,home_team,away_team")
```
Backfilled 2008–2025 × 5 leagues (32,545 rows, zero failures).

---

**C7 · Club Elo refresh (write path)**

```
run-season.yml `club-elo` job
  └──> push_club_elo(force=True)                 today's snapshot, Big-5 filter
         └──> fetch_club_elo_snapshot()          readers/clubelo.py (date-keyed cache)
         └──> upsert_df(df, "club_elo", "team,league,snapshot_date")
one-off backfill (done):
  push_club_elo_history(team) per club           per-rating-change series since 2008
  + twice-yearly date snapshots 2008–2025        covers clubs the per-team endpoint
                                                 can't serve (Saint-Etienne, Arles)
```
191k rows. Team names are ClubElo spellings — see the A7 club-name seam.

---

**C4 · Landing/site deploy**

```
git push main ──> Netlify build hook ──> publish site/ ──> *.netlify.app
  └──> /api/ask rewrite ──> soccerhub-agent.onrender.com/ask  (see C5)
```
Netlify chosen over GitHub Pages: Pages is static-only and cannot rewrite
`/api/ask`, so the agent call would break CORS. Pages deploy removed 2026-09-21.

---

**C5 · Legacy FIFA ETL (frozen)**

```
player_data_generate.py ──> FIFA CSVs from raw.githubusercontent ──> clean/explode/
impute ──> Male_Players.csv / Female_Players.csv (local) ──> player_static_analysis.py
(Dash :8080) / football_data_cleaner.py (EDA)
```

---

## Cross-map bridges

| Product node | Runs on | Key seam to check when touching it |
|---|---|---|
| A0 Landing | B10, B8 (pages) | card stats hard-coded — restate after big loads |
| A1 Player Dashboard | B10 ⟶ B7 tables ⟵ C2 | JS `hub()` vs Python `read_hub()` — same PostgREST semantics, changed separately |
| A1 value markers | C2 + C3 | upstream transfer coverage partial — synthetic markers stay necessary |
| A1 verdict/bars | C2 (misc/keeper 2017+) | DF/GK metrics absent pre-2017 — card degrades to "NO VERDICT" by design |
| A7 Match Center | C6 + C7 | club-name mismatch across sources — JS alias map until a `club_xref` exists |
| ▓ A2/A3 screens | B5 or B10, C2/C3 | tables cron-refreshed; build when ready |
| ▓ A4 screens | B1 statsbomb (unused) | no event ingestion yet — Phase C/D |
| A6 MCP server | B1 + B5 | hub_table truncates at max_rows — filter before trusting counts |
| A5 legacy | nothing shared | safe to archive; only root README references it |
