"""Shared season loop for the SPADL readers (StatsBomb, Wyscout).

Each game is cached on its own, so a dropped connection at game 200 resumes
at game 200 instead of starting over. The provider reader supplies how to
list games, convert one game's events, and read one game's players.
"""
import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest


def fetch_spadl_season(source, params, make_loader, games_of, actions_of, players_of, force=False) -> dict[str, Manifest]:
    """Games, SPADL actions and player minutes for one competition-season."""
    loader = None

    def get_loader():
        nonlocal loader
        loader = loader or make_loader()  # only built on a cache miss
        return loader

    games_m = cached_fetch(source, "games", params, lambda: games_of(get_loader()), force)
    games = pd.read_parquet(games_m.path)

    paths = []
    for g in games.itertuples(index=False):
        gp = {"game_id": int(g.game_id)}
        a = cached_fetch(source, "game_actions", gp, lambda g=g: actions_of(get_loader(), g), force)
        p = cached_fetch(source, "game_players", gp, lambda g=g: players_of(get_loader(), g.game_id), force)
        paths.append((a.path, p.path))

    def stack(i):
        return lambda: pd.concat([pd.read_parquet(pp[i]) for pp in paths], ignore_index=True)

    return {
        "games": games_m,
        "actions": cached_fetch(source, "actions", params, stack(0), force),
        "players": cached_fetch(source, "players", params, stack(1), force),
    }


def game_players(loader, game_id: int) -> pd.DataFrame:
    """Player minutes for one game, with team names attached."""
    teams = loader.teams(game_id)[["team_id", "team_name"]]
    return loader.players(game_id).merge(teams, on="team_id", how="left")
