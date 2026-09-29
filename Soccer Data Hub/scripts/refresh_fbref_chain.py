#!/usr/bin/env python
"""Refresh the FBref-sourced chain on this machine, not in CI.

FBref sits behind a Cloudflare interactive challenge. soccerdata clears it with a real
Chrome (``class FBref(BaseSeleniumReader)``), but only from a residential IP — on a
GitHub runner the browser starts, burns all five attempts and raises. So every job that
reads FBref runs here instead, on the twice-weekly schedule launchd owns.

The three stages are ordered, not independent: understat and age_curve both update rows
that run_season writes, so they must follow it in the same pass.

One league per weekday. All five in one pass is 15 challenge-gated FBref fetches, which
trips their per-IP limit: measured 2026-09-29, the first league completed in 35 min and
the second was refused partway with "failed CAPTCHA, IP block or network issues".

Run ``--dry-run`` to check env + imports without touching the network.
``LEAGUE=<name>`` does one named league, ``--all`` does all five (expect a block).
"""
import atexit
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
# Order is the schedule: index 0 runs Monday, 4 runs Friday.
LEAGUES = [
    "ENG-Premier League",
    "ESP-La Liga",
    "GER-Bundesliga",
    "ITA-Serie A",
    "FRA-Ligue 1",
]


def leagues_for_today(today: date) -> list[str]:
    """Which leagues this invocation should refresh."""
    if os.environ.get("LEAGUE"):
        return [os.environ["LEAGUE"]]
    if "--all" in sys.argv:
        return LEAGUES
    weekday = today.weekday()  # Mon=0
    return [LEAGUES[weekday]] if weekday < len(LEAGUES) else []


def reap_orphan_drivers() -> None:
    """Kill uc_driver processes soccerdata left behind.

    Each retry calls _init_webdriver() again without quitting the dead session, so a
    run with retries leaks one driver per attempt — 5 were still resident after the
    2026-09-29 run. Scoped to this venv's path so another project's drivers survive.
    """
    driver = HUB / ".venv/lib/python3.11/site-packages/seleniumbase/drivers/uc_driver"
    subprocess.run(["pkill", "-f", str(driver)], check=False)


def load_env(path: Path) -> None:
    """Export KEY=VALUE lines. The package reads os.environ directly, no dotenv dep."""
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}  {msg}", flush=True)


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    # launchd starts us in "/", which is read-only — seleniumbase creates its
    # downloaded_files dir relative to cwd, and the parquet cache is relative too.
    os.chdir(HUB)
    load_env(HUB / ".env")

    missing = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY") if not os.environ.get(k)]
    if missing:
        log(f"FATAL missing env: {', '.join(missing)}")
        return 1

    from soccerhub import (
        current_season,
        push_age_curve,
        push_player_xg,
        push_shots,
        push_team_match,
        run_season,
    )
    from soccerhub.errors import SoccerhubError

    season = os.environ.get("SEASON") or current_season()
    todays = leagues_for_today(date.today())
    log(f"season {season}, leagues {todays or '(none — weekend)'}"
        f"{' (dry run)' if dry_run else ''}")
    if dry_run:
        log("OK env + imports fine")
        return 0
    if not todays:
        return 0

    atexit.register(reap_orphan_drivers)

    # One league's failure must not cost the rest — FBref blocks per-IP, per-day, so a
    # later league can still succeed after an earlier one is refused.
    failures = []
    for league in todays:
        try:
            log(f"seasons  {league}: {run_season(league, season, force=True)}")
        except SoccerhubError as exc:
            log(f"FAILED seasons {league}: {exc}")
            failures.append(f"seasons/{league}")
            continue
        for name, fn in (("player_xg", push_player_xg), ("team_match", push_team_match),
                         ("shots", push_shots)):
            try:
                log(f"{name}  {league}: {fn(league, season, force=True)}")
            except SoccerhubError as exc:
                log(f"FAILED {name} {league}: {exc}")
                failures.append(f"{name}/{league}")

    # age_curve is derived from player_season across all leagues, so it runs once at the end.
    try:
        log(f"age_curve: {push_age_curve()}")
    except SoccerhubError as exc:
        log(f"FAILED age_curve: {exc}")
        failures.append("age_curve")

    if failures:
        log(f"DONE with {len(failures)} failure(s): {', '.join(failures)}")
        return 1
    log("DONE all stages clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
