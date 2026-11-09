"""WhoScored (Opta) events -> SPADL actions for one Big-5 league-season.

Current-season event data with every pass, carry, tackle and recovery located on the
pitch. Scraped through soccerdata's real Chrome (Cloudflare), so it runs on the user's
Mac only and breaks WhoScored's terms like the FBref chain does. Opta logs events
differently from StatsBomb and Wyscout: one model per league-season, never compared
across providers.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from soccerhub.manifest import Manifest
from soccerhub.readers.spadl_season import fetch_spadl_season, game_players

SOURCE = "whoscored_spadl"
# soccerdata caches one file per match here; loader ids are its league/season strings
FEEDS = {"whoscored": "events/{competition_id}_{season_id}/{game_id}.json"}
_WRAPPER = re.compile(r"^\s*<html><head></head><body>|</body></html>\s*$")


def strip_html_wrapper(text: str) -> str:
    """Chrome shows a raw JSON response as an HTML page; soccerdata 1.9 saves that page."""
    return _WRAPPER.sub("", text)


def _patch_whoscored_json() -> None:
    """Swap the `json` name inside soccerdata.whoscored only (it calls nothing but json.load)."""
    import soccerdata.whoscored as ws

    def load(fp):
        text = fp.read()
        return json.loads(strip_html_wrapper(text.decode() if isinstance(text, bytes) else text))

    ws.json = SimpleNamespace(load=load)


def _to_spadl(events: pd.DataFrame, home_team_id: int) -> pd.DataFrame:
    import socceraction.spadl as spadl
    from socceraction.spadl.opta import convert_to_actions

    return spadl.add_names(convert_to_actions(events, home_team_id=home_team_id))


FULL_TIME = 6  # WhoScored schedule status for a finished match


def finished_ids(schedule: pd.DataFrame) -> list[int]:
    """Only finished games: an unplayed game saves a `null` file, a live one a half match."""
    return schedule.loc[schedule.status == FULL_TIME, "game_id"].astype(int).tolist()


def drop_null_files(season_dir) -> int:
    """Remove `null` files soccerdata saved for unplayed games (they crash OptaLoader.games)."""
    stale = [f for f in Path(season_dir).glob("*.json") if f.read_bytes().strip() == b"null"]
    for f in stale:
        f.unlink()
    return len(stale)


def _loader(league: str, season_code: str):
    _patch_whoscored_json()
    import soccerdata as sd  # lazy: heavy browser stack

    ws = sd.WhoScored(leagues=league, seasons=season_code, headless=False)
    done = finished_ids(ws.read_schedule().reset_index())  # current season: fresh schedule
    drop_null_files(ws.data_dir / "events" / f"{league}_{season_code}")
    # downloads only finished games not yet cached; force_cache: schedule was just read
    return ws.read_events(match_id=done, force_cache=True, output_fmt="loader")


def fetch_whoscored_spadl(
    league: str, season_code: str, force: bool = False, refresh: bool = False
) -> dict[str, Manifest]:
    """Games, SPADL actions and player minutes for one league-season ('2526' = 2025/26)."""
    return fetch_spadl_season(
        SOURCE, {"league": league, "season": season_code},
        make_loader=lambda: _loader(league, season_code),
        games_of=lambda L: L.games(league, season_code),
        actions_of=lambda L, g: _to_spadl(L.events(g.game_id), g.home_team_id),
        players_of=game_players,
        force=force, refresh=refresh,
    )
