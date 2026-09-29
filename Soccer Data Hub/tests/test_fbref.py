import json

import pandas as pd
import pytest


def test_season_to_code():
    from soccerhub.readers.fbref import _season_to_code
    assert _season_to_code("2021") == "2122"  # the ambiguous one: NOT 20-21
    assert _season_to_code("2008") == "0809"
    assert _season_to_code("1999") == "9900"


def test_fetch_passes_unambiguous_code(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))
    import soccerhub.readers.fbref as fb

    captured = {}

    class FakeFBref:
        def __init__(self, leagues, seasons, no_cache=False):
            captured["no_cache"] = no_cache
            captured["seasons"] = seasons

        def read_player_season_stats(self, stat_type="standard"):
            captured["stat_type"] = stat_type
            return pd.DataFrame({"x": [1]})

    monkeypatch.setattr("soccerdata.FBref", FakeFBref)
    m = fb.fetch_fbref_season("ENG-Premier League", "2021")
    assert captured["seasons"] == "2122"
    assert captured["stat_type"] == "standard"
    assert m.params["season"] == "2021"  # canonical label unchanged in cache key
    m2 = fb.fetch_fbref_season("ENG-Premier League", "2021", stat_type="misc")
    assert captured["stat_type"] == "misc"
    assert m2.params.get("stat_type") == "misc"  # separate cache key
    assert "stat_type" not in m.params  # legacy standard keys untouched


def test_patch_league_config_writes_serie_a_fix(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERDATA_DIR", str(tmp_path))
    from soccerhub.readers.fbref import _patch_league_config

    _patch_league_config()
    data = json.loads((tmp_path / "config" / "league_dict.json").read_text())
    assert data["ITA-Serie A"]["FBref"] == "Serie A (M)"
    assert data["ITA-Serie A"]["Understat"] == "Serie A"  # full entry, not partial


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_fetch_fbref_season_caches_reader_output(monkeypatch):
    import soccerhub.readers.fbref as fbref

    class FakeFBref:
        def __init__(self, leagues, seasons, no_cache=False):
            self.leagues = leagues
            self.seasons = seasons
            self.no_cache = no_cache

        def read_player_season_stats(self, stat_type="standard"):
            return pd.DataFrame({"player": ["A", "B"], "goals": [3, 1]})

    monkeypatch.setattr("soccerdata.FBref", FakeFBref)

    m = fbref.fetch_fbref_season("ENG-Premier League", "2023")
    assert m.source == "fbref"
    assert m.dataset == "player_season"
    assert m.rows == 2
    assert m.params == {"league": "ENG-Premier League", "season": "2023"}
    assert pd.read_parquet(m.path).shape == (2, 2)


def test_force_reaches_soccerdata_html_cache(tmp_path, monkeypatch):
    """force must bust BOTH cache layers.

    soccerdata keeps its own html on disk. If force stops at soccerhub's parquet
    layer, a "forced" refresh reparses a months-old page and reports success.
    """
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))
    import soccerhub.readers.fbref as fb

    captured = {}

    class FakeFBref:
        def __init__(self, leagues, seasons, no_cache=False):
            captured["no_cache"] = no_cache

        def read_player_season_stats(self, stat_type="standard"):
            return pd.DataFrame({"x": [1]})

    monkeypatch.setattr("soccerdata.FBref", FakeFBref)

    fb.fetch_fbref_season("ENG-Premier League", "2021", force=True)
    assert captured["no_cache"] is True
    fb.fetch_fbref_season("ENG-Premier League", "2022", force=False)
    assert captured["no_cache"] is False
