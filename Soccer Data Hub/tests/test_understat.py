import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def _us(rows):
    return pd.DataFrame(rows, columns=["player", "team", "minutes", "xg", "np_xg",
                                       "xa", "xg_chain", "xg_buildup", "shots",
                                       "key_passes", "player_id"])


def _hub(rows):
    return pd.DataFrame(rows, columns=["league", "season", "team",
                                       "player_name", "minutes"])


def test_match_players_ladder():
    from soccerhub.pipelines.understat import match_players

    us = _us([
        # rung 1: unique name, spelling identical
        ["Bukayo Saka", "Arsenal", 2900, 12.1, 9.3, 8.0, 20.0, 5.0, 90, 60, 7322],
        # rung 2: mover — two stints, must pair by minutes
        ["Cole Palmer", "Manchester City", 300, 1.0, 1.0, 0.5, 2.0, 1.0, 10, 5, 111],
        ["Cole Palmer", "Chelsea", 2500, 20.0, 16.0, 10.0, 30.0, 4.0, 100, 70, 111],
        # rung 3: accent drift (fbref has the accent, understat doesn't)
        ["Martin Odegaard", "Arsenal", 2700, 8.0, 8.0, 7.5, 25.0, 8.0, 70, 80, 6055],
        # no counterpart in hub: must stay unmatched
        ["Ghost Player", "Nowhere FC", 900, 1.0, 1.0, 0.0, 1.0, 0.0, 5, 2, 999],
    ])
    hub = _hub([
        ["ENG-Premier League", "2023", "Arsenal", "Bukayo Saka", 2919],
        ["ENG-Premier League", "2023", "Manchester City", "Cole Palmer", 250],
        ["ENG-Premier League", "2023", "Chelsea", "Cole Palmer", 2450],
        ["ENG-Premier League", "2023", "Arsenal", "Martin Ødegaard", 2650],
        ["ENG-Premier League", "2023", "Burnley", "Unrelated Person", 900],
    ])
    out = match_players(us, hub).set_index("player_name")

    assert out.loc["Bukayo Saka", "understat_id"] == 7322
    # mover stints attached to the right clubs
    assert out.loc["Cole Palmer"].set_index("team").loc["Chelsea", "xg"] == 20.0
    assert out.loc["Cole Palmer"].set_index("team").loc["Manchester City", "xg"] == 1.0
    # accent drift caught by fuzzy rung
    assert out.loc["Martin Ødegaard", "understat_id"] == 6055
    # ghost row didn't invent a match
    assert "Unrelated Person" not in out.index
    assert len(out) == 4


def test_match_players_minutes_guard_blocks_wrong_fuzzy():
    from soccerhub.pipelines.understat import match_players

    # near-identical names but wildly different minutes: must NOT match
    us = _us([["Joao Silva", "Porto B", 2800, 5, 5, 2, 8, 2, 40, 20, 1]])
    hub = _hub([["ESP-La Liga", "2023", "Sevilla", "Joao Silvo", 400]])
    assert len(match_players(us, hub)) == 0


def test_push_team_match_keys_and_season_label(monkeypatch, tmp_path):
    import soccerhub.pipelines.understat as un
    from soccerhub.manifest import Manifest

    df = pd.DataFrame({
        "game_id": [22275], "date": [pd.Timestamp("2023-08-11 19:00:00")],
        "home_team": ["Burnley"], "away_team": ["Manchester City"],
        "home_goals": [0], "away_goals": [3], "home_xg": [0.3], "away_xg": [2.5],
        "home_np_xg": [0.3], "away_np_xg": [2.5],
        "home_expected_points": [0.2], "away_expected_points": [2.7],
        "home_ppda": [12.0], "away_ppda": [8.0],
        "home_deep_completions": [2], "away_deep_completions": [14],
        "league": ["ENG-Premier League"], "season": ["2324"],  # understat code
    })
    p = tmp_path / "tm.parquet"
    df.to_parquet(p)
    m = Manifest(path=str(p), source="understat", dataset="team_match",
                 params={}, rows=1, cols=18, date_range=None, fetched_at="t")
    monkeypatch.setattr(un, "fetch_understat",
                        lambda l, s, d, force=False: m)

    captured = {}

    def fake_upsert(df, table, on_conflict):
        captured["df"], captured["table"], captured["key"] = df, table, on_conflict
        return len(df)

    import soccerhub.pipelines.supa as sp
    monkeypatch.setattr(sp, "upsert_df", fake_upsert)

    assert un.push_team_match("ENG-Premier League", "2023") == 1
    row = captured["df"].iloc[0]
    assert captured["table"] == "team_match_understat"
    assert captured["key"] == "league,season,game_id"
    assert row["season"] == "2023"      # canonical, not understat's '2324'
    assert row["date"] == "2023-08-11"  # date only, ISO
    assert un.push_team_match("ENG-Premier League", "2010") == 0  # pre-2014


