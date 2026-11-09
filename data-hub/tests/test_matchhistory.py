import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_fetch_match_history_maps_columns_and_url(monkeypatch):
    import soccerhub.readers.matchhistory as mh

    fake = pd.DataFrame({
        "Date": ["16/08/08", "23/08/08"],
        "HomeTeam": ["Arsenal", "Chelsea"],
        "AwayTeam": ["West Brom", None],  # a postponed/void row: must be dropped
        "FTHG": [1, 2], "FTAG": [0, 1], "FTR": ["H", "H"],
        "HTHG": [1, 1], "HTAG": [0, 0], "HTR": ["H", "H"],
        "Referee": ["H Webb", "M Oliver"],
        "HS": [24, 10], "AS": [5, 8], "HST": [14, 4], "AST": [4, 3],
        "HF": [11, 9], "AF": [8, 12], "HC": [7, 3], "AC": [5, 6],
        "HY": [0, 2], "AY": [0, 1], "HR": [0, 0], "AR": [0, 0],
        "B365H": [1.5, 2.1],  # betting odds column: must be dropped
    })
    captured = {}

    def fake_read_csv(url):
        captured["url"] = url
        return fake

    monkeypatch.setattr(mh.pd, "read_csv", fake_read_csv)

    m = mh.fetch_match_history("ENG-Premier League", "2008")
    assert captured["url"] == "https://www.football-data.co.uk/mmz4281/0809/E0.csv"
    assert m.rows == 1  # the null-away-team row was dropped
    df = pd.read_parquet(m.path)
    assert "b365h" not in df.columns.str.lower().tolist()
    assert list(df.columns) == [
        "date", "home_team", "away_team", "home_goals", "away_goals", "result",
        "home_goals_ht", "away_goals_ht", "result_ht", "referee",
        "home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target",
        "home_fouls", "away_fouls", "home_corners", "away_corners",
        "home_yellow", "away_yellow", "home_red", "away_red",
    ]
    assert df.iloc[0]["date"] == "2008-08-16"  # DD/MM/YY -> ISO
    assert df.iloc[0]["home_team"] == "Arsenal"
