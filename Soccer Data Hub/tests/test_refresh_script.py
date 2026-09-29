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
    # launchd Weekday 1..5 == Monday..Friday, and date.weekday() is Mon=0, so the
    # plist's five entries must line up with LEAGUES in order.
    ("2026-09-28", "ENG-Premier League"),  # Monday
    ("2026-09-29", "ESP-La Liga"),         # Tuesday
    ("2026-09-30", "GER-Bundesliga"),      # Wednesday
    ("2026-10-01", "ITA-Serie A"),         # Thursday
    ("2026-10-02", "FRA-Ligue 1"),         # Friday
])
def test_one_league_per_weekday(mod, day, expected, monkeypatch):
    monkeypatch.delenv("LEAGUE", raising=False)
    assert mod.leagues_for_today(date.fromisoformat(day)) == [expected]


@pytest.mark.parametrize("day", ["2026-10-03", "2026-10-04"])  # Sat, Sun
def test_weekend_refreshes_nothing(mod, day, monkeypatch):
    monkeypatch.delenv("LEAGUE", raising=False)
    assert mod.leagues_for_today(date.fromisoformat(day)) == []


def test_league_env_overrides_the_schedule(mod, monkeypatch):
    monkeypatch.setenv("LEAGUE", "ITA-Serie A")
    # Monday would otherwise be ENG; the override wins so a missed day can be re-run.
    assert mod.leagues_for_today(date(2026, 9, 28)) == ["ITA-Serie A"]


def test_every_league_has_a_weekday(mod):
    """A sixth league would silently never refresh — there are only five weekdays."""
    assert len(mod.LEAGUES) <= 5
