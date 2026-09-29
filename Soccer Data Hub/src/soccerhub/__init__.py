"""soccerhub — unified fetch layer for open-source soccer data."""

from soccerhub.agent import ask
from soccerhub.errors import SoccerhubError
from soccerhub.manifest import Manifest
from soccerhub.readers.clubelo import fetch_club_elo_history, fetch_club_elo_snapshot
from soccerhub.readers.fbref import fetch_fbref_season
from soccerhub.readers.matchhistory import fetch_match_history
from soccerhub.readers.statsbomb import fetch_statsbomb_events
from soccerhub.readers.transfermarkt import (
    fetch_transfermarkt_players,
    fetch_transfermarkt_transfers,
    fetch_transfermarkt_values,
)
from soccerhub.readers.understat import fetch_understat
from soccerhub.pipelines import (
    build_player_season,
    build_player_xref,
    current_season,
    push_age_curve,
    push_club_elo,
    push_club_elo_history,
    push_matches,
    push_player_xg,
    push_shots,
    push_team_match,
    push_to_supabase,
    push_transfers,
    read_hub,
    run_season,
)

__all__ = [
    "ask",
    "SoccerhubError",
    "Manifest",
    "fetch_club_elo_history",
    "fetch_club_elo_snapshot",
    "fetch_fbref_season",
    "fetch_match_history",
    "fetch_statsbomb_events",
    "fetch_transfermarkt_players",
    "fetch_transfermarkt_transfers",
    "fetch_transfermarkt_values",
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
    "fetch_understat",
    "read_hub",
    "run_season",
]
