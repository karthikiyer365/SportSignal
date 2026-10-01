import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


class FakeLoader:
    def __init__(self):
        self.event_calls = 0

    def games(self, competition_id, season_id):
        assert (competition_id, season_id) == (2, 27)
        return pd.DataFrame({
            "game_id": [1, 2],
            "home_team_id": [10, 20],
            "away_team_id": [20, 10],
            "game_date": pd.to_datetime(["2015-08-08", "2015-08-15"]),
            "home_score": [1, 0],
            "away_score": [0, 2],
        })

    def events(self, game_id):
        self.event_calls += 1
        return pd.DataFrame({"game_id": [game_id, game_id]})

    def players(self, game_id):
        return pd.DataFrame({
            "game_id": [game_id] * 2,
            "team_id": [10, 20],
            "player_id": [100, 200],
            "player_name": ["Jamie Vardy", "Mesut Ozil"],
            "minutes_played": [90, 90],
        })

    def teams(self, game_id):
        return pd.DataFrame({"team_id": [10, 20], "team_name": ["Leicester City", "Arsenal"]})


def test_fetch_statsbomb_spadl_caches_each_game_and_stacks_season(monkeypatch):
    import soccerhub.readers.statsbomb_spadl as r

    fake = FakeLoader()
    monkeypatch.setattr(r, "_loader", lambda: fake)
    monkeypatch.setattr(r, "_to_spadl", lambda events, home_team_id: events.assign(home=home_team_id))

    m = r.fetch_statsbomb_spadl(2, 27)
    actions = pd.read_parquet(m["actions"].path)
    players = pd.read_parquet(m["players"].path)
    assert set(m) == {"games", "actions", "players"}
    assert len(actions) == 4
    assert sorted(actions.home.unique()) == [10, 20]
    assert set(players.team_name) == {"Leicester City", "Arsenal"}
    assert fake.event_calls == 2

    r.fetch_statsbomb_spadl(2, 27)  # second run: every game is a cache hit
    assert fake.event_calls == 2
