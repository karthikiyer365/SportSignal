def test_run_season_chains_and_pushes(monkeypatch):
    import soccerhub.pipelines as pl

    order = []
    refetches = []
    fake_manifest = object()
    monkeypatch.setattr(
        pl, "build_player_xref",
        lambda l, s, force=False, refetch=False:
            (order.append("xref"), refetches.append(refetch))[0])
    monkeypatch.setattr(pl, "push_xref",
                        lambda m, l, s: order.append("push:xref"))
    monkeypatch.setattr(
        pl, "build_player_season",
        lambda l, s, force=False, refetch=False:
            (order.append("merge"), refetches.append(refetch), fake_manifest)[2],
    )
    monkeypatch.setattr(pl, "push_to_supabase",
                        lambda m, table: order.append(f"push:{table}"))

    out = pl.run_season("ENG-Premier League", "2023", force=True)
    assert order == ["xref", "push:xref", "merge", "push:player_season"]
    assert out is fake_manifest
    assert refetches == [True, True]  # cron force must reach the leaf readers


def test_read_hub_paginates_and_filters(monkeypatch):
    import io
    import json as jsonlib
    import urllib.request

    import soccerhub.db.read as q

    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "anon")
    monkeypatch.setattr(q, "PAGE", 2)

    pages = [[{"a": 1}, {"a": 2}], [{"a": 3}]]  # 2 full + short page -> stop
    urls = []

    def fake_urlopen(req):
        urls.append(req.full_url)
        return io.BytesIO(jsonlib.dumps(pages[len(urls) - 1]).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    df = q.read_hub("player_season", league="ITA-Serie A")
    assert list(df.a) == [1, 2, 3]
    assert len(urls) == 2
    assert "league=eq.ITA-Serie+A" in urls[0] or "league=eq.ITA-Serie%20A" in urls[0]
    assert "offset=2" in urls[1]


def test_push_xref_adds_key_columns(monkeypatch, tmp_path):
    import pandas as pd

    import soccerhub.pipelines as pl
    from soccerhub.manifest import Manifest

    xdf = pd.DataFrame({"fbref_name": ["A"], "team": ["T"],
                        "tm_id": [1], "method": ["exact"], "confidence": [1.0]})
    p = tmp_path / "x.parquet"
    xdf.to_parquet(p)
    m = Manifest(path=str(p), source="xref", dataset="players",
                 params={}, rows=1, cols=5, date_range=None, fetched_at="t")

    captured = {}

    def fake_upsert(df, table, on_conflict):
        captured["df"], captured["table"], captured["key"] = df, table, on_conflict
        return len(df)

    import soccerhub.db.write as sp
    monkeypatch.setattr(sp, "upsert_df", fake_upsert)

    n = pl.push_xref(m, "ITA-Serie A", "2023")
    assert n == 1
    assert captured["table"] == "player_xref"
    assert captured["df"].iloc[0]["league"] == "ITA-Serie A"
    assert captured["df"].iloc[0]["season"] == "2023"
    assert captured["key"] == "league,season,team,fbref_name"


def test_push_transfers_upserts_on_composite_key(monkeypatch, tmp_path):
    import pandas as pd

    import soccerhub.pipelines as pl
    from soccerhub.manifest import Manifest

    tdf = pd.DataFrame({"tm_id": [1], "transfer_date": ["2023-07-01"],
                        "from_club": ["A"], "to_club": ["B"]})
    p = tmp_path / "t.parquet"
    tdf.to_parquet(p)
    m = Manifest(path=str(p), source="transfermarkt", dataset="transfers",
                 params={}, rows=1, cols=4, date_range=None, fetched_at="t")

    forces = []
    monkeypatch.setattr(
        "soccerhub.readers.transfermarkt.fetch_transfermarkt_transfers",
        lambda force=False: (forces.append(force), m)[1])

    captured = {}

    def fake_upsert(df, table, on_conflict):
        captured["table"], captured["key"] = table, on_conflict
        return len(df)

    import soccerhub.db.write as sp
    monkeypatch.setattr(sp, "upsert_df", fake_upsert)

    assert pl.push_transfers(force=True) == 1
    assert forces == [True]
    assert captured["table"] == "transfers"
    assert captured["key"] == "tm_id,transfer_date"


def test_push_age_curve_groups_and_filters(monkeypatch):
    import pandas as pd

    import soccerhub.pipelines as pl

    hub = pd.DataFrame({
        "primary_position": ["FW"]*3 + ["MF"]*2 + [None],
        "age": [23, 23, 23, 30, 30, 23],
        "market_value_in_eur": [10e6, 20e6, None, 5e6, 7e6, 9e6],
        "minutes": [900, 900, 900, 900, 100, 900],
    })
    monkeypatch.setattr("soccerhub.db.read.read_hub",
                        lambda table, select: hub)

    captured = {}

    def fake_upsert(df, table, on_conflict):
        captured["df"], captured["table"], captured["key"] = df, table, on_conflict
        return len(df)

    import soccerhub.db.write as sp
    monkeypatch.setattr(sp, "upsert_df", fake_upsert)

    # min_n=2: FW/23 survives (two valued rows -> avg 15m); MF/30 has one row
    # over the minutes floor -> dropped; None position dropped
    assert pl.push_age_curve(min_minutes=450, min_n=2) == 1
    row = captured["df"].iloc[0]
    assert captured["table"] == "age_curve"
    assert captured["key"] == "primary_position,age"
    assert (row["primary_position"], row["age"]) == ("FW", 23)
    assert row["avg_value_eur"] == 15_000_000
    assert row["n"] == 2


def test_push_matches_builds_and_upserts(monkeypatch, tmp_path):
    import pandas as pd

    import soccerhub.pipelines as pl
    from soccerhub.manifest import Manifest

    mdf = pd.DataFrame({
        "league": ["ENG-Premier League"], "season": ["2023"],
        "date": ["2023-08-11"], "home_team": ["Burnley"], "away_team": ["Man City"],
        "home_goals": [0], "away_goals": [3], "result": ["A"],
    })
    p = tmp_path / "m.parquet"
    mdf.to_parquet(p)
    fake_manifest = Manifest(path=str(p), source="hub", dataset="matches",
                             params={}, rows=1, cols=7, date_range=None, fetched_at="t")

    monkeypatch.setattr("soccerhub.pipelines.matches.build_matches",
                        lambda l, s, force=False, refetch=False: fake_manifest)

    captured = {}

    def fake_upsert(df, table, on_conflict):
        captured["table"], captured["key"] = table, on_conflict
        return len(df)

    import soccerhub.db.write as sp
    monkeypatch.setattr(sp, "upsert_df", fake_upsert)

    assert pl.push_matches("ENG-Premier League", "2023") == 1
    assert captured["table"] == "matches"
    assert captured["key"] == "league,season,date,home_team,away_team"


def test_push_club_elo_filters_to_big5(monkeypatch, tmp_path):
    import pandas as pd

    import soccerhub.pipelines as pl
    from soccerhub.manifest import Manifest

    edf = pd.DataFrame({
        "team": ["Man City", "River Plate"],
        "league": ["ENG-Premier League", "ARG-Primera Division"],
        "snapshot_date": ["2023-08-11", "2023-08-11"],
        "elo": [2077.3, 1900.0],
    })
    p = tmp_path / "e.parquet"
    edf.to_parquet(p)
    fake_manifest = Manifest(path=str(p), source="clubelo", dataset="snapshot",
                             params={}, rows=2, cols=4, date_range=None, fetched_at="t")

    monkeypatch.setattr("soccerhub.readers.clubelo.fetch_club_elo_snapshot",
                        lambda date, force=False: fake_manifest)

    captured = {}

    def fake_upsert(df, table, on_conflict):
        captured["df"], captured["table"], captured["key"] = df, table, on_conflict
        return len(df)

    import soccerhub.db.write as sp
    monkeypatch.setattr(sp, "upsert_df", fake_upsert)

    n = pl.push_club_elo("2023-08-11")
    assert n == 1  # River Plate (non-Big5) filtered out
    assert captured["table"] == "club_elo"
    assert captured["key"] == "team,league,snapshot_date"
    assert list(captured["df"]["team"]) == ["Man City"]


def test_push_club_elo_history_maps_league_and_drops_lower_divisions(
        monkeypatch, tmp_path):
    import pandas as pd

    import soccerhub.pipelines as pl
    from soccerhub.manifest import Manifest

    hdf = pd.DataFrame({
        "team": ["Leicester"]*3,
        "country": ["ENG"]*3,
        "level": [1, 2, 1],  # level 2 = Championship spell: dropped, not mislabeled
        "elo": [1700.0, 1600.0, 1750.0],
        "elo_from": ["2015-08-01", "2023-08-01", "2024-08-01"],
        "elo_to": ["2015-08-08", "2023-08-08", "2024-08-08"],
        "snapshot_date": ["2015-08-01", "2023-08-01", "2024-08-01"],
    })
    p = tmp_path / "h.parquet"
    hdf.to_parquet(p)
    fake_manifest = Manifest(path=str(p), source="clubelo", dataset="history",
                             params={}, rows=3, cols=7, date_range=None, fetched_at="t")

    monkeypatch.setattr("soccerhub.readers.clubelo.fetch_club_elo_history",
                        lambda team, force=False: fake_manifest)

    captured = {}

    def fake_upsert(df, table, on_conflict):
        captured["df"], captured["table"], captured["key"] = df, table, on_conflict
        return len(df)

    import soccerhub.db.write as sp
    monkeypatch.setattr(sp, "upsert_df", fake_upsert)

    assert pl.push_club_elo_history("Leicester") == 2
    assert captured["table"] == "club_elo"
    assert captured["key"] == "team,league,snapshot_date"
    assert set(captured["df"]["league"]) == {"ENG-Premier League"}
    assert 1600.0 not in set(captured["df"]["elo"])


def test_public_exports():
    import soccerhub
    for fn in ("build_player_xref", "build_player_season",
               "push_to_supabase", "push_transfers", "push_age_curve",
               "push_matches", "push_club_elo", "push_club_elo_history",
               "push_player_xg", "push_team_match", "push_shots",
               "run_season"):
        assert callable(getattr(soccerhub, fn))
