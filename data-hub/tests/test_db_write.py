import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_push_to_supabase_upserts_records(monkeypatch, tmp_path):
    import soccerhub.db.write as sp
    from soccerhub.cache import cached_fetch

    df = pd.DataFrame({
        "league": ["ENG-Premier League"], "season": ["2023"],
        "team": ["Arsenal"], "player_name": ["Bukayo Saka"],
        "goals": [14], "market_value_in_eur": [pd.NA],
    })
    m = cached_fetch("hub", "player_season",
                     {"league": "ENG-Premier League", "season": "2023"},
                     lambda: df)

    calls = {}

    class FakeTable:
        def upsert(self, records, on_conflict):
            calls["records"] = records
            calls["on_conflict"] = on_conflict
            return self

        def execute(self):
            return None

    class FakeClient:
        def table(self, name):
            calls["table"] = name
            return FakeTable()

    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    monkeypatch.setattr(sp, "create_client", lambda url, key: FakeClient())

    n = sp.push_to_supabase(m, "player_season")
    assert n == 1
    assert calls["table"] == "player_season"
    assert calls["on_conflict"] == "league,season,team,player_name"
    assert calls["records"][0]["goals"] == 14
    assert calls["records"][0]["market_value_in_eur"] is None  # NaN -> None
