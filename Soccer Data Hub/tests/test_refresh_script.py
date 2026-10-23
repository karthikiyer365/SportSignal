"""Checks for scripts/refresh_fbref_chain.py — the launchd entry point.

Loaded by path: it is an operational script, not part of the installed package.
"""
import importlib.util
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "refresh_fbref_chain.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("refresh_fbref_chain", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("day,expected", [
    # date.weekday() is Mon=0; launchd fires daily and SCHEDULE decides what runs.
    ("2026-09-28", "ENG-Premier League"),       # Monday
    ("2026-09-29", "IND-Indian Super League"),  # Tuesday
    ("2026-09-30", "ESP-La Liga"),              # Wednesday
    ("2026-10-01", "GER-Bundesliga"),           # Thursday
    ("2026-10-02", "ITA-Serie A"),              # Friday
    ("2026-10-03", "FRA-Ligue 1"),              # Saturday
])
def test_one_league_per_weekday(mod, day, expected, monkeypatch):
    monkeypatch.delenv("LEAGUE", raising=False)
    assert mod.leagues_for_today(date.fromisoformat(day)) == [expected]


def test_sunday_refreshes_nothing(mod, monkeypatch):
    monkeypatch.delenv("LEAGUE", raising=False)
    assert mod.leagues_for_today(date(2026, 10, 4)) == []


def test_league_env_overrides_the_schedule(mod, monkeypatch):
    monkeypatch.setenv("LEAGUE", "ITA-Serie A")
    # Monday would otherwise be ENG; the override wins so a missed day can be re-run.
    assert mod.leagues_for_today(date(2026, 9, 28)) == ["ITA-Serie A"]


def test_every_league_has_a_day(mod):
    assert len(mod.SCHEDULE) <= 7 and set(mod.LEAGUES) | {mod.ISL} == set(mod.SCHEDULE.values())
    assert mod.ISL not in mod.LEAGUES  # --all must never send the ISL through FBref


def test_isl_day_runs_isl_not_fbref(mod, monkeypatch):
    import soccerhub

    calls = []
    monkeypatch.setattr(mod, "load_env", lambda path: None)
    monkeypatch.setattr(mod.os, "chdir", lambda path: None)
    monkeypatch.setenv("SUPABASE_URL", "x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("LEAGUE", "IND-Indian Super League")
    monkeypatch.setattr(mod.sys, "argv", ["refresh_fbref_chain.py"])
    monkeypatch.setattr(soccerhub, "push_isl_new", lambda: calls.append("isl") or {"player_match": 3})
    monkeypatch.setattr(soccerhub, "run_season", lambda *a, **k: calls.append("fbref"))
    monkeypatch.setattr(soccerhub, "push_age_curve", lambda: calls.append("age"))
    assert mod.main() == 0
    assert calls == ["isl"]


def _big5_day(mod, monkeypatch, calls, run_season, push_fotmob_new):
    import soccerhub

    monkeypatch.setattr(mod, "load_env", lambda path: None)
    monkeypatch.setattr(mod.os, "chdir", lambda path: None)
    monkeypatch.setattr(mod.atexit, "register", lambda fn: None)
    monkeypatch.setenv("SUPABASE_URL", "x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("LEAGUE", "ENG-Premier League")
    monkeypatch.setattr(mod.sys, "argv", ["refresh_fbref_chain.py"])
    monkeypatch.setattr(soccerhub, "run_season", run_season)
    for name in ("push_player_xg", "push_team_match", "push_shots"):
        monkeypatch.setattr(soccerhub, name, lambda *a, **k: calls.append("understat"))
    monkeypatch.setattr(soccerhub, "push_fotmob_new", push_fotmob_new)
    monkeypatch.setattr(soccerhub, "link_fotmob", lambda lg, s: calls.append("link") or (1, 1))
    monkeypatch.setattr(soccerhub, "push_age_curve", lambda: calls.append("age"))
    return mod.main()


def test_big5_day_runs_fotmob_even_when_fbref_blocked(mod, monkeypatch):
    from soccerhub.errors import SoccerhubError

    calls = []

    def blocked(*a, **k):
        calls.append("fbref")
        raise SoccerhubError("IP block")

    rc = _big5_day(mod, monkeypatch, calls, blocked, lambda lg: calls.append("fotmob") or {})
    assert calls == ["fbref", "fotmob", "link", "age"] and rc == 1


def test_fotmob_http_error_is_logged_not_fatal(mod, monkeypatch):
    import urllib.error

    calls = []

    def http_down(lg):
        calls.append("fotmob")
        raise urllib.error.HTTPError("u", 503, "down", None, None)

    rc = _big5_day(mod, monkeypatch, calls, lambda *a, **k: calls.append("fbref"), http_down)
    assert "age" in calls and "link" not in calls and rc == 1
