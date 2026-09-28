import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


_IDX = pd.MultiIndex.from_tuples(
    [("ENG-Premier League", "2324", "Arsenal", "Bukayo Saka"),
     ("ENG-Premier League", "2324", "Arsenal", "Totally Unknown")],
    names=["league", "season", "team", "player"],
)


def _fake_fbref():
    cols = pd.MultiIndex.from_tuples([
        ("nation", ""), ("pos", ""), ("age", ""), ("born", ""),
        ("Playing Time", "MP"), ("Playing Time", "Min"), ("Playing Time", "90s"),
        ("Performance", "Gls"), ("Performance", "Ast"),
    ])
    return pd.DataFrame(
        [["ENG", "FW", 21, 2001, 38, 3300, 36.7, 14, 9],
         ["ENG", "GK", 30, 1993, 10, 900, 10.0, 0, 0]],
        index=_IDX, columns=cols,
    )


def _fake_misc():
    cols = pd.MultiIndex.from_tuples([
        ("born", ""), ("Performance", "TklW"), ("Performance", "Int"),
        ("Performance", "Fls"), ("Performance", "Crs"),  # Crs must be dropped
    ])
    return pd.DataFrame(
        [[2001, 30, 25, 12, 99],
         [1993, 1, 0, 2, 0]],
        index=_IDX, columns=cols,
    )


def _fake_keeper():
    cols = pd.MultiIndex.from_tuples([
        ("born", ""), ("Performance", "GA"), ("Performance", "SoTA"),
        ("Performance", "Saves"), ("Performance", "Save%"),
        ("Performance", "CS"), ("Performance", "CS%"),
        ("Penalty Kicks", "Save%"),  # colliding name — canon selection drops it
    ])
    return pd.DataFrame(
        [[1993, 30, 100, 71, 70.9, 8, 21.1, 25.0]],
        index=_IDX[1:], columns=cols,
    )


def test_flatten_drops_nameless_rows():
    from soccerhub.pipelines.player_season import flatten_fbref
    df = _fake_fbref()
    idx = df.index.to_frame()
    idx.iloc[0, idx.columns.get_loc("player")] = None
    df.index = pd.MultiIndex.from_frame(idx)
    flat = flatten_fbref(df)
    assert flat.player_name.notna().all()
    assert len(flat) == len(df) - 1


def test_flatten_fbref_canonical_names():
    from soccerhub.pipelines.player_season import flatten_fbref
    flat = flatten_fbref(_fake_fbref())
    assert {"player_name", "goals", "assists", "matches_played", "minutes",
            "nationality", "position", "birth_year"} <= set(flat.columns)
    assert flat.loc[flat.player_name == "Bukayo Saka", "goals"].iloc[0] == 14


def test_season_end():
    from soccerhub.pipelines.player_season import season_end
    assert season_end("2023") == "2024-06-30"


def test_same_name_same_team_disambiguated(monkeypatch):
    import soccerhub.pipelines.player_season as ps
    from soccerhub.cache import cached_fetch

    cols = pd.MultiIndex.from_tuples([
        ("nation", ""), ("pos", ""), ("age", ""), ("born", ""),
        ("Playing Time", "MP"), ("Playing Time", "Min"),
        ("Performance", "Gls"), ("Performance", "Ast"),
    ])
    idx = pd.MultiIndex.from_tuples(
        [("ESP-La Liga", "0910", "Barcelona", "Lionel Messi"),  # non-dup row:
         # disambiguation must align dup-only aggregates with the full frame
         ("ESP-La Liga", "0910", "Dep La Coruña", "Adrián López"),
         ("ESP-La Liga", "0910", "Dep La Coruña", "Adrián López"),
         # dup pair where one row lacks born (Vittiglio, Pescara 2012):
         # the year suffix must not NA the name
         ("ESP-La Liga", "0910", "Valencia", "Marco Vittiglio"),
         ("ESP-La Liga", "0910", "Valencia", "Marco Vittiglio")],
        names=["league", "season", "team", "player"],
    )
    fbref = pd.DataFrame(
        [["ARG", "FW", 22, 1987, 35, 3100, 34, 11],
         ["ESP", "FW", 21, 1988, 30, 2044, 4, 2],
         ["ESP", "DF", 22, 1987, 5, 270, 0, 0],
         ["ITA", "MF", 18, 1994, 10, 500, 1, 0],
         ["ITA", "MF", None, None, 1, 23, 0, 0]],
        index=idx, columns=cols,
    )
    m_fbref = cached_fetch("fbref", "player_season",
                           {"league": "ESP-La Liga", "season": "2009"},
                           lambda: fbref)
    monkeypatch.setattr(ps, "fetch_fbref_season", lambda l, s, force=False: m_fbref)

    xref = pd.DataFrame({
        "fbref_name": ["Adrián López"], "team": ["Dep La Coruña"],
        "tm_id": pd.array([55], dtype="Int64"),
        "method": ["exact"], "confidence": [1.0],
    })
    m_xref = cached_fetch("xref", "players",
                          {"league": "ESP-La Liga", "season": "2009"},
                          lambda: xref)
    monkeypatch.setattr(ps, "build_player_xref", lambda l, s, force=False: m_xref)

    vals = pd.DataFrame({"player_id": [55], "date": ["2010-05-01"],
                         "market_value_in_eur": [10_000_000]})
    m_vals = cached_fetch("transfermarkt", "valuations", {"competition": "ALL"},
                          lambda: vals)
    monkeypatch.setattr(ps, "fetch_transfermarkt_values",
                        lambda c, force=False: m_vals)

    df = pd.read_parquet(ps.build_player_season("ESP-La Liga", "2009").path)
    assert len(df) == 5
    assert df.player_name.notna().all()
    assert not df.duplicated(["league", "season", "team", "player_name"]).any()
    assert set(df.player_name) == {
        "Lionel Messi", "Adrián López (1988)", "Adrián López (1987)",
        "Marco Vittiglio (1994)", "Marco Vittiglio (?)"
    }
    major = df[df.player_name == "Adrián López (1988)"].iloc[0]
    minor = df[df.player_name == "Adrián López (1987)"].iloc[0]
    assert major["tm_id"] == 55  # most-minutes row keeps the name-based match
    assert pd.isna(minor["tm_id"]) and minor["xref_method"] == "ambiguous"


