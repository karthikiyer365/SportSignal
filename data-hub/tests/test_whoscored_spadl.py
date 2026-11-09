from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "whoscored"  # Man Utd v Fulham 2024-08-16, first 300 events


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def test_strip_html_wrapper_unwraps_and_leaves_clean_json_alone():
    from soccerhub.readers.whoscored_spadl import strip_html_wrapper

    assert strip_html_wrapper('<html><head></head><body>{"a": 1}</body></html>') == '{"a": 1}'
    assert strip_html_wrapper('{"a": "<body>"}') == '{"a": "<body>"}'


def test_fixture_match_converts_to_spadl():
    from socceraction.data.opta import OptaLoader

    from soccerhub.readers.whoscored_spadl import FEEDS, _to_spadl

    L = OptaLoader(root=str(FIXTURES), parser="whoscored", feeds=FEEDS)
    g = L.games("ENG-Premier League", "2425")
    assert list(g.game_id) == [1821049]
    assert set(L.teams(1821049).team_name) == {"Man Utd", "Fulham"}
    a = _to_spadl(L.events(1821049), int(g.home_team_id.iat[0]))
    assert len(a) > 0 and {"start_x", "end_x", "type_id", "player_id"} <= set(a.columns)


def test_patch_is_scoped_to_soccerdata_whoscored():
    import io
    import json

    import soccerdata.whoscored as ws

    from soccerhub.readers.whoscored_spadl import _patch_whoscored_json

    _patch_whoscored_json()
    _patch_whoscored_json()  # idempotent
    assert ws.json.load(io.StringIO('<html><head></head><body>[1]</body></html>')) == [1]
    assert json.load is not ws.json.load  # stdlib untouched


def test_refresh_lists_new_games_without_refetching_old_ones():
    import pandas as pd

    from soccerhub.readers.spadl_season import fetch_spadl_season

    schedule = [[1], [1, 2]]  # game 2 is played between the two runs
    built = []

    def run(refresh):
        ids = schedule.pop(0)
        return fetch_spadl_season(
            "test_src", {"league": "X", "season": "2627"},
            make_loader=lambda: None,
            games_of=lambda L: pd.DataFrame({"game_id": ids, "home_team_id": [10] * len(ids)}),
            actions_of=lambda L, g: built.append(int(g.game_id)) or pd.DataFrame({"game_id": [g.game_id]}),
            players_of=lambda L, gid: pd.DataFrame({"game_id": [gid]}),
            refresh=refresh)

    run(refresh=False)
    m = run(refresh=True)
    assert built == [1, 2]
    assert len(pd.read_parquet(m["actions"].path)) == 2


def test_finished_ids_keeps_only_full_time_games():
    import pandas as pd

    from soccerhub.readers.whoscored_spadl import finished_ids

    sched = pd.DataFrame({"game_id": [1, 2, 3], "status": [6, 1, 3]})  # FT, not started, in play
    assert finished_ids(sched) == [1]


def test_null_files_from_unplayed_games_are_dropped_and_games_still_list(tmp_path):
    import shutil

    from socceraction.data.opta import OptaLoader

    from soccerhub.readers.whoscored_spadl import FEEDS, drop_null_files

    root = tmp_path / "ws"
    shutil.copytree(FIXTURES, root)
    season_dir = root / "events" / "ENG-Premier League_2425"
    (season_dir / "999.json").write_bytes(b"null")  # what soccerdata saves for an unplayed game
    assert drop_null_files(season_dir) == 1
    L = OptaLoader(root=str(root), parser="whoscored", feeds=FEEDS)
    assert list(L.games("ENG-Premier League", "2425").game_id) == [1821049]
