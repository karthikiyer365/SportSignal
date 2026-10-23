import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_fotmob_season_label():
    from soccerhub.readers.fotmob import fotmob_season

    assert fotmob_season("2021") == "2021/2022"
    assert fotmob_season("2026") == "2026/2027"


def test_fetch_match_uses_cache(monkeypatch):
    import soccerhub.readers.fotmob as fm

    calls, archived = [], []
    monkeypatch.setattr(fm, "_get_json", lambda url: calls.append(url) or {"general": {"matchId": "1"}})
    monkeypatch.setattr(fm, "_archive", lambda *a: archived.append(a))
    assert fm.fetch_match(1, "2024", "IND-Indian Super League") == {"general": {"matchId": "1"}}
    assert fm.fetch_match(1, "2024", "IND-Indian Super League") == {"general": {"matchId": "1"}}
    assert len(calls) == 1
    assert len(archived) == 1 and archived[0][:2] == (1, "2024")  # only fresh downloads are archived


def test_finished_match_ids_skips_unplayed_and_cancelled():
    from soccerhub.readers.fotmob import finished_match_ids

    payload = {"fixtures": {"allMatches": [
        {"id": "10", "status": {"finished": True}},
        {"id": "11", "status": {"finished": False}},
        {"id": "12", "status": {"finished": True, "cancelled": True}},
    ]}}
    assert finished_match_ids(payload) == [10]


def test_fetch_league_uses_league_id(monkeypatch):
    import soccerhub.readers.fotmob as fm

    urls = []
    monkeypatch.setattr(fm, "_get_json", lambda u: urls.append(u) or {})
    fm.fetch_league("ENG-Premier League", "2024")
    assert "id=47" in urls[0] and "season=2024%2F2025" in urls[0]


def test_archive_path_uses_league_slug(monkeypatch):
    import soccerhub.readers.fotmob as fm

    paths = []
    monkeypatch.setattr(fm, "_get_json", lambda u: {"general": {}})
    monkeypatch.setattr(fm, "_archive",
                        lambda mid, season, gz, slug: paths.append(f"{slug}/{season}/{mid}"))
    fm.fetch_match(1, "2024", "ENG-Premier League")
    fm.fetch_match(2, "2024", "IND-Indian Super League")
    assert paths == ["eng/2024/1", "isl/2024/2"]
