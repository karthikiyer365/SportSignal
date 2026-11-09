import pandas as pd
from soccerhub.manifest import Manifest, infer_date_range


def test_manifest_roundtrip():
    m = Manifest(
        path="data/fbref/abc.parquet",
        source="fbref",
        dataset="player_season",
        params={"league": "ENG-Premier League", "season": "2023"},
        rows=500,
        cols=30,
        date_range=None,
        fetched_at="2026-07-14T00:00:00+00:00",
    )
    restored = Manifest.from_json(m.to_json())
    assert restored == m


def test_infer_date_range_uses_year_column():
    df = pd.DataFrame({"year": [2019, 2021, 2020], "x": [1, 2, 3]})
    assert infer_date_range(df) == ("2019", "2021")


def test_infer_date_range_none_when_no_date_column():
    df = pd.DataFrame({"x": [1, 2, 3]})
    assert infer_date_range(df) is None
