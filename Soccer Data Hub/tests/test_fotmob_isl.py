import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "fotmob_4617934.json.gz"  # MBSG 2-2 Mumbai, 2024-09-13


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


@pytest.fixture(scope="module")
def raw():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))


@pytest.fixture(scope="module")
def parsed(raw):
    from soccerhub.pipelines.fotmob_isl import parse_match
    return parse_match(raw, "2024")


def test_parse_match_row(parsed):
    m = parsed["matches"].iloc[0]
    assert (m.home_team, m.away_team, m.home_goals, m.away_goals) == ("Mohun Bagan SG", "Mumbai City FC", 2, 2)
    assert m.league == "IND-Indian Super League" and m.season == "2024" and m.date == "2024-09-13"
    assert (m.home_goals_ht, m.away_goals_ht, m.result, m.result_ht) == (2, 0, "D", "H")
    assert m.home_shots + m.away_shots == 20 and m.home_yellow + m.away_yellow == 8
    assert pd.isna(m.referee)  # infoBox Referee text is '' here


def test_team_match_possession(parsed):
    t = parsed["team_match"].iloc[0]
    assert (t.home_possession, t.away_possession) == (46, 54)
    assert t.game_id == 4617934 and (t.home_xg, t.away_xg) == (0.08, 1.10)


def test_shots_scaled_and_vocab(parsed):
    s = parsed["shots"]
    assert len(s) == 21
    assert s.location_x.between(0, 1).all() and s.location_y.between(0, 1).all()
    assert (s[s.result != "Own Goal"].location_x > 0.5).all()
    assert set(s.result) <= {"Goal", "Own Goal", "Saved Shot", "Missed Shot", "Blocked Shot", "Shot On Post"}
    assert (s.result == "Own Goal").sum() == 1
    assert set(s.body_part.dropna()) <= {"Right Foot", "Left Foot", "Head"}
    assert (s.game_id == 4617934).all() and s.player_id.notna().all()


def test_player_match_drops_unused_and_keeps_nulls(parsed):
    p = parsed["player_match"]
    assert len(p) == 31 and (p.minutes > 0).all()  # 40 listed, 9 unused subs dropped
    assert p.is_starter.sum() == 22
    toral = p[p.player_name == "Jon Toral"].iloc[0]
    assert pd.isna(toral.xgot)          # stat present, no value -> null, not 0
    assert toral.team == "Mumbai City FC" and toral.opponent == "Mohun Bagan SG" and not toral.is_home
    assert p.yellow_cards.sum() == 8
    assert set(p.position.dropna()) <= {"GK", "DF", "MF", "FW"}
    assert p.groupby("team").goals_conceded.max().notna().all()  # each side's GK row has it


def _pm(rows):
    from soccerhub.pipelines.fotmob_isl import PLAYER_STATS

    base = {**dict.fromkeys(PLAYER_STATS), "league": "IND-Indian Super League", "season": "2024",
            "goals": 0, "is_starter": True, "position": "MF", "rating": 7.0,
            "yellow_cards": 0, "red_cards": 0}
    return pd.DataFrame([{**base, **r} for r in rows])


def _shots(rows):
    return pd.DataFrame(rows, columns=["player_id", "team", "situation", "result"])


def test_season_rows_sums_and_per90():
    from soccerhub.pipelines.fotmob_isl import season_rows

    pm = _pm([
        dict(match_id=1, fotmob_id=7, team="FC Goa", player_name="A", minutes=90, goals=1, is_starter=True, position="FW", rating=7.0),
        dict(match_id=2, fotmob_id=7, team="FC Goa", player_name="A", minutes=45, goals=0, is_starter=False, position="FW", rating=6.0),
    ])
    r = season_rows(pm, _shots([])).iloc[0]
    assert (r.matches_played, r.starts, r.minutes, r.goals) == (2, 1, 135, 1)
    assert r.nineties == 1.5 and round(r.goals_per90, 3) == 0.667
    assert round(r.fotmob_rating, 3) == 6.667
    assert (r.primary_position, r.fotmob_id) == ("FW", 7)


def test_mover_gets_one_row_per_team():
    from soccerhub.pipelines.fotmob_isl import season_rows

    pm = _pm([dict(match_id=1, fotmob_id=7, team="FC Goa", player_name="A", minutes=90),
              dict(match_id=9, fotmob_id=7, team="Odisha FC", player_name="A", minutes=90)])
    assert set(season_rows(pm, _shots([])).team) == {"FC Goa", "Odisha FC"}


def test_penalties_split_from_open_play():
    from soccerhub.pipelines.fotmob_isl import season_rows

    pm = _pm([dict(match_id=1, fotmob_id=7, team="FC Goa", player_name="A", minutes=90, goals=2)])
    shots = _shots([dict(player_id=7, team="FC Goa", situation="Penalty", result="Goal")])
    r = season_rows(pm, shots).iloc[0]
    assert (r.penalties_attempted, r.penalties_scored, r.non_penalty_goals) == (1, 1, 1)


