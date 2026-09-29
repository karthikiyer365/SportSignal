import json
import os
from pathlib import Path

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest

# FBref's comps index gender-suffixes any league that has a same-named
# women's competition ("Serie A (M)" / "Serie A (W)"); soccerdata 1.9.0
# still looks for plain "Serie A" and silently returns zero leagues.
# soccerdata merges ~/soccerdata/config/league_dict.json OVER its built-ins
# at import time, so we write the corrected entry there before importing.
_SERIE_A_ENTRY = {
    "ClubElo": "ITA_1",
    "MatchHistory": "I1",
    "FBref": "Serie A (M)",
    "ESPN": "ita.1",
    "Sofascore": "Serie A",
    "SoFIFA": "[Italy] Serie A",
    "Understat": "Serie A",
    "WhoScored": "Italy - Serie A",
    "season_start": "Aug",
    "season_end": "May",
}


def _patch_league_config() -> None:
    cfg_dir = (
        Path(os.environ.get("SOCCERDATA_DIR", Path.home() / "soccerdata")) / "config"
    )
    cfg = cfg_dir / "league_dict.json"
    data = json.loads(cfg.read_text()) if cfg.exists() else {}
    if data.get("ITA-Serie A", {}).get("FBref") != _SERIE_A_ENTRY["FBref"]:
        data["ITA-Serie A"] = _SERIE_A_ENTRY
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(data, indent=2))


def _season_to_code(season: str) -> str:
    """Start year -> soccerdata's unambiguous 4-digit code: '2021' -> '2122'.

    Passing '2021' raw makes soccerdata parse it as the 20-21 season (it even
    warns), which silently duplicated 2020 under the 2021 label.
    """
    y = int(season)
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def fetch_fbref_season(
    league: str, season: str, force: bool = False, stat_type: str = "standard"
) -> Manifest:
    """Player season stats for one league-season from FBref.

    ``season`` is the canonical start year ('2021' = 2021-22 season).
    ``stat_type`` is any table soccerdata supports (standard, defense, keeper…).
    """
    _patch_league_config()  # must precede the first soccerdata import in-process
    import soccerdata as sd  # lazy: keeps the heavy scraper stack off import time

    def produce():
        return sd.FBref(
            leagues=league, seasons=_season_to_code(season),
            # soccerdata caches the raw html separately; without this, force only
            # rebuilds the parquet from a stale page (and a season added upstream
            # after the cached index was written raises KeyError on its code).
            no_cache=force,
        ).read_player_season_stats(stat_type=stat_type)

    # legacy cache keys for "standard" predate the param — don't invalidate them
    params = {"league": league, "season": season}
    if stat_type != "standard":
        params["stat_type"] = stat_type

    return cached_fetch("fbref", "player_season", params, produce, force)
