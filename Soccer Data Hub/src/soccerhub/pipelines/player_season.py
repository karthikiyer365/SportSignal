"""Merged player-season table: FBref stats + Transfermarkt market value."""
from datetime import date

import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest
from soccerhub.pipelines.xref import build_player_xref
from soccerhub.readers.fbref import fetch_fbref_season
from soccerhub.readers.transfermarkt import fetch_transfermarkt_values

# FBref ('group', 'stat') -> canonical DB column. One namespace forever;
# Understat/ClubElo columns land here later, not in source jargon.
CANON = {
    ("nation", ""): "nationality",
    ("pos", ""): "position",
    ("age", ""): "age",
    ("born", ""): "birth_year",
    ("Playing Time", "MP"): "matches_played",
    ("Playing Time", "Starts"): "starts",
    ("Playing Time", "Min"): "minutes",
    ("Playing Time", "90s"): "nineties",
    ("Performance", "Gls"): "goals",
    ("Performance", "Ast"): "assists",
    ("Performance", "G+A"): "goals_assists",
    ("Performance", "G-PK"): "non_penalty_goals",
    ("Performance", "PK"): "penalties_scored",
    ("Performance", "PKatt"): "penalties_attempted",
    ("Performance", "CrdY"): "yellow_cards",
    ("Performance", "CrdR"): "red_cards",
    ("Per 90 Minutes", "Gls"): "goals_per90",
    ("Per 90 Minutes", "Ast"): "assists_per90",
    ("Per 90 Minutes", "G+A"): "goals_assists_per90",
    ("Per 90 Minutes", "G-PK"): "non_penalty_goals_per90",
    ("Per 90 Minutes", "G+A-PK"): "non_penalty_goals_assists_per90",
}


def flatten_fbref(df: pd.DataFrame) -> pd.DataFrame:
    """MultiIndex fbref frame -> flat frame with canonical column names."""
    flat = df.copy()
    flat.columns = [
        CANON.get(tuple(c), "_".join(filter(None, c)).lower()) for c in flat.columns
    ]
    flat = flat.reset_index().rename(columns={"player": "player_name"})
    # fbref tables occasionally carry a nameless artifact row (Serie A 2012)
    return flat[flat["player_name"].notna()]


# extra stat pages: only the columns the card needs, one canon per page.
# (per-league fbref 'misc' is the defensive table this soccerdata exposes —
# there is no 'defense' stat_type outside the Big5-combined mode)
MISC_CANON = {
    ("Performance", "TklW"): "tackles_won",
    ("Performance", "Int"): "interceptions",
    ("Performance", "Fls"): "fouls_committed",
}
KEEPER_CANON = {
    ("Performance", "GA"): "goals_against",
    ("Performance", "SoTA"): "shots_on_target_against",
    ("Performance", "Saves"): "saves",
    ("Performance", "Save%"): "save_pct",   # selecting by canon key also drops
    ("Performance", "CS"): "clean_sheets",  # the colliding ('Penalty Kicks','Save%')
    ("Performance", "CS%"): "clean_sheet_pct",
}
EXTRA_STATS_SINCE = 2017  # StatsBomb-era tables; earlier pages not backfilled


def extra_stats(league: str, season: str, stat_type: str, canon: dict,
                refetch: bool = False) -> pd.DataFrame:
    """One extra fbref page -> flat frame keyed (player_name, team, birth_year)."""
    df = pd.read_parquet(
        fetch_fbref_season(league, season, force=refetch, stat_type=stat_type).path
    )
    born = ("born", "")
    keep = [c for c in df.columns if tuple(c) in canon or tuple(c) == born]
    df = df[keep]
    df.columns = [canon.get(tuple(c), "birth_year") for c in keep]
    df = df.reset_index().rename(columns={"player": "player_name"})
    df = df[["player_name", "team", "birth_year", *canon.values()]]
    return df[df["player_name"].notna()].drop_duplicates(
        ["player_name", "team", "birth_year"])


def season_end(season: str) -> str:
    """'2023' (2023-24 season) -> '2024-06-30'."""
    return f"{int(season) + 1}-06-30"


# European seasons start in August, so Jan-Jul still belongs to the year before.
SEASON_START_MONTH = 8


def current_season(today: date | None = None) -> str:
    """Canonical start year of the season in progress: '2026' = 2026-27.

    Derived from the date so the schedule never needs an annual bump.
    """
    d = today or date.today()
    return str(d.year - (1 if d.month < SEASON_START_MONTH else 0))


