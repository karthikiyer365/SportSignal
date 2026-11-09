import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_normalize():
    from soccerhub.pipelines.xref import normalize
    assert normalize("Ángel Di María") == "angel di maria"


def test_score_mononym_no_subset_bonus():
    # single-token TM names ("Alan", "Diego") must not auto-match any
    # longer name containing that token
    from soccerhub.pipelines.xref import _score
    assert _score("alan smith", "alan") < 0.85
    assert _score("angel di maria", "angel di maria hernandez") == 0.95


def test_exact_match_rejects_wrong_birth_year(monkeypatch, tmp_path):
    import soccerhub.pipelines.xref as xr
    from soccerhub.cache import cached_fetch

    fbref = pd.DataFrame(
        {"born": [1982]},
        index=pd.MultiIndex.from_tuples(
            [("ENG-Premier League", "0809", "Blackburn", "Jason Brown")],
            names=["league", "season", "team", "player"],
        ),
    )
    m_fbref = cached_fetch("fbref", "player_season",
                           {"league": "ENG-Premier League", "season": "2008"},
                           lambda: fbref)
    monkeypatch.setattr(xr, "fetch_fbref_season", lambda l, s, force=False: m_fbref)

    # registry homonym born 1996 — exact name hit, wrong person
    tm = pd.DataFrame({
        "player_id": [99],
        "name": ["Jason Brown"],
        "date_of_birth": ["1996-05-05"],
    })
    m_tm = cached_fetch("transfermarkt", "players", {"competition": "ALL"},
                        lambda: tm)
    monkeypatch.setattr(xr, "fetch_transfermarkt_players",
                        lambda c, force=False: m_tm)
    monkeypatch.setattr(xr, "_load_mapping",
                        lambda: pd.DataFrame({"PlayerFBref": [], "UrlTmarkt": []}))

    df = pd.read_parquet(xr.build_player_xref("ENG-Premier League", "2008").path)
    assert df.iloc[0]["method"] == "unmatched"


def test_mapping_duplicate_names_dropped_and_resolved_by_year(monkeypatch, tmp_path):
    import soccerhub.pipelines.xref as xr
    from soccerhub.cache import cached_fetch

    fbref = pd.DataFrame(
        {"born": [1990]},
        index=pd.MultiIndex.from_tuples(
            [("ENG-Premier League", "0809", "Arsenal", "Aaron Ramsey")],
            names=["league", "season", "team", "player"],
        ),
    )
    m_fbref = cached_fetch("fbref", "player_season",
                           {"league": "ENG-Premier League", "season": "2008"},
                           lambda: fbref)
    monkeypatch.setattr(xr, "fetch_fbref_season", lambda l, s, force=False: m_fbref)

    # two Aaron Ramseys in registry; only years tell them apart
    tm = pd.DataFrame({
        "player_id": [1, 2],
        "name": ["Aaron Ramsey", "Aaron Ramsey"],
        "date_of_birth": ["1990-12-26", "2003-01-21"],
    })
    m_tm = cached_fetch("transfermarkt", "players", {"competition": "ALL"},
                        lambda: tm)
    monkeypatch.setattr(xr, "fetch_transfermarkt_players",
                        lambda c, force=False: m_tm)

    # mapping file also has both -> ambiguous name, must be ignored
    mapping = pd.DataFrame({
        "PlayerFBref": ["Aaron Ramsey", "Aaron Ramsey"],
        "UrlTmarkt": ["https://x/spieler/2", "https://x/spieler/1"],
    })
    monkeypatch.setattr(xr, "_load_mapping", lambda: mapping)

    df = pd.read_parquet(xr.build_player_xref("ENG-Premier League", "2008").path)
    row = df.iloc[0]
    assert row["tm_id"] == 1  # the 1990 one, resolved by year-guarded fuzzy
    assert row["method"] == "fuzzy"


def test_manual_override_wins(monkeypatch, tmp_path):
    import soccerhub.pipelines.xref as xr
    from soccerhub.cache import cached_fetch

    fbref = pd.DataFrame(
        {"born": [1987]},
        index=pd.MultiIndex.from_tuples(
            [("ENG-Premier League", "0809", "Barnsley", "Nathan Doyle")],
            names=["league", "season", "team", "player"],
        ),
    )
    m_fbref = cached_fetch("fbref", "player_season",
                           {"league": "ENG-Premier League", "season": "2008"},
                           lambda: fbref)
    monkeypatch.setattr(xr, "fetch_fbref_season", lambda l, s, force=False: m_fbref)

    tm = pd.DataFrame({
        "player_id": [7], "name": ["Nathan Dyer"],
        "date_of_birth": ["1987-11-29"],
    })
    m_tm = cached_fetch("transfermarkt", "players", {"competition": "ALL"},
                        lambda: tm)
    monkeypatch.setattr(xr, "fetch_transfermarkt_players",
                        lambda c, force=False: m_tm)
    monkeypatch.setattr(xr, "_load_mapping",
                        lambda: pd.DataFrame({"PlayerFBref": [], "UrlTmarkt": []}))

    df = pd.read_parquet(xr.build_player_xref("ENG-Premier League", "2008").path)
    assert df.iloc[0]["method"] == "unmatched"  # override blocks Dyer false hit


def test_build_player_xref_ladder(monkeypatch, tmp_path):
    import soccerhub.pipelines.xref as xr
    from soccerhub.cache import cached_fetch

    # fake fbref parquet: 3 players, one team
    fbref = pd.DataFrame(
        {"born": [2001, 1987, 1999]},
        index=pd.MultiIndex.from_tuples(
            [
                ("ENG-Premier League", "2324", "Arsenal", "Bukayo Saka"),
                ("ENG-Premier League", "2324", "Arsenal", "Angel Di Maria"),
                ("ENG-Premier League", "2324", "Arsenal", "Totally Unknown"),
            ],
            names=["league", "season", "team", "player"],
        ),
    )
    m_fbref = cached_fetch(
        "fbref",
        "player_season",
        {"league": "ENG-Premier League", "season": "2023"},
        lambda: fbref,
    )
    monkeypatch.setattr(xr, "fetch_fbref_season", lambda l, s, force=False: m_fbref)

    # fake tm players registry
    tm = pd.DataFrame(
        {
            "player_id": [10, 20],
            "name": ["Bukayo Saka", "Ángel Di María Hernández"],
            "date_of_birth": ["2001-09-05", "1988-02-14"],
        }
    )
    m_tm = cached_fetch("transfermarkt", "players", {"competition": "GB1"}, lambda: tm)
    monkeypatch.setattr(
        xr, "fetch_transfermarkt_players", lambda c, force=False: m_tm
    )

    # fake mapping file: covers Saka only
    mapping = pd.DataFrame(
        {
            "PlayerFBref": ["Bukayo Saka"],
            "UrlTmarkt": [
                "https://www.transfermarkt.com/bukayo-saka/profil/spieler/10"
            ],
        }
    )
    monkeypatch.setattr(xr, "_load_mapping", lambda: mapping)

    m = xr.build_player_xref("ENG-Premier League", "2023")
    df = pd.read_parquet(m.path).set_index("fbref_name")

    assert df.loc["Bukayo Saka", "method"] == "mapping_file"
    assert df.loc["Bukayo Saka", "tm_id"] == 10
    assert df.loc["Angel Di Maria", "method"] == "fuzzy"
    assert df.loc["Angel Di Maria", "tm_id"] == 20
    assert df.loc["Totally Unknown", "method"] == "unmatched"
    assert pd.isna(df.loc["Totally Unknown", "tm_id"])