def test_push_shots_keys_and_rounding(monkeypatch, tmp_path):
    import soccerhub.pipelines.understat as un
    from soccerhub.manifest import Manifest

    df = pd.DataFrame({
        "shot_id": [552237], "game_id": [22275],
        "date": [pd.Timestamp("2023-08-11 19:00:00")],
        "team": ["Burnley"], "player": ["Anass Zaroury"], "player_id": [11703],
        "assist_player": ["Lyle Foster"], "assist_player_id": [10408],
        "xg": [0.0639837458729744], "location_x": [0.817], "location_y": [0.536],
        "minute": [79], "body_part": ["Left Foot"], "situation": ["Open Play"],
        "result": ["Blocked Shot"],
    })
    p = tmp_path / "sh.parquet"
    df.to_parquet(p)
    m = Manifest(path=str(p), source="understat", dataset="shots",
                 params={}, rows=1, cols=15, date_range=None, fetched_at="t")
    monkeypatch.setattr(un, "fetch_understat", lambda l, s, d, force=False: m)

    captured = {}

    def fake_upsert(df, table, on_conflict):
        captured["df"], captured["table"], captured["key"] = df, table, on_conflict
        return len(df)

    import soccerhub.pipelines.supa as sp
    monkeypatch.setattr(sp, "upsert_df", fake_upsert)

    assert un.push_shots("ENG-Premier League", "2023") == 1
    row = captured["df"].iloc[0]
    assert captured["table"] == "shots_understat"
    assert captured["key"] == "league,season,shot_id"
    assert row["xg"] == 0.064
    assert row["season"] == "2023"


def test_fetch_understat_rejects_unknown_dataset():
    from soccerhub.readers.understat import fetch_understat
    with pytest.raises(ValueError):
        fetch_understat("ENG-Premier League", "2023", "keeper")


def test_match_players_single_token_short_names():
    """Spanish short names: Understat's 'Remiro' is FBref's 'Álex Remiro'.

    xref's scorer rejects single-token subsets (global-registry safety); in a
    one-league pool behind a minutes guard they are the honest common case.
    """
    from soccerhub.pipelines.understat import match_players

    us = _us([
        ["Remiro", "Real Sociedad", 3275, 0, 0, 0.1, 2, 2, 1, 2, 2555],
        ["Raíllo", "Mallorca", 2200, 2.0, 2.0, 0.5, 5, 3, 12, 6, 2584],
        ["Djené Dakonam", "Getafe", 2580, 0.5, 0.5, 0.2, 3, 2, 6, 3, 6151],
    ])
    hub = _hub([
        ["ESP-La Liga", "2023", "Real Sociedad", "Álex Remiro", 3275],
        ["ESP-La Liga", "2023", "Mallorca", "Antonio Raillo", 2200],
        ["ESP-La Liga", "2023", "Getafe", "Djené", 2580],  # subset reversed
    ])
    out = match_players(us, hub).set_index("player_name")
    assert out.loc["Álex Remiro", "understat_id"] == 2555
    assert out.loc["Antonio Raillo", "understat_id"] == 2584   # + accent drift
    assert out.loc["Djené", "understat_id"] == 6151


def test_match_players_rejects_ambiguous_short_name():
    """Two players who both fit the short name = no match, not a coin flip."""
    from soccerhub.pipelines.understat import match_players

    us = _us([["Gabriel", "Atletico Madrid", 1800, 1, 1, 1, 4, 2, 9, 4, 777]])
    hub = _hub([
        ["ESP-La Liga", "2023", "Atletico Madrid", "Gabriel Paulista", 1800],
        ["ESP-La Liga", "2023", "Atletico Madrid", "Gabriel Martinelli", 1750],
    ])
    assert len(match_players(us, hub)) == 0


def test_match_players_rung2_rejects_minutes_tie():
    from soccerhub.pipelines.understat import match_players

    # two source "Gabriel"s equally far (50 min) from the one hub "Gabriel": unknowable, no guess
    us = _us([["Gabriel", "Arsenal", 1000, 1, 1, 0, 1, 0, 5, 2, 1],
              ["Gabriel", "Brighton", 1100, 1, 1, 0, 1, 0, 5, 2, 2]])
    hub = _hub([["ENG-Premier League", "2024", "Arsenal", "Gabriel", 1050]])
    assert len(match_players(us, hub)) == 0


def test_match_players_rung1_respects_minutes_guard():
    from soccerhub.pipelines.understat import match_players

    us = _us([["Gabriel", "Brentford", 120, 0, 0, 0, 0, 0, 1, 0, 9]])
    hub = _hub([["ENG-Premier League", "2024", "Arsenal", "Gabriel", 2800]])
    assert len(match_players(us, hub)) == 0
