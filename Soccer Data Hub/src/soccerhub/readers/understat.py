"""Understat xG data (plain HTTP, no browser) via soccerdata."""
import logging

import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest
from soccerhub.readers.fbref import _patch_league_config, _season_to_code

log = logging.getLogger(__name__)

DATASETS = {
    "player_season": "read_player_season_stats",
    "team_match": "read_team_match_stats",
    "shots": "read_shot_events",
}


def fetch_understat(league: str, season: str, dataset: str = "player_season",
                    force: bool = False) -> Manifest:
    """One league-season of Understat data. Coverage: Big-5 from 2014.

    ``dataset``: player_season (per-player xG/xA totals), team_match
    (per-match team xG, PPDA, expected points), shots (every shot with
    coordinates — one page per match upstream, so much slower to fetch).
    """
    if dataset not in DATASETS:
        raise ValueError(f"dataset must be one of {sorted(DATASETS)}")
    _patch_league_config()  # must precede the first soccerdata import in-process
    import soccerdata as sd  # lazy: keeps the heavy scraper stack off import time

    def produce():
        u = sd.Understat(leagues=league, seasons=_season_to_code(season),
                         no_cache=force)  # see fbref.py: force must reach soccerdata's html cache
        if dataset == "shots":
            return _shots_skipping_bad_matches(u)
        return getattr(u, DATASETS[dataset])().reset_index()

    return cached_fetch(
        "understat", dataset, {"league": league, "season": season}, produce, force
    )


def _shots_skipping_bad_matches(u) -> pd.DataFrame:
    """Shot events for a season, tolerating individual unparseable matches.

    soccerdata's bulk read walks every match page and dies on the first bad
    one — Understat serves `rosters: []` instead of `{}` for some voided
    fixtures, which raises AttributeError deep in its parser and costs the
    whole season (GER 2024 lost ~8k shots this way). Try the fast bulk path
    first, then fall back to per-match so one broken fixture skips itself.
    """
    try:
        return u.read_shot_events().reset_index()
    except Exception as exc:
        log.warning("bulk shot read failed (%s) — retrying match by match", exc)

    ids = u.read_schedule().reset_index()["game_id"].dropna().unique()
    frames, skipped = [], []
    for gid in ids:
        try:
            frames.append(u.read_shot_events(match_id=int(gid)).reset_index())
        except Exception as exc:
            skipped.append((int(gid), type(exc).__name__))
    if not frames:
        raise RuntimeError(f"every match failed: {skipped[:3]}")
    if skipped:
        log.warning("skipped %d unparseable match(es): %s", len(skipped), skipped)
    return pd.concat(frames, ignore_index=True)
