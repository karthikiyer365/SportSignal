"""Build site/data/hero.json: the rotating landing-page hero charts.

Soccer: every Understat shot for a few players (shot map).
Baseball: a sample of real pitches per pitch type for a few pitchers (movement, catcher's view).

Run from Soccer Data Hub/:  python scripts/build_hero.py
Needs SUPABASE_URL + SUPABASE_PUBLISHABLE_KEY (read-only) and the local statcast cache.
"""
import json
import os
import random
from pathlib import Path

import requests

# (Understat name, display name, button label) in rotation order
SOCCER = [
    ("Lionel Messi", "Lionel Messi", "Messi"), ("Cole Palmer", "Cole Palmer", "Palmer"),
    ("Kylian Mbappe-Lottin", "Kylian Mbappé", "Mbappé"), ("Eden Hazard", "Eden Hazard", "Hazard"),
    ("Cristiano Ronaldo", "Cristiano Ronaldo", "Ronaldo"),
    ("Vinícius Júnior", "Vinícius Júnior", "Vinícius"), ("Virgil van Dijk", "Virgil van Dijk", "Van Dijk"),
]
# (MLBAM id, season, button label): season = the pitcher's latest with 1,500+ pitches
BASEBALL = [
    (554430, 2026, "Wheeler"), (660271, 2023, "Ohtani"), (694973, 2026, "Skenes"), (669373, 2026, "Skubal"),
    (543037, 2026, "Cole"), (645261, 2026, "Alcantara"), (543243, 2026, "Gray"),
]
PITCHES_PER_TYPE = 26
OUT = Path(__file__).resolve().parents[2] / "site" / "data" / "hero.json"


def shots(name, display, short):
    url, key, rows = os.environ["SUPABASE_URL"], os.environ["SUPABASE_PUBLISHABLE_KEY"], []
    while True:  # Supabase caps every response at 1000 rows
        r = requests.get(f"{url}/rest/v1/shots_understat", headers={"apikey": key}, timeout=60,
                         params={"select": "xg,location_x,location_y,result", "player": f"eq.{name}",
                                 "order": "shot_id", "limit": 1000, "offset": len(rows)})
        r.raise_for_status()
        rows += r.json()
        if len(r.json()) < 1000:
            break
    return {"name": display, "short": short, "shots": [[round(s["location_x"], 3), round(s["location_y"], 3), round(s["xg"], 3),
                                     int(s["result"] == "Goal")] for s in rows]}


def pitches(pid, season, short):
    from soccerhub.pipelines import statcast as sc

    if season not in SEASON_CACHE:
        SEASON_CACHE[season] = sc.load_season(season)
    d = SEASON_CACHE[season]
    d = d[(d.pitcher == pid) & d.pfx_x.notna() & d.pitch_type.notna()]
    last, first = d.player_name.iloc[0].split(", ")
    lefty = d.p_throws.iloc[0] == "L"
    out = {"name": f"{first} {last}", "short": short, "season": season, "types": {}}
    for t, g in sorted(d.groupby("pitch_type"), key=lambda kv: -len(kv[1])):
        if len(g) < 25:
            continue
        x = -g.pfx_x if lefty else g.pfx_x  # the cache stores LHP mirrored; the hero shows the catcher's view
        pts = list(zip((x * 12).round(1), (g.pfx_z * 12).round(1)))
        random.seed(f"{pid}{t}")
        out["types"][t] = [list(map(float, p)) for p in random.sample(pts, min(PITCHES_PER_TYPE, len(pts)))]
    return out


SEASON_CACHE = {}   # several pitchers share a season; load each season's parquet once


if __name__ == "__main__":
    data = {"soccer": [shots(*a) for a in SOCCER], "baseball": [pitches(*a) for a in BASEBALL]}
    for p in data["soccer"]:
        print(p["name"], len(p["shots"]), "shots,", sum(s[3] for s in p["shots"]), "goals")
    for p in data["baseball"]:
        print(p["name"], list(p["types"]))
    OUT.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    print(OUT, round(OUT.stat().st_size / 1024), "KB")
