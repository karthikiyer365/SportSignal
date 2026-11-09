import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest

# Pre-scraped Transfermarkt valuations (dcaribou/transfermarkt-datasets,
# published on Kaggle; git repo stores data via DVC so raw.githubusercontent 404s).
# Calibration knob: update if the upstream path moves.
TM_VALUATIONS_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/"
    "davidcariboo/player-scores?fileName=player_valuations.csv"
)


TM_PLAYERS_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/"
    "davidcariboo/player-scores?fileName=players.csv"
)

PLAYER_COLS = [
    "player_id", "name", "date_of_birth", "country_of_citizenship",
    "position", "sub_position", "current_club_id", "current_club_name",
    "current_club_domestic_competition_id", "market_value_in_eur",
]


def fetch_transfermarkt_players(competition: str | None, force: bool = False) -> Manifest:
    """Player identity registry (name, DOB, club), optionally one competition.

    Filter uses CURRENT club — pass None (full registry incl. retired players)
    when matching historical seasons.
    """

    def produce():
        df = pd.read_csv(TM_PLAYERS_URL)
        if competition is not None:
            df = df[df["current_club_domestic_competition_id"] == competition]
        return df[PLAYER_COLS].reset_index(drop=True)

    return cached_fetch(
        "transfermarkt",
        "players",
        {"competition": competition or "ALL"},
        produce,
        force,
    )


TM_TRANSFERS_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/"
    "davidcariboo/player-scores?fileName=transfers.csv"
)


def fetch_transfermarkt_transfers(force: bool = False) -> Manifest:
    """All transfer events (fee, from/to club, date), every league."""

    def produce():
        df = pd.read_csv(TM_TRANSFERS_URL)
        df = df.rename(columns={"player_id": "tm_id"})
        # source has a few placeholder rows dated years ahead (contract-end
        # entries, e.g. 2030) — a transfer can't be further out than the
        # upcoming window
        horizon = (pd.Timestamp.now() + pd.DateOffset(months=8)).strftime("%Y-%m-%d")
        df = df[df["transfer_date"] <= horizon]
        # same-day duplicate rows (loan bookkeeping) collide with the
        # (tm_id, transfer_date) primary key downstream
        return df.drop_duplicates(["tm_id", "transfer_date"], keep="last")

    return cached_fetch("transfermarkt", "transfers", {}, produce, force)


def fetch_transfermarkt_values(competition: str | None, force: bool = False) -> Manifest:
    """Player market valuations, optionally filtered to one domestic competition.

    The competition filter uses the player's CURRENT club — fine for live
    squads, wrong for historical seasons (transferred players vanish).
    Pass None for the full valuation history of every player.
    """

    def produce():
        df = pd.read_csv(TM_VALUATIONS_URL)
        if competition is not None:
            df = df[df["player_club_domestic_competition_id"] == competition]
        return df

    return cached_fetch(
        "transfermarkt",
        "valuations",
        {"competition": competition or "ALL"},
        produce,
        force,
    )
