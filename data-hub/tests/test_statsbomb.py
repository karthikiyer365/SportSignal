import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_fetch_statsbomb_events_converts_dataset_to_df(monkeypatch):
    import soccerhub.readers.statsbomb as sb

    class FakeDataset:
        def to_df(self):
            return pd.DataFrame({"event_type": ["pass", "shot"], "minute": [1, 2]})

    def fake_load_open_data(match_id):
        assert match_id == "3788741"
        return FakeDataset()

    monkeypatch.setattr("kloppy.statsbomb.load_open_data", fake_load_open_data)

    m = sb.fetch_statsbomb_events("3788741")
    assert m.source == "statsbomb"
    assert m.dataset == "events"
    assert m.rows == 2
    assert m.params == {"match_id": "3788741"}
    assert pd.read_parquet(m.path).shape == (2, 2)
