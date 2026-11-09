# Multi-sport landing page + light theme — design

**Date:** 2026-09-21
**Status:** approved, implementation started
**Scope:** `site/index.html`, `site/player.html`, `site/match.html`

## Problem

The site is becoming sports analytics across multiple sports and multiple entity
types (players, teams), not a football site. Two things block that:

1. **The landing page is football at the structural level.** `index.html` is a
   4-3-3: nine cards in three rows tagged "front three / midfield / back line",
   each wearing a shirt number. The nine slots *are* the formation — a basketball
   dashboard cannot wear the number 6 in midfield. Six of the nine were also
   unbuilt but styled identically to the live ones, so the page read as far more
   complete than it was.
2. **It is a nav grid, not a landing page.** No hero, no editorial, nothing that
   explains what the database is to someone who has not used it.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Sport first** is the primary navigation axis | Each sport needs different surfaces — basketball has no transfer market, soccer has no draft. Analysis-type-first forces one page to swap data sources; a flat sport × entity matrix goes stale as most cells stay empty. |
| 2 | Landing is a **soccer-forward hub with a sport switcher**, not a pure chooser | Soccer is the only sport with data. A pure chooser costs every current user a click through an almost-empty menu. The structure is still sport-first, so adding a sport is a nav entry, not a redesign. |
| 3 | Layout is **editorial hero inside a split frame** | Hero carries a story (headline, dek, two CTAs) with a chart card beside it, then a stat band, then surfaces. Serves the reader and the person looking someone up without either scrolling. |
| 4 | Visual treatment is **Clean**: true white, tight sans, emerald `#0e9f6e`, soft shadows, pill buttons | Most sport-neutral of the three mocked. The alternative (tinted green panels) kept the most brand equity but is the most football-coded — it would look wrong the day basketball lands. |
| 5 | **Light shell, solid dark-green data panels** — not a full light flip | See "Theme — what actually shipped" below. |
| 6 | **Editorial is deferred**; files stay flat | Posts have no storage yet and the site has no build step. v1 ships without a writing band rather than shipping a "coming soon" one. Sport folders (`site/soccer/…`) wait until a second sport exists — equally cheap then. |

## v1 landing composition

```
nav        brand · sport switcher (soccer live, rest disabled) · search
hero       kicker · headline · dek · 2 CTAs   │   animated chart card
band       49,692 · 542,481 · 32,545 · 18     │   sources note
surfaces   4 cards — Player, Match Center (live) · Team, Scouting (in progress)
footer     data sources
```

The hero keeps the editorial slot's exact shape while holding a product message.
When posts exist, swapping in a story is a text change, not a layout change.

### Rules this page follows

- **Unbuilt surfaces are not links.** `<div class="card soon">`, flat, on the grey
  band — no hover lift, no arrow. The old page styled all nine identically.
- **The hero chart is real.** Bars are non-penalty goals, the line is npxG, the gap
  is the finishing — the same read as the Value tab, with a caption saying so.
- **Motion respects `prefers-reduced-motion`**: the draw, the bar rise and the
  travelling dot are all disabled, not merely slowed.
- **Amber is never text on white.** `#ffb43a` on `#fff` is ~1.9:1. It survives as a
  fill and as the travelling dot; `#e08a00` carries it where it must mean something.

## Theme — what actually shipped

The plan was tokenise, then flip everything to light. **The flip stopped at the
page shell.** Data panels are solid dark green on a white page.

### Why the panels are not light

A half-opaque green has no working data palette. Measured against the candidate
panel colours, worst-case contrast for each series set:

| Panel | Text | Light-ground series | Dark-ground series |
|---|---|---|---|
| `#d9efe4` | 15.0:1 | 3.4:1 | 1.2:1 |
| `#bfe3d0` | 13.0:1 | 3.0:1 | 1.1:1 |
| `#8fc9ad` | 9.6:1 | **2.2:1** | **1.0:1** |
| `#4d8f6f` | 4.7:1 | **1.1:1** | **1.5:1** |
| `#0f4a36` | 10.2:1 | 2.1:1 | **4.1:1** |

Everything between a pale tint and a genuinely dark green is a dead zone: the
dark-ground colours never clear 1.5:1 and the light-ground ones fall under 3:1.
There is no series palette that reads on a mid-green. So the choice was a pale
tint or a solid dark panel, and solid won on the grounds that the SVG code was
written for a dark ground.

### The two layers

- **Shell** (light): `body`, `.top` nav, search and dropdowns, `.chips`, `.tabs`,
  and any text sitting directly on the page — `.empty`, `.cardnote`, `.scopelabel`.
  Lives in an appended `--shell-*` block at the end of each page's stylesheet.
- **Panels** (dark): `--card:#0f4a36`, hero strip `#17624a → #0e4634`, every chart,
  the tooltip, the season log.

Chips and tabs use `--shell-accent-deep` `#0b7c56` with white text, 5.2:1.

### Series colours on `#0f4a36`

`--green #8fd18a` 5.7:1 · `--amber #ffb43a` 5.8:1 · `--chalk-y #e8d47a` 6.9:1 ·
`--blue #5aa9f0` 4.1:1 · `--red #f07d73` 3.8:1.

`--red` was `#e0524a`, tuned for the old near-black `#0a1a0e`; it fell to 2.7:1 on
the lighter panel and was lifted.

### Two traps this hit

1. **A second palette lives in JS.** The radar builds SVG fills as strings, so it
   cannot use `var()` and resolves through a hardcoded `HEX` map. Every palette
   change has to be made twice or the radar drifts off every other chart.
2. **Panels must declare their own text colour.** The shell sets
   `body{color:var(--shell-ink)}` for the white page; anything unstyled inside a
   dark panel inherits that dark ink and disappears. Fixed by
   `.herostrip,.box,details.season-log,#tip{color:var(--line)}`.

## Out of scope — each needs its own spec

Basketball and other sport data pipelines; team analysis surfaces; scouting
screens; the posts/editorial storage model.

## Naming — resolved

The site is **SportSignal**. "SoccerHub" and "Every number on the pitch" were
football-locked and could not survive a Basketball tab.

Renamed across `index.html`, `player.html` and `match.html` (7 references). The
`⚽` that prefixed the wordmark in the two dashboard navs is gone for the same
reason — a ball beside a multi-sport name reads as a contradiction. Those two
pages still carry a `⚽` favicon and the dark palette; both are picked up by the
theme flip, which rebuilds their navs anyway.