def test_clean_rules():
    from soccerhub.pipelines.player_season import clean
    df = pd.DataFrame({
        "season": ["2023", "2023"],
        "position": ["MF,FW", "GK"],
        "birth_year": [2001, 1990],
        "age": [21, 40],  # 40 wrong: 2023-1990=33 -> recomputed
        "minutes": [2000, 100],
        "goals_per90": [0.5, 9.0],
        "assists_per90": [0.3, 4.5],
        "goals_assists_per90": [0.8, 13.5],
        "non_penalty_goals_per90": [0.4, 9.0],
        "non_penalty_goals_assists_per90": [0.7, 13.5],
        "tackles_interceptions_per90": [2.1, 8.0],
        "save_pct": [None, 100.0],
        "value_date": ["2024-05-01", "2022-01-01"],  # 2nd >1yr before 2024-06-30
        "market_value_in_eur": [1e7, 1e6],
    })
    out = clean(df)
    assert out.primary_position.tolist() == ["MF", "GK"]
    assert out.age.tolist() == [22, 33]  # season+1 minus birth year? no: 2023-2001=22
    assert out.loc[0, "goals_per90"] == 0.5          # enough minutes: kept
    assert pd.isna(out.loc[1, "goals_per90"])        # 100 min: rate nulled
    assert pd.isna(out.loc[1, "goals_assists_per90"])
    assert pd.isna(out.loc[1, "tackles_interceptions_per90"])  # new rates same floor
    assert pd.isna(out.loc[1, "save_pct"])
    assert out.loc[0, "tackles_interceptions_per90"] == 2.1
    assert out.loc[1, "minutes"] == 100              # counting stats untouched
    assert out.value_is_stale.tolist() == [False, True]


def test_build_player_season_merges_value(monkeypatch):
    import soccerhub.pipelines.player_season as ps
    from soccerhub.cache import cached_fetch

    manifests = {
        "standard": cached_fetch("fbref", "player_season",
            {"league": "ENG-Premier League", "season": "2023"}, _fake_fbref),
        "misc": cached_fetch("fbref", "player_season",
            {"league": "ENG-Premier League", "season": "2023", "stat_type": "misc"},
            _fake_misc),
        "keeper": cached_fetch("fbref", "player_season",
            {"league": "ENG-Premier League", "season": "2023", "stat_type": "keeper"},
            _fake_keeper),
    }
    monkeypatch.setattr(
        ps, "fetch_fbref_season",
        lambda l, s, force=False, stat_type="standard": manifests[stat_type])

    xref = pd.DataFrame({
        "fbref_name": ["Bukayo Saka", "Totally Unknown"],
        "team": ["Arsenal", "Arsenal"],
        "tm_id": pd.array([10, None], dtype="Int64"),
        "method": ["mapping_file", "unmatched"],
        "confidence": [1.0, 0.0],
    })
    m_xref = cached_fetch("xref", "players",
                          {"league": "ENG-Premier League", "season": "2023"},
                          lambda: xref)
    monkeypatch.setattr(ps, "build_player_xref", lambda l, s, force=False: m_xref)

    vals = pd.DataFrame({
        "player_id": [10, 10, 10],
        "date": ["2023-11-01", "2024-05-30", "2024-08-01"],  # last one after season end
        "market_value_in_eur": [90_000_000, 120_000_000, 140_000_000],
    })
    m_vals = cached_fetch("transfermarkt", "valuations", {"competition": "GB1"},
                          lambda: vals)
    monkeypatch.setattr(ps, "fetch_transfermarkt_values",
                        lambda c, force=False: m_vals)

    m = ps.build_player_season("ENG-Premier League", "2023")
    df = pd.read_parquet(m.path).set_index("player_name")

    saka = df.loc["Bukayo Saka"]
    assert saka["market_value_in_eur"] == 120_000_000  # latest <= 2024-06-30
    assert saka["season"] == "2023"
    unk = df.loc["Totally Unknown"]
    assert pd.isna(unk["market_value_in_eur"])  # kept, not dropped
    assert unk["xref_method"] == "unmatched"

    # misc merged; per-90 computed off nineties; Crs never lands
    assert saka["tackles_won"] == 30
    assert saka["tackles_interceptions_per90"] == 1.5  # (30+25)/36.7
    assert "crs" not in df.columns and "performance_crs" not in df.columns
    # keeper merged only onto its row; PK Save% collision dropped by canon pick
    assert unk["save_pct"] == 70.9
    assert unk["clean_sheet_pct"] == 21.1
    assert pd.isna(saka["save_pct"])


@pytest.mark.parametrize("today,expected", [
    ("2026-08-01", "2026"),  # first day of the new season
    ("2026-07-31", "2025"),  # last day before it — still the old season
    ("2026-09-28", "2026"),
    ("2027-01-15", "2026"),  # new calendar year, same season
])
def test_current_season_august_cutover(today, expected):
    from datetime import date

    from soccerhub.pipelines.player_season import current_season

    assert current_season(date.fromisoformat(today)) == expected
