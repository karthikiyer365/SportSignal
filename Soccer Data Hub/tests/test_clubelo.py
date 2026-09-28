import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_fetch_club_elo_snapshot_renames_and_tags_date(monkeypatch):
    import soccerhub.readers.clubelo as ce

    fake = pd.DataFrame(
        {"rank": [1.0], "country": ["ENG"], "level": [1], "elo": [2077.3],
         "from": [pd.Timestamp("2023-06-11")], "to": [pd.Timestamp("2023-08-11")],
         "league": ["ENG-Premier League"]},
        index=pd.Index(["Man City"], name="team"),
    )

    class FakeClubElo:
        def __init__(self, no_cache=False):
            captured["no_cache"] = no_cache

        def read_by_date(self, date):
            captured["date"] = date
            return fake

    captured = {}
    monkeypatch.setattr("soccerdata.ClubElo", FakeClubElo)

    m = ce.fetch_club_elo_snapshot("2023-08-11")
    assert captured["date"] == "2023-08-11"
    assert m.params == {"date": "2023-08-11"}
    df = pd.read_parquet(m.path)
    assert "from" not in df.columns and "to" not in df.columns
    assert df.iloc[0]["elo_from"] == "2023-06-11"  # ISO string, JSON-safe for upsert
    assert df.iloc[0]["snapshot_date"] == "2023-08-11"
    assert df.iloc[0]["team"] == "Man City"


def test_fetch_club_elo_snapshot_default_date_is_todays_cache_key(monkeypatch):
    import soccerhub.readers.clubelo as ce

    fake = pd.DataFrame(
        {"rank": [1.0], "country": ["ENG"], "level": [1], "elo": [2000.0],
         "from": [pd.Timestamp("2026-01-01")], "to": [pd.Timestamp("2026-01-08")],
         "league": ["ENG-Premier League"]},
        index=pd.Index(["Arsenal"], name="team"),
    )
    monkeypatch.setattr("soccerdata.ClubElo",
                        lambda no_cache=False: type(
                            "X", (), {"read_by_date": lambda self, d: fake})())

    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    m = ce.fetch_club_elo_snapshot()
    assert m.params == {"date": today}  # resolved eagerly, not a constant "today" key


def test_fetch_club_elo_history_drops_forward_placeholder(monkeypatch):
    import soccerhub.readers.clubelo as ce

    future = (pd.Timestamp.now() + pd.Timedelta(days=40)).strftime("%Y-%m-%d")
    fake = pd.DataFrame({
        "team": ["Arsenal"]*3,
        "rank": [5.0]*3, "country": ["ENG"]*3, "level": [1]*3,
        "elo": [1900.0, 1910.0, 2063.8],
        "from": pd.to_datetime(["2007-05-01", "2024-08-01", future]),
        "to": pd.to_datetime(["2007-05-08", "2024-08-08",
                              (pd.Timestamp.now() + pd.Timedelta(days=160))
                              .strftime("%Y-%m-%d")]),
    }).set_index("from")

    class FakeClubElo:
        def __init__(self, no_cache=False):
            pass

        def read_team_history(self, team):
            return fake

    monkeypatch.setattr("soccerdata.ClubElo", FakeClubElo)
    m = ce.fetch_club_elo_history("Arsenal")
    df = pd.read_parquet(m.path)
    # pre-2008 row and the future placeholder both dropped
    assert list(df["elo"]) == [1910.0]
    assert df.iloc[0]["snapshot_date"] == "2024-08-01"