@pytest.fixture
def wired(monkeypatch, raw):
    """push_* with FotMob, Supabase reads and upserts faked; every match is the fixture."""
    import soccerhub.pipelines.fotmob_isl as fi
    import soccerhub.pipelines.query as q
    import soccerhub.pipelines.supa as sp
    import soccerhub.readers.fotmob as fm

    state = {"fetched": [], "upserts": [], "stored": [], "finished": [4617934, 555]}
    league = {"allAvailableSeasons": ["2024/2025", "2023/2024"],
              "fixtures": {"allMatches": [{"id": str(i), "status": {"finished": True}}
                                          for i in state["finished"]]}}
    monkeypatch.setattr(fm, "fetch_league", lambda season=None, force=False: league)
    monkeypatch.setattr(fm, "fetch_match",
                        lambda i, season, force=False: state["fetched"].append(i) or raw)

    def read_hub(table, select="*", **eq):
        if table == "player_match" and select == "match_id":
            return pd.DataFrame({"match_id": state["stored"]})
        p = fi.parse_match(raw, "2024")
        return p["player_match"] if table == "player_match" else p["shots"]

    monkeypatch.setattr(q, "read_hub", read_hub)
    monkeypatch.setattr(sp, "upsert_df", lambda df, table, key: state["upserts"].append((table, key)) or len(df))
    return state


def test_push_isl_new_fetches_only_missing(wired):
    from soccerhub.pipelines.fotmob_isl import push_isl_new

    wired["stored"] = [4617934]
    push_isl_new()
    assert wired["fetched"] == [555]


def test_push_isl_upserts_every_table_with_its_key(wired):
    from soccerhub.pipelines.fotmob_isl import push_isl

    out = push_isl("2024", match_ids=[4617934])
    keys = dict(wired["upserts"])
    assert set(keys) == {"matches", "team_match_understat", "shots_understat", "player_match", "player_season"}
    assert keys["player_match"] == "league,season,match_id,fotmob_id"
    assert keys["player_season"] == "league,season,team,player_name"
    assert out["player_match"] == 31


def test_shootout_kicks_are_not_shots(raw):
    import copy

    from soccerhub.pipelines.fotmob_isl import parse_match

    r = copy.deepcopy(raw)
    kick = {**r["content"]["shotmap"]["shots"][0], "id": 1, "period": "PenaltyShootout",
            "situation": "Penalty", "eventType": "Goal"}
    r["content"]["shotmap"]["shots"].append(kick)
    assert len(parse_match(r, "2024")["shots"]) == 21  # FotMob logs 9 of these in 4138418


def test_rating_ignores_unrated_cameo_minutes():
    from soccerhub.pipelines.fotmob_isl import season_rows

    pm = _pm([dict(match_id=1, fotmob_id=7, team="FC Goa", player_name="A", minutes=90, rating=7.0),
              dict(match_id=2, fotmob_id=7, team="FC Goa", player_name="A", minutes=10, rating=None),
              dict(match_id=3, fotmob_id=7, team="FC Goa", player_name="A", minutes=10, rating=None)])
    assert season_rows(pm, _shots([])).iloc[0].fotmob_rating == 7.0


def test_duplicate_page_rows_are_not_double_counted():
    from soccerhub.pipelines.fotmob_isl import season_rows

    row = dict(match_id=1, fotmob_id=7, team="FC Goa", player_name="A", minutes=90, goals=1)
    r = season_rows(_pm([row, row]), _shots([])).iloc[0]   # offset paging can repeat a row
    assert (r.minutes, r.goals) == (90, 1)


def test_push_isl_new_rebuilds_season_when_nothing_new(wired):
    from soccerhub.pipelines.fotmob_isl import push_isl_new

    wired["stored"] = list(wired["finished"])
    push_isl_new()
    assert wired["fetched"] == [] and [t for t, _ in wired["upserts"]] == ["player_season"]


def test_broken_team_ids_resolve_to_the_other_side(raw):
    """FotMob tags SC Delhi 2025 shots teamId=-1 and players teamId=0 (e.g. match 5159578)."""
    import copy

    from soccerhub.pipelines.fotmob_isl import parse_match

    r = copy.deepcopy(raw)
    home_id = r["header"]["teams"][0]["id"]               # break the HOME side: worst case for is_home
    for s in r["content"]["shotmap"]["shots"]:
        if s["teamId"] == home_id:
            s["teamId"] = -1
    for p in r["content"]["playerStats"].values():
        if p["teamId"] == home_id:
            p["teamId"] = 0
    p = parse_match(r, "2024")
    assert p["shots"].team.notna().all()
    assert set(p["shots"].team) == {"Mohun Bagan SG", "Mumbai City FC"}
    pm = p["player_match"]
    assert (pm[pm.team == "Mohun Bagan SG"].is_home).all() and len(pm[pm.team == "Mohun Bagan SG"]) > 11


def test_statless_player_without_team_id_is_skipped(raw):
    """Match 6361999 lists a player with no teamId and no stats at all."""
    import copy

    from soccerhub.pipelines.fotmob_isl import parse_match

    r = copy.deepcopy(raw)
    r["content"]["playerStats"]["1"] = {"name": "Ghost", "id": 1, "isGoalkeeper": False, "stats": []}
    assert len(parse_match(r, "2024")["player_match"]) == 31
