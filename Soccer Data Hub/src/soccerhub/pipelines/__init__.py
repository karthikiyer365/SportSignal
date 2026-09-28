"""Preset pipelines: arbitration layer over the raw readers.

Supabase is the source of truth; local parquet manifests are build cache.
"""
from soccerhub.manifest import Manifest
from soccerhub.pipelines.player_season import build_player_season, current_season
from soccerhub.pipelines.query import read_hub
from soccerhub.pipelines.supa import push_to_supabase
from soccerhub.pipelines.xref import build_player_xref

__all__ = [
    "build_player_xref",
    "build_player_season",
    "current_season",
    "push_to_supabase",
    "push_transfers",
    "push_age_curve",
    "push_matches",
    "push_club_elo",
    "push_club_elo_history",
    "push_player_xg",
    "push_shots",
    "push_team_match",
    "read_hub",
    "run_season",
]

XREF_CONFLICT_KEY = "league,season,team,fbref_name"
TRANSFERS_CONFLICT_KEY = "tm_id,transfer_date"  # matches 0002 PK
AGE_CURVE_CONFLICT_KEY = "primary_position,age"  # matches 0005 PK
MATCHES_CONFLICT_KEY = "league,season,date,home_team,away_team"  # matches 0006 PK
CLUB_ELO_CONFLICT_KEY = "team,league,snapshot_date"  # matches 0007 PK
CONFLICT_KEY_PLAYER_SEASON = "league,season,team,player_name"  # matches 0001 PK
TEAM_MATCH_CONFLICT_KEY = "league,season,game_id"  # matches 0009 PK
SHOTS_CONFLICT_KEY = "league,season,shot_id"  # matches 0010 PK
BIG5 = {"ENG-Premier League", "ESP-La Liga", "GER-Bundesliga",
        "ITA-Serie A", "FRA-Ligue 1"}


def push_transfers(force: bool = False) -> int:
    """Transfers snapshot -> transfers table. Cron runs this so the table
    stays a feed, not a one-off load."""
    import pandas as pd

    from soccerhub.pipelines.supa import upsert_df
    from soccerhub.readers.transfermarkt import fetch_transfermarkt_transfers

    m = fetch_transfermarkt_transfers(force=force)
    return upsert_df(pd.read_parquet(m.path), "transfers", TRANSFERS_CONFLICT_KEY)


def push_age_curve(min_minutes: int = 450, min_n: int = 30) -> int:
    """player_season -> avg market value by (position, age) for the dashboard
    overlay. Derived from the hub itself (PostgREST aggregates are disabled),
    so cron must run it after the season jobs."""
    from soccerhub.pipelines.query import read_hub
    from soccerhub.pipelines.supa import upsert_df

    df = read_hub(
        "player_season",
        select="primary_position,age,market_value_in_eur,minutes",
    )
    df = df[
        (df["minutes"].fillna(0) >= min_minutes)
        & df["market_value_in_eur"].notna()
        & df["age"].notna()
        & df["primary_position"].notna()
    ]
    g = (
        df.groupby(["primary_position", "age"])["market_value_in_eur"]
        .agg(avg_value_eur="mean", n="count")
        .reset_index()
    )
    g = g[g["n"] >= min_n]  # thin age buckets (16, 40+) make a jumpy curve
    g["avg_value_eur"] = g["avg_value_eur"].round().astype("Int64")
    g["age"] = g["age"].astype(int)
    return upsert_df(g, "age_curve", AGE_CURVE_CONFLICT_KEY)


def push_matches(league: str, season: str, force: bool = False) -> int:
    """One league-season of match results -> matches table."""
    import pandas as pd

    from soccerhub.pipelines.matches import build_matches
    from soccerhub.pipelines.supa import upsert_df

    m = build_matches(league, season, force=force, refetch=force)
    return upsert_df(pd.read_parquet(m.path), "matches", MATCHES_CONFLICT_KEY)


def push_club_elo(date: str | None = None, force: bool = False) -> int:
    """Today's (or given date's) club Elo ratings -> club_elo table, Big-5 only."""
    import pandas as pd

    from soccerhub.pipelines.supa import upsert_df
    from soccerhub.readers.clubelo import fetch_club_elo_snapshot

    m = fetch_club_elo_snapshot(date, force=force)
    df = pd.read_parquet(m.path)
    df = df[df["league"].isin(BIG5)]
    return upsert_df(df, "club_elo", CLUB_ELO_CONFLICT_KEY)


# ClubElo history rows carry country+level, not a league name — top-flight
# rows in these countries ARE our five leagues
COUNTRY_TO_LEAGUE = {
    "ENG": "ENG-Premier League", "ESP": "ESP-La Liga", "GER": "GER-Bundesliga",
    "ITA": "ITA-Serie A", "FRA": "FRA-Ligue 1",
}


def push_club_elo_history(team: str, force: bool = False) -> int:
    """One club's Elo time series -> club_elo table (top-flight spells only).

    Second-division spells (relegation years) are dropped rather than
    mislabeled: level==1 + country is what maps cleanly onto our league names.
    """
    import pandas as pd

    from soccerhub.pipelines.supa import upsert_df
    from soccerhub.readers.clubelo import fetch_club_elo_history

    m = fetch_club_elo_history(team, force=force)
    df = pd.read_parquet(m.path)
    df = df[(df["level"] == 1) & df["country"].isin(COUNTRY_TO_LEAGUE)]
    if df.empty:
        return 0
    df["league"] = df["country"].map(COUNTRY_TO_LEAGUE)
    return upsert_df(df, "club_elo", CLUB_ELO_CONFLICT_KEY)


def push_xref(manifest: Manifest, league: str, season: str) -> int:
    """Xref parquet -> player_xref table (adds the league/season key cols)."""
    import pandas as pd

    from soccerhub.pipelines.supa import upsert_df

    df = pd.read_parquet(manifest.path)
    df.insert(0, "league", league)
    df.insert(1, "season", season)
    return upsert_df(df, "player_xref", XREF_CONFLICT_KEY)


def run_season(
    league: str, season: str, force: bool = False, table: str = "player_season"
) -> Manifest:
    """Phase A preset: xref -> merged player-season -> Supabase upsert.

    force here means "refresh this season": sources are re-downloaded, not
    just re-merged — the cron's whole point is new fbref numbers.
    """
    mx = build_player_xref(league, season, force=force, refetch=force)
    push_xref(mx, league, season)
    manifest = build_player_season(league, season, force=force, refetch=force)
    push_to_supabase(manifest, table)
    return manifest


# bottom import on purpose: understat.py reads this package's CONFLICT_KEY
# constants at call time, so importing it here is cycle-free
from soccerhub.pipelines.understat import (  # noqa: E402
    push_player_xg,
    push_shots,
    push_team_match,
)
