"""Club Elo ratings from clubelo.com, via soccerdata (plain HTTPS, no browser —
unlike FBref this source needs no Cloudflare-bypass, so no selenium overhead)."""
import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest
from soccerhub.readers.fbref import _patch_league_config


def fetch_club_elo_snapshot(date: str | None = None, force: bool = False) -> Manifest:
    """Elo rating for every tracked club as of one date (default: today).

    ClubElo has no season/league filter — one call returns every club in its
    database, worldwide; the pipeline restricts to our 5 leagues on push.
    ``date`` is resolved before caching so a new day gets a new cache key
    (a constant key would silently serve yesterday's snapshot forever).
    """
    d = date or pd.Timestamp.now().strftime("%Y-%m-%d")
    _patch_league_config()  # must precede the first soccerdata import in-process
    import soccerdata as sd  # lazy: keeps the heavy scraper stack off import time

    def produce():
        df = sd.ClubElo(no_cache=force).read_by_date(d).reset_index()
        df = df.rename(columns={"from": "elo_from", "to": "elo_to"})
        # pandas Timestamps aren't JSON-serializable for the Supabase client
        df["elo_from"] = df["elo_from"].dt.strftime("%Y-%m-%d")
        df["elo_to"] = df["elo_to"].dt.strftime("%Y-%m-%d")
        df["snapshot_date"] = d
        return df

    return cached_fetch("clubelo", "snapshot", {"date": d}, produce, force)


def fetch_club_elo_history(team: str, since: str = "2008-01-01",
                           force: bool = False) -> Manifest:
    """Full Elo time series for one club: one row per rating change."""
    _patch_league_config()  # must precede the first soccerdata import in-process
    import soccerdata as sd  # lazy: keeps the heavy scraper stack off import time

    def produce():
        df = sd.ClubElo(no_cache=force).read_team_history(team).reset_index()
        # last row is a forward placeholder (rating pre-booked for the next
        # window, e.g. from=Aug to=Dec of the coming season) — not a snapshot
        today = pd.Timestamp.now().strftime("%Y-%m-%d")
        df = df[(df["from"] >= since) & (df["from"] <= today)]
        df = df.rename(columns={"from": "elo_from", "to": "elo_to"})
        df["elo_from"] = df["elo_from"].dt.strftime("%Y-%m-%d")
        df["elo_to"] = df["elo_to"].dt.strftime("%Y-%m-%d")
        # each rating becomes a snapshot dated at the start of its validity
        df["snapshot_date"] = df["elo_from"]
        return df

    return cached_fetch(
        "clubelo", "history", {"team": team, "since": since}, produce, force
    )