RATE_COLS = [
    "goals_per90", "assists_per90", "goals_assists_per90",
    "non_penalty_goals_per90", "non_penalty_goals_assists_per90",
    "tackles_interceptions_per90", "save_pct", "clean_sheet_pct",
]
MIN_MINUTES_FOR_RATES = 450  # ponytail: one global floor; 5 full games


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Validity rules applied to every merged frame before caching/pushing.

    - per-90 rates on tiny samples are noise (1 goal in 4 min = 22.5/90),
      so they are nulled below the minutes floor; counting stats stay raw
    - age recomputed from birth_year (fbref snapshots drift by league)
    - value_is_stale: TM stopped revaluing >1yr before season end
    """
    df = df.copy()
    thin = df["minutes"] < MIN_MINUTES_FOR_RATES
    df.loc[thin, [c for c in RATE_COLS if c in df.columns]] = pd.NA

    df["age"] = (df["season"].astype(int) - df["birth_year"]).astype("Int64")
    df["primary_position"] = df["position"].str.split(",").str[0]

    end = pd.to_datetime(df["season"].map(season_end))
    vdate = pd.to_datetime(df["value_date"], errors="coerce")
    df["value_is_stale"] = ((end - vdate).dt.days > 365).fillna(False)
    return df


def build_player_season(
    league: str, season: str, force: bool = False, refetch: bool = False
) -> Manifest:
    """FBref season stats + latest market value on/before season end.

    force rebuilds the merge; refetch additionally re-downloads source data.
    """

    def produce():
        stats = flatten_fbref(
            pd.read_parquet(fetch_fbref_season(league, season, force=refetch).path)
        )
        stats["season"] = season  # canonical start-year label, not fbref's '2324'

        if int(season) >= EXTRA_STATS_SINCE:
            key = ["player_name", "team", "birth_year"]
            for st, canon in (("misc", MISC_CANON), ("keeper", KEEPER_CANON)):
                stats = stats.merge(
                    extra_stats(league, season, st, canon, refetch=refetch),
                    on=key, how="left",
                )
            n90 = stats["nineties"].where(stats["nineties"] > 0)
            stats["tackles_interceptions_per90"] = (
                (stats["tackles_won"].fillna(0) + stats["interceptions"].fillna(0))
                / n90
            ).round(2)
            # absent from the misc page entirely -> unknown, not zero activity
            stats.loc[stats["tackles_won"].isna() & stats["interceptions"].isna(),
                      "tackles_interceptions_per90"] = pd.NA

        xref = pd.read_parquet(build_player_xref(league, season).path).rename(
            columns={"method": "xref_method", "confidence": "xref_confidence"}
        )
        merged = stats.merge(
            xref,
            left_on=["player_name", "team"],
            right_on=["fbref_name", "team"],
            how="left",
        ).drop(columns=["fbref_name"])
        merged["xref_method"] = merged["xref_method"].fillna("unmatched")

        # None = all competitions: valuations are keyed by CURRENT club, so a
        # league filter would drop every player who transferred out since
        vals = pd.read_parquet(fetch_transfermarkt_values(None, force=refetch).path)
        vals = vals[vals["date"] <= season_end(season)]
        latest = (
            vals.sort_values("date")
            .groupby("player_id")
            .tail(1)[["player_id", "date", "market_value_in_eur"]]
            .rename(columns={"date": "value_date"})
        )
        merged = merged.merge(
            latest, left_on="tm_id", right_on="player_id", how="left"
        ).drop(columns=["player_id"])

        # two different players, same name, same team (Adrián López x2,
        # Deportivo 2009): name-keyed xref matched both to one tm_id and the
        # DB primary key rejects the pair. Disambiguate the name with birth
        # year; trust the tm match only for the biggest-minutes row.
        key = ["league", "season", "team", "player_name"]
        dups = merged.duplicated(key, keep=False)
        if dups.any():
            top = merged.loc[dups].groupby(key)["minutes"].transform("max")
            minor = pd.Series(False, index=merged.index)
            minor.loc[dups] = merged.loc[dups, "minutes"] < top
            merged.loc[minor, ["tm_id", "market_value_in_eur", "value_date"]] = pd.NA
            merged.loc[minor, "xref_method"] = "ambiguous"
            merged.loc[minor, "xref_confidence"] = 0.0
            by = merged.loc[dups, "birth_year"].map(
                lambda v: str(int(v)) if pd.notna(v) else "?"  # NA propagates through +
            )
            merged.loc[dups, "player_name"] = (
                merged.loc[dups, "player_name"] + " (" + by + ")"
            )
            # ponytail: same name + team + birth year would still collide;
            # keep the bigger spell if that ever happens
            merged = (
                merged.sort_values("minutes", ascending=False)
                .drop_duplicates(key, keep="first")
                .sort_index()
            )
        return clean(merged)

    return cached_fetch(
        "hub", "player_season", {"league": league, "season": season}, produce, force
    )
