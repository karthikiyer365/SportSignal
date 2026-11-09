"""Match results (goals, shots, cards, corners) from football-data.co.uk."""
import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest

# football-data.co.uk's own division codes for the Big 5 — no more, no less
DIV = {
    "ENG-Premier League": "E0",
    "ESP-La Liga": "SP1",
    "GER-Bundesliga": "D1",
    "ITA-Serie A": "I1",
    "FRA-Ligue 1": "F1",
}

MATCH_COLS = {
    "Date": "date", "HomeTeam": "home_team", "AwayTeam": "away_team",
    "FTHG": "home_goals", "FTAG": "away_goals", "FTR": "result",
    "HTHG": "home_goals_ht", "HTAG": "away_goals_ht", "HTR": "result_ht",
    "Referee": "referee",
    "HS": "home_shots", "AS": "away_shots",
    "HST": "home_shots_on_target", "AST": "away_shots_on_target",
    "HF": "home_fouls", "AF": "away_fouls",
    "HC": "home_corners", "AC": "away_corners",
    "HY": "home_yellow", "AY": "away_yellow",
    "HR": "home_red", "AR": "away_red",
}


def fetch_match_history(league: str, season: str, force: bool = False) -> Manifest:
    """One league-season of match results from football-data.co.uk.

    ``season`` is the canonical start year ('2023' = 2023-24 season), same
    scheme fbref uses. Plain CSV download — no browser automation, and
    deliberately not soccerdata's own MatchHistory reader: its bundled TLS
    client gets a 503 from this host, while a bare pandas.read_csv doesn't.
    """

    def produce():
        y = int(season)
        code = f"{y % 100:02d}{(y + 1) % 100:02d}"
        url = f"https://www.football-data.co.uk/mmz4281/{code}/{DIV[league]}.csv"
        df = pd.read_csv(url)
        keep = [c for c in MATCH_COLS if c in df.columns]
        df = df[keep].rename(columns=MATCH_COLS)
        # football-data uses DD/MM/YY pre-~2019, DD/MM/YYYY after — consistent
        # within one season's file, so sniff it from the first date once
        fmt = "%d/%m/%y" if len(str(df["date"].iloc[0])) <= 8 else "%d/%m/%Y"
        df["date"] = pd.to_datetime(df["date"], format=fmt).dt.strftime("%Y-%m-%d")
        return df.dropna(subset=["home_team", "away_team"])

    return cached_fetch(
        "matchhistory", "matches", {"league": league, "season": season}, produce, force
    )
