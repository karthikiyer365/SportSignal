import json
import os
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


class FakeLoader:
    def __init__(self):
        self.event_calls = 0

    def games(self, competition_id, season_id):
        assert (competition_id, season_id) == (364, 181150)
        return pd.DataFrame({
            "game_id": [2500089, 2500090],
            "home_team_id": [1646, 1659],
            "away_team_id": [1659, 1646],
            "game_date": pd.to_datetime(["2017-08-12", "2017-08-19"]),
        })

    def events(self, game_id):
        self.event_calls += 1
        return pd.DataFrame({"game_id": [game_id, game_id, game_id]})

    def players(self, game_id):
        return pd.DataFrame({"game_id": [game_id] * 2, "team_id": [1646, 1659],
                             "player_id": [1, 2], "player_name": ["A", "B"], "minutes_played": [90, 90]})

    def teams(self, game_id):
        return pd.DataFrame({"team_id": [1646, 1659], "team_name": ["Burnley", "FC Bayern M\\u00fcnchen"]})


def test_fetch_wyscout_spadl_adds_scores_and_caches_each_game(monkeypatch):
    import soccerhub.readers.wyscout_spadl as r

    # scores only exist in Wyscout's raw matches file, keyed by team id
    root = Path(os.environ["SOCCERHUB_CACHE"]) / "wyscout_public"
    root.mkdir(parents=True)
    (root / "matches_England.json").write_text(json.dumps([
        {"wyId": 2500089, "teamsData": {"1646": {"side": "home", "score": 1}, "1659": {"side": "away", "score": 2}}},
        {"wyId": 2500090, "teamsData": {"1659": {"side": "home", "score": 0}, "1646": {"side": "away", "score": 0}}},
    ]))
    fake = FakeLoader()
    monkeypatch.setattr(r, "_loader", lambda: fake)
    monkeypatch.setattr(r, "_to_spadl", lambda events, home_team_id: events.assign(home=home_team_id))

    m = r.fetch_wyscout_spadl(364, 181150)
    games = pd.read_parquet(m["games"].path).set_index("game_id")
    assert games.loc[2500089, ["home_score", "away_score"]].tolist() == [1, 2]
    assert games.loc[2500090, ["home_score", "away_score"]].tolist() == [0, 0]
    assert len(pd.read_parquet(m["actions"].path)) == 6
    # Wyscout stores some accents as literal "\\u00fc" text; names must come out decoded
    assert set(pd.read_parquet(m["players"].path).team_name) == {"Burnley", "FC Bayern München"}

    r.fetch_wyscout_spadl(364, 181150)  # second run: every game is a cache hit
    assert fake.event_calls == 2
