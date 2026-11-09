"""Match results pipeline: football-data.co.uk -> matches table."""
import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest
from soccerhub.readers.matchhistory import fetch_match_history


def build_matches(
    league: str, season: str, force: bool = False, refetch: bool = False
) -> Manifest:
    """One league-season of match results, keyed and ready to push."""

    def produce():
        df = pd.read_parquet(fetch_match_history(league, season, force=refetch).path)
        df.insert(0, "league", league)
        df.insert(1, "season", season)
        return df

    return cached_fetch(
        "hub", "matches", {"league": league, "season": season}, produce, force
    )
