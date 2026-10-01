"""StatsBomb open data -> SPADL actions for one competition-season.

Each game is cached on its own, so a dropped connection at game 200 resumes
at game 200 instead of starting over.
"""
import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest

SOURCE = "statsbomb_spadl"


def _loader():
    from socceraction.data.statsbomb import StatsBombLoader  # lazy: heavy import

    return StatsBombLoader(getter="remote")


def _to_spadl(events: pd.DataFrame, home_team_id: int) -> pd.DataFrame:
    import socceraction.spadl as spadl
    from socceraction.spadl.statsbomb import convert_to_actions

    return spadl.add_names(convert_to_actions(events, home_team_id=home_team_id))


def _game_players(loader, game_id: int) -> pd.DataFrame:
    teams = loader.teams(game_id)[["team_id", "team_name"]]
    return loader.players(game_id).merge(teams, on="team_id", how="left")


def fetch_statsbomb_spadl(
    competition_id: int, season_id: int, force: bool = False
) -> dict[str, Manifest]:
    """Games, SPADL actions and player minutes for one StatsBomb competition-season."""
    params = {"competition_id": competition_id, "season_id": season_id}
    loader = None

    def get_loader():
        nonlocal loader
        loader = loader or _loader()  # only built on a cache miss
        return loader

    games_m = cached_fetch(
        SOURCE, "games", params, lambda: get_loader().games(competition_id, season_id), force
    )
    games = pd.read_parquet(games_m.path)

    paths = []
    for g in games.itertuples(index=False):
        gp = {"game_id": int(g.game_id)}
        a = cached_fetch(
            SOURCE, "game_actions", gp,
            lambda g=g: _to_spadl(get_loader().events(g.game_id), g.home_team_id), force,
        )
        p = cached_fetch(
            SOURCE, "game_players", gp, lambda g=g: _game_players(get_loader(), g.game_id), force
        )
        paths.append((a.path, p.path))

    def stack(i):
        return lambda: pd.concat([pd.read_parquet(pp[i]) for pp in paths], ignore_index=True)

    return {
        "games": games_m,
        "actions": cached_fetch(SOURCE, "actions", params, stack(0), force),
        "players": cached_fetch(SOURCE, "players", params, stack(1), force),
    }
