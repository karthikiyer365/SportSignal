import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_fetch_transfermarkt_values_filters_by_competition(monkeypatch):
    import soccerhub.readers.transfermarkt as tm

    fake = pd.DataFrame(
        {
            "player_id": [1, 2, 3],
            "market_value_in_eur": [100, 200, 300],
            "player_club_domestic_competition_id": ["GB1", "ES1", "GB1"],
        }
    )
    monkeypatch.setattr(tm.pd, "read_csv", lambda url: fake)

    m = tm.fetch_transfermarkt_values("GB1")
    assert m.source == "transfermarkt"
    assert m.dataset == "valuations"
    assert m.rows == 2  # only GB1 rows
    assert m.params == {"competition": "GB1"}
    assert set(pd.read_parquet(m.path)["player_id"]) == {1, 3}


def test_fetch_transfermarkt_values_unfiltered(monkeypatch):
    import soccerhub.readers.transfermarkt as tm

    fake = pd.DataFrame(
        {
            "player_id": [1, 2],
            "market_value_in_eur": [100, 200],
            "player_club_domestic_competition_id": ["GB1", "ES1"],
        }
    )
    monkeypatch.setattr(tm.pd, "read_csv", lambda url: fake)

    m = tm.fetch_transfermarkt_values(None)
    assert m.rows == 2  # no competition filter
    assert m.params == {"competition": "ALL"}


def test_fetch_transfermarkt_transfers(monkeypatch):
    import soccerhub.readers.transfermarkt as tm

    fake = pd.DataFrame(
        {
            "player_id": [1, 2],
            "transfer_date": ["2023-07-01", "2024-01-15"],
            "transfer_season": ["23/24", "23/24"],
            "from_club_id": [10, 11],
            "to_club_id": [20, 21],
            "from_club_name": ["A", "B"],
            "to_club_name": ["C", "D"],
            "transfer_fee": [50000000.0, None],
            "market_value_in_eur": [40000000.0, 5000000.0],
            "player_name": ["X", "Y"],
        }
    )
    monkeypatch.setattr(tm.pd, "read_csv", lambda url: fake)

    m = tm.fetch_transfermarkt_transfers()
    assert m.source == "transfermarkt"
    assert m.dataset == "transfers"
    assert m.rows == 2


def test_fetch_transfermarkt_players_filters_and_trims(monkeypatch):
    import soccerhub.readers.transfermarkt as tm

    fake = pd.DataFrame(
        {
            "player_id": [10, 20],
            "name": ["Bukayo Saka", "Vinicius Junior"],
            "date_of_birth": ["2001-09-05", "2000-07-12"],
            "country_of_citizenship": ["England", "Brazil"],
            "position": ["Attack", "Attack"],
            "sub_position": ["Right Winger", "Left Winger"],
            "current_club_id": [11, 418],
            "current_club_name": ["Arsenal FC", "Real Madrid"],
            "current_club_domestic_competition_id": ["GB1", "ES1"],
            "market_value_in_eur": [120000000, 180000000],
            "agent_name": ["x", "y"],  # extra col must be dropped
        }
    )
    monkeypatch.setattr(tm.pd, "read_csv", lambda url: fake)

    m = tm.fetch_transfermarkt_players("GB1")
    assert m.source == "transfermarkt"
    assert m.dataset == "players"
    assert m.rows == 1
    df = pd.read_parquet(m.path)
    assert list(df["name"]) == ["Bukayo Saka"]
    assert "agent_name" not in df.columns
