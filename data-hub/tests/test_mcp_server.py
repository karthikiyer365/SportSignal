from dataclasses import asdict

from soccerhub.manifest import Manifest


def _fake_manifest(source):
    return Manifest(
        path=f"data/{source}/x.parquet",
        source=source,
        dataset="events",
        params={},
        rows=1,
        cols=1,
        date_range=None,
        fetched_at="2026-07-14T00:00:00+00:00",
    )


def test_fbref_tool_returns_manifest_dict(monkeypatch):
    import soccerhub.mcp_server as server

    monkeypatch.setattr(
        server, "fetch_fbref_season", lambda league, season: _fake_manifest("fbref")
    )
    result = server.fbref_season("ENG-Premier League", "2023")
    assert result == asdict(_fake_manifest("fbref"))
    assert result["source"] == "fbref"


def test_server_registers_tools():
    import soccerhub.mcp_server as server

    for name in ("fbref_season", "statsbomb_events", "transfermarkt_values",
                  "hub_table"):
        assert callable(getattr(server, name))


def test_hub_table_filters_and_truncates(monkeypatch):
    import pandas as pd

    import soccerhub.mcp_server as server

    calls = {}

    def fake_read_hub(table, select="*", **eq):
        calls["table"], calls["eq"] = table, eq
        return pd.DataFrame({"a": [1, 2, 3]})

    monkeypatch.setattr(server, "read_hub", fake_read_hub)
    out = server.hub_table("player_season", league="ITA-Serie A", max_rows=2)
    assert calls == {"table": "player_season", "eq": {"league": "ITA-Serie A"}}
    assert out == [{"a": 1}, {"a": 2}]
