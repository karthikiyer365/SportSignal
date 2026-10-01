"""StatsBomb open data -> SPADL actions for one competition-season."""
import pandas as pd

from soccerhub.manifest import Manifest
from soccerhub.readers.spadl_season import fetch_spadl_season, game_players

SOURCE = "statsbomb_spadl"


def _loader():
    from socceraction.data.statsbomb import StatsBombLoader  # lazy: heavy import

    return StatsBombLoader(getter="remote")


def _to_spadl(events: pd.DataFrame, home_team_id: int) -> pd.DataFrame:
    import socceraction.spadl as spadl
    from socceraction.spadl.statsbomb import convert_to_actions

    return spadl.add_names(convert_to_actions(events, home_team_id=home_team_id))


def fetch_statsbomb_spadl(
    competition_id: int, season_id: int, force: bool = False
) -> dict[str, Manifest]:
    """Games, SPADL actions and player minutes for one StatsBomb competition-season."""
    return fetch_spadl_season(
        SOURCE, {"competition_id": competition_id, "season_id": season_id},
        make_loader=lambda: _loader(),
        games_of=lambda L: L.games(competition_id, season_id),
        actions_of=lambda L, g: _to_spadl(L.events(g.game_id), g.home_team_id),
        players_of=game_players,
        force=force,
    )
