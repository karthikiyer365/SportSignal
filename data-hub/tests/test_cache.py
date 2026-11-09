import pandas as pd
import pytest

from soccerhub.cache import cache_key, cached_fetch, cache_hit
from soccerhub.errors import SoccerhubError


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_cache_key_is_stable_and_order_independent():
    a = cache_key("fbref", "player_season", {"league": "ENG", "season": "2023"})
    b = cache_key("fbref", "player_season", {"season": "2023", "league": "ENG"})
    assert a == b
    assert a != cache_key("fbref", "player_season", {"league": "ESP", "season": "2023"})


def test_cached_fetch_writes_then_hits_cache():
    calls = {"n": 0}

    def produce():
        calls["n"] += 1
        return pd.DataFrame({"year": [2020, 2021], "x": [1, 2]})

    params = {"league": "ENG", "season": "2023"}
    m1 = cached_fetch("fbref", "player_season", params, produce)
    assert calls["n"] == 1
    assert m1.rows == 2 and m1.cols == 2
    assert m1.date_range == ("2020", "2021")
    assert cache_hit("fbref", cache_key("fbref", "player_season", params))

    # second call is a cache hit — produce must NOT run again
    m2 = cached_fetch("fbref", "player_season", params, produce)
    assert calls["n"] == 1
    assert m2 == m1

    # force bypasses the cache
    cached_fetch("fbref", "player_season", params, produce, force=True)
    assert calls["n"] == 2


def test_cached_fetch_wraps_errors_and_writes_no_manifest():
    def produce():
        raise ValueError("boom")

    params = {"league": "ENG", "season": "2023"}
    with pytest.raises(SoccerhubError):
        cached_fetch("fbref", "player_season", params, produce)
    assert not cache_hit("fbref", cache_key("fbref", "player_season", params))
