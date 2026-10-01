"""Wyscout public dataset -> SPADL actions for one competition-season.

Every match of the 2017/18 top-5 leagues (+ World Cup 2018, Euro 2016), CC BY 4.0.
Attribution: Pappalardo et al. (2019), "A public data set of spatio-temporal match
events in soccer competitions", Scientific Data 6:236; data collected by Wyscout.

Not on the StatsBomb scale: Wyscout logs ~37% fewer actions (almost no carries,
different tackle/interception rules), so every Wyscout season gets its own model.
"""
import json

import pandas as pd

from soccerhub.cache import cache_root
from soccerhub.manifest import Manifest
from soccerhub.readers.spadl_season import fetch_spadl_season, game_players

SOURCE = "wyscout_spadl"


def _root():
    return cache_root() / "wyscout_public"


def _loader():
    from socceraction.data.wyscout import PublicWyscoutLoader  # lazy: heavy import

    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    # first use downloads the whole set once (~1 GB, figshare); afterwards reads it from disk
    return PublicWyscoutLoader(root=str(root), download=not (root / "competitions.json").exists())


def _to_spadl(events: pd.DataFrame, home_team_id: int) -> pd.DataFrame:
    import socceraction.spadl as spadl
    from socceraction.spadl.wyscout import convert_to_actions

    return spadl.add_names(convert_to_actions(events, home_team_id=home_team_id))


def _unescape(name):
    """'FC Bayern M\\u00fcnchen' -> 'FC Bayern München': Wyscout stores some accents as escape text."""
    if not isinstance(name, str) or "\\u" not in name:
        return name
    return name.encode("latin-1", "backslashreplace").decode("unicode-escape")


def _players(loader, game_id: int) -> pd.DataFrame:
    df = game_players(loader, game_id)
    return df.assign(team_name=df.team_name.map(_unescape), player_name=df.player_name.map(_unescape))


def _scores() -> pd.DataFrame:
    """Final score per match. The loader's games() has none; Wyscout's raw matches files do."""
    rows = []
    for path in _root().glob("matches_*.json"):
        for m in json.loads(path.read_text()):
            side = {v["side"]: v["score"] for v in m["teamsData"].values()}
            rows.append({"game_id": m["wyId"], "home_score": side["home"], "away_score": side["away"]})
    return pd.DataFrame(rows)


def fetch_wyscout_spadl(
    competition_id: int, season_id: int, force: bool = False
) -> dict[str, Manifest]:
    """Games (with scores), SPADL actions and player minutes for one Wyscout competition-season."""
    def games_of(L):
        return L.games(competition_id, season_id).merge(_scores(), on="game_id", how="left")

    return fetch_spadl_season(
        SOURCE, {"competition_id": competition_id, "season_id": season_id},
        make_loader=lambda: _loader(),
        games_of=games_of,
        actions_of=lambda L, g: _to_spadl(L.events(g.game_id), g.home_team_id),
        players_of=_players,
        force=force,
    )
