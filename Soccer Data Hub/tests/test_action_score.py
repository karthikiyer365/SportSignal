import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def _game_actions(game_id, home, away, n=120):
    """Synthetic but valid SPADL game: possession flips every 6 actions,
    every possession ends in a shot, every 3rd shot is a goal (alternating teams)."""
    import socceraction.spadl as spadl
    import socceraction.spadl.config as cfg

    i = np.arange(n)
    team = np.where(i // 6 % 2 == 0, home, away)
    shot, pas = cfg.actiontypes.index("shot"), cfg.actiontypes.index("pass")
    ok, fail = cfg.results.index("success"), cfg.results.index("fail")
    rng = np.random.default_rng(game_id)
    return spadl.add_names(pd.DataFrame({
        "game_id": game_id,
        "original_event_id": [f"{game_id}-{k}" for k in i],  # non-null: VAEP features fillna on it
        "action_id": i,
        "period_id": np.where(i < n // 2, 1, 2),
        "time_seconds": (i % (n // 2)) * 20.0,
        "team_id": team,
        "player_id": team * 10 + i % 3,
        "start_x": rng.uniform(-1, 106, n),  # a few off-pitch coords on purpose
        "start_y": rng.uniform(-1, 69, n),
        "end_x": rng.uniform(0, 105, n),
        "end_y": rng.uniform(0, 68, n),
        "bodypart_id": cfg.bodyparts.index("foot"),
        "type_id": np.where(i % 6 == 5, shot, pas),
        "result_id": np.where(i % 18 == 5, ok, fail),
    }))


@pytest.fixture
def season():
    games = pd.DataFrame({
        "game_id": [1, 2, 3, 4],
        "home_team_id": [10, 20, 10, 20],
        "away_team_id": [20, 10, 20, 10],
        "game_date": pd.to_datetime(["2015-08-08", "2015-08-15", "2015-08-22", "2015-08-29"]),
        "home_score": [2, 1, 0, 1],
        "away_score": [1, 1, 0, 3],
    })
    actions = pd.concat(
        [_game_actions(g.game_id, g.home_team_id, g.away_team_id) for g in games.itertuples()],
        ignore_index=True,
    )
    rows = []
    for gid in games.game_id:
        for team, name in ((10, "Leicester City"), (20, "Arsenal")):
            for k in range(3):
                rows.append({"game_id": gid, "team_id": team, "team_name": name,
                             "player_id": team * 10 + k, "player_name": f"{name} {k}",
                             "minutes_played": 90})
        rows.append({"game_id": gid, "team_id": 10, "team_name": "Leicester City",
                     "player_id": 103, "player_name": "Unused Sub", "minutes_played": 0})
    return games, actions, pd.DataFrame(rows)


def test_split_by_game_alternates_by_date_and_never_overlaps():
    from soccerhub.pipelines.action_score import split_by_game

    games = pd.DataFrame({
        "game_id": [7, 3, 9, 1],
        "game_date": pd.to_datetime(["2015-09-01", "2015-08-01", "2015-10-01", "2015-08-01"]),
    })
    assert split_by_game(games).to_dict() == {1: 0, 3: 1, 7: 0, 9: 1}


def test_attack_left_to_right_flips_only_the_away_team():
    """Raw SPADL: home attacks towards x=105, away towards x=0.
    The same raw spot is the home team's attacking right but the away team's own left."""
    from soccerhub.pipelines.action_score import attack_left_to_right

    games = pd.DataFrame({"game_id": [1], "home_team_id": [10]})
    raw = pd.DataFrame({
        "game_id": [1, 1], "team_id": [10, 20],
        "start_x": [100.0, 100.0], "start_y": [5.0, 5.0],
        "end_x": [104.0, 104.0], "end_y": [6.0, 6.0],
    })
    z = attack_left_to_right(raw, games)
    assert z.start_x.tolist() == [100.0, 5.0]  # away coords now from its own attacking view
    assert z.start_y.tolist() == [5.0, 63.0]   # its right flank (low y) becomes its left


def test_zone_summary_is_a_6_by_5_grid_with_its_own_geometry():
    """6 bands of 17.5 m x 5 lanes cut at the box and six-yard-box edges; off-pitch coords still land."""
    from soccerhub.pipelines.action_score import zone_summary

    rated = pd.DataFrame({"team_id": 10, "vaep_value": [0.1, 0.2, 0.3, 0.4],
                          "start_x": [0.0, 104.9, 52.0, 106.0], "start_y": [0.0, 67.9, 34.0, -1.0]})
    z = zone_summary(rated).set_index("zone")
    assert set(z.index) == {"0-right-wing", "5-left-wing", "2-centre", "5-right-wing"}
    assert z.loc["0-right-wing", ["x0", "x1", "y0", "y1"]].tolist() == [0.0, 17.5, 0.0, 13.84]
    assert z.loc["2-centre", ["x0", "x1", "y0", "y1"]].tolist() == [35.0, 52.5, 24.84, 43.16]
    assert z.loc["5-right-wing", "n_actions"] == 1


def test_rating_zones_and_player_table(season):
    from soccerhub.pipelines import action_score as a

    games, actions, players = season
    rated = a.attack_left_to_right(a.rate_out_of_fold(games, actions), games)

    assert len(rated) == len(actions)
    assert rated.groupby("game_id").fold.nunique().eq(1).all()
    assert rated[["offensive_value", "defensive_value", "vaep_value"]].notna().all().all()
    assert rated.p_scores.between(0, 1).all()

    table = a.player_table(rated, players).set_index("player_id")
    assert table.loc[100, "minutes"] == 360
    assert table.loc[100, "vaep_per90"] == pytest.approx(table.loc[100, "vaep_total"] / 360 * 90)
    assert np.isnan(table.loc[103, "vaep_per90"])  # 0 minutes -> no rate, never inf


def test_validation_and_site_export(season, tmp_path):
    from soccerhub.pipelines import action_score as a

    games, actions, players = season
    rated = a.attack_left_to_right(a.rate_out_of_fold(games, actions), games)
    table = a.player_table(rated, players)

    report = a.validate(rated, games, players)
    assert {"auc_scores", "brier_scores", "auc_concedes", "calibration_max_gap",
            "team_spearman", "team_table", "reliability_spearman", "reliability_n"} <= report.keys()
    assert 0 <= report["auc_scores"] <= 1
    assert report["reliability_n"] == 0  # 2 games per fold = 180 min, nobody reaches 450
    assert np.isnan(report["reliability_spearman"])

    sizes = a.export_action_score_site(games, players, rated, table, tmp_path)
    assert set(sizes) == {"players", "zones", "games", "player_actions"}

    # every action of the season, one compact file per player
    files = sorted((tmp_path / "player_actions").glob("*.json"))
    assert [f.name for f in files] == ["100.json", "101.json", "102.json", "200.json", "201.json", "202.json"]
    assert sizes["player_actions"] == sum(f.stat().st_size for f in files)
    vardy = json.loads((tmp_path / "player_actions" / "100.json").read_text())
    n = (rated.player_id == 100).sum()
    assert {k: len(vardy[k]) for k in ("g", "m", "t", "r", "x0", "y0", "x1", "y1", "v")} == dict.fromkeys(
        ("g", "m", "t", "r", "x0", "y0", "x1", "y1", "v"), n)
    assert sorted({vardy["types"][t] for t in vardy["t"]}) == sorted(rated[rated.player_id == 100].type_name.unique())
    assert {1, 46} <= set(vardy["m"])  # football minutes: kick-off 1', second half 46'
    assert sum(vardy["v"]) == pytest.approx(rated[rated.player_id == 100].vaep_value.sum(), abs=0.01)

    played = json.loads((tmp_path / "games.json").read_text())
    assert len(played) == 4
    assert played[0] == {"game_id": 1, "game_date": "2015-08-08",
                         "home_team": "Leicester City", "away_team": "Arsenal",
                         "home_score": 2, "away_score": 1}  # scores let the page build the league table

    zones = json.loads((tmp_path / "zones.json").read_text())
    assert len(zones) <= 2 * 30 and {"zone", "x0", "x1", "y0", "y1"} <= zones[0].keys()
    first = json.loads((tmp_path / "players.json").read_text())[0]
    assert {"player_name", "team_name", "minutes", "vaep_per90"} <= first.keys()


def test_rating_is_reproducible(season):
    """Published rankings must not shift between re-runs."""
    from soccerhub.pipelines.action_score import rate_out_of_fold

    games, actions, _ = season
    first = rate_out_of_fold(games, actions).vaep_value
    second = rate_out_of_fold(games, actions).vaep_value
    pd.testing.assert_series_equal(first, second)


def test_force_rerates_without_refetching_games(season, monkeypatch):
    """force re-runs the model only; the 380-game download stays cached."""
    from soccerhub.manifest import Manifest
    from soccerhub.pipelines import action_score as a

    games, actions, players = season
    paths = {}
    for name, df in {"games": games, "actions": actions, "players": players}.items():
        path = Path(os.environ["SOCCERHUB_CACHE"]) / f"{name}.parquet"
        df.to_parquet(path)
        paths[name] = Manifest(str(path), "fake", name, {}, len(df), len(df.columns), None, "")
    fetch_force, rated = [], []
    monkeypatch.setattr(a, "fetch_statsbomb_spadl",
                        lambda c, s, refetch=False: fetch_force.append(refetch) or paths)
    real_rate = a.rate_out_of_fold
    monkeypatch.setattr(a, "rate_out_of_fold", lambda *x, **k: rated.append(1) or real_rate(*x, **k))

    a.build_action_score(force=False)
    a.build_action_score(force=True)
    assert fetch_force == [False, False]
    assert len(rated) == 2


def test_each_league_season_exports_to_its_own_folder():
    """9 league-seasons (4 StatsBomb 2015/16 + 5 Wyscout 2017/18) never overwrite each other."""
    from soccerhub.pipelines.action_score import LEAGUE_SEASONS, site_dir

    dirs = {site_dir(league, season) for league, season in LEAGUE_SEASONS}
    assert len(dirs) == 9
    assert site_dir("GER-Bundesliga", "2017").name == "ger-bundesliga-2017"
    assert {p for p, _, _ in LEAGUE_SEASONS.values()} == {"statsbomb", "wyscout"}


def test_upload_player_actions_puts_every_file_in_the_bucket(tmp_path, monkeypatch):
    """Upload keeps the league folder in the object path and overwrites on re-run."""
    from soccerhub.pipelines import action_score as a

    league = tmp_path / "eng-premier-league-2015"
    (league / "player_actions").mkdir(parents=True)
    for pid in (100, 200):
        (league / "player_actions" / f"{pid}.json").write_text("{}")
    sent = []

    class Bucket:
        def upload(self, path, file, file_options):
            sent.append((path, file_options["upsert"], file_options["content-type"]))

    class Storage:
        def from_(self, name):
            assert name == "action-score"
            return Bucket()

    monkeypatch.setattr(a, "_storage", lambda: Storage())
    assert a.upload_player_actions(league) == 2
    assert sorted(sent) == [
        ("eng-premier-league-2015/player_actions/100.json", "true", "application/json"),
        ("eng-premier-league-2015/player_actions/200.json", "true", "application/json"),
    ]


def test_unknown_player_placeholder_is_not_a_player(season):
    """Wyscout files unattributed actions under player_id 0: they count for the team, not as a player."""
    from soccerhub.pipelines.action_score import attack_left_to_right, player_table, rate_out_of_fold

    games, actions, players = season
    actions = actions.copy()
    actions.loc[actions.index[:5], "player_id"] = 0
    players = pd.concat([players, pd.DataFrame([{"game_id": 1, "team_id": 10, "team_name": "Leicester City",
                                                 "player_id": 0, "player_name": None, "minutes_played": 7}])])
    rated = attack_left_to_right(rate_out_of_fold(games, actions), games)
    assert 0 not in set(player_table(rated, players).player_id)


def test_cli_filter_means_league_and_season():
    """`action_score "ENG-Premier League" 2015` must pick exactly one league-season, not either."""
    from soccerhub.pipelines.action_score import selected

    assert selected(["ENG-Premier League", "2015"]) == [("ENG-Premier League", "2015")]
    assert len(selected(["2017"])) == 5
    assert selected(["ESP-La Liga"]) == [("ESP-La Liga", "2015"), ("ESP-La Liga", "2017")]
    assert len(selected([])) == 9


def test_upload_retries_a_dropped_connection(tmp_path, monkeypatch):
    """One TLS blip must not kill a 4,800-file upload."""
    from soccerhub.pipelines import action_score as a

    league = tmp_path / "eng-premier-league-2015"
    (league / "player_actions").mkdir(parents=True)
    (league / "player_actions" / "100.json").write_text("{}")
    calls = []

    class Bucket:
        def upload(self, path, file, file_options):
            calls.append(path)
            if len(calls) == 1:
                raise ConnectionError("ssl/tls alert bad record mac")

    class Storage:
        def from_(self, name):
            return Bucket()

    monkeypatch.setattr(a, "_storage", lambda: Storage())
    monkeypatch.setattr(a.time, "sleep", lambda s: None)
    assert a.upload_player_actions(league) == 1
    assert len(calls) == 2
