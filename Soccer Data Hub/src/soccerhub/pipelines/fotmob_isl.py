"""ISL from FotMob -> matches, team_match_understat, shots_understat, player_match,
player_season. Vocab is mapped onto Understat's strings so existing filters work;
xG is FotMob's model, not Understat's — never compare across leagues unfiltered.
"""
import pandas as pd

# safe at module level: pipelines/__init__ defines its constants before bottom-importing us
from soccerhub.pipelines import ISL_LEAGUE as LEAGUE

POSITION = {0: "GK", 1: "DF", 2: "MF", 3: "FW"}  # FotMob usualPlayingPositionId
PITCH_X, PITCH_Y = 105, 68

RESULT = {"Goal": "Goal", "Miss": "Missed Shot", "Post": "Shot On Post"}
SITUATION = {"RegularPlay": "Open Play", "FastBreak": "Open Play", "FromCorner": "From Corner",
             "SetPiece": "Set Piece", "ThrowInSetPiece": "Set Piece",
             "FreeKick": "Direct Freekick", "Penalty": "Penalty"}
BODY = {"RightFoot": "Right Foot", "LeftFoot": "Left Foot", "Header": "Head"}

# player_match column -> FotMob playerStats inner key
PLAYER_STATS = {
    "minutes": "minutes_played", "rating": "rating_title", "goals": "goals",
    "assists": "assists", "xg": "expected_goals", "xgot": "expected_goals_on_target_variant",
    "xa": "expected_assists", "np_xg": "expected_goals_non_penalty", "shots": "total_shots",
    "shots_on_target": "ShotsOnTarget", "big_chances_missed": "big_chance_missed_title",
    "chances_created": "chances_created", "accurate_passes": "accurate_passes",
    "passes_final_third": "passes_into_final_third", "accurate_long_balls": "long_balls_accurate",
    "touches": "touches", "touches_opp_box": "touches_opp_box", "dribbles": "dribbles_succeeded",
    "dispossessed": "dispossessed", "tackles": "matchstats.headers.tackles",
    "interceptions": "interceptions", "clearances": "clearances", "blocks": "shot_blocks",
    "recoveries": "recoveries", "dribbled_past": "dribbled_past", "duels_won": "duel_won",
    "duels_lost": "duel_lost", "aerials_won": "aerials_won", "ground_duels_won": "ground_duels_won",
    "fouls_committed": "fouls", "was_fouled": "was_fouled", "saves": "saves",
    "goals_conceded": "goals_conceded",
}


def _result(home: int, away: int) -> str:
    return "H" if home > away else "A" if away > home else "D"


def _team_stats(content: dict) -> dict[str, list]:
    """key -> [home, away]; first occurrence wins (FotMob repeats keys across groups)."""
    out: dict[str, list] = {}
    for group in content["stats"]["Periods"]["All"]["stats"]:
        for row in group["stats"]:
            out.setdefault(row.get("key"), row.get("stats"))
    return out


def _num(v):
    return None if v in (None, "") else float(v)


def _player_stats(p: dict) -> dict:
    by_key = {s.get("key"): s.get("stat", {}) for g in p["stats"] for s in g["stats"].values()}
    row = {col: by_key.get(k, {}).get("value") for col, k in PLAYER_STATS.items()}
    row["passes"] = by_key.get("accurate_passes", {}).get("total")
    return row


def _sider(team_ids: set, home_id: int, away_id: int):
    """FotMob team id -> is_home. FotMob sometimes tags one side with a junk id (SC Delhi
    2025: shots -1, players 0); a junk id then means the side whose real id is absent."""
    present = team_ids & {home_id, away_id}
    junk_is_home = home_id not in present if len(present) == 1 else None

    def is_home(tid: int) -> bool:
        if tid in (home_id, away_id):
            return tid == home_id
        if junk_is_home is None:
            raise ValueError(f"can't place FotMob team id {tid} (home {home_id}, away {away_id})")
        return junk_is_home
    return is_home


def parse_match(raw: dict, season: str, league: str = LEAGUE,
                team_names: dict[int, str] | None = None) -> dict[str, pd.DataFrame]:
    """One matchDetails payload -> rows for each hub table, keyed and ready to upsert."""
    c = raw["content"]
    match_id = int(raw["general"]["matchId"])
    date = raw["general"]["matchTimeUTCDate"][:10]
    home, away = raw["header"]["teams"]
    # default: name as of that match (ISL 2021 Hyderabad FC, not SC Delhi). team_names
    # overrides by FotMob team id (Big-5: headers drift 'Freiburg'/'SC Freiburg' mid-season)
    name = {t["id"]: (team_names or {}).get(t["id"], t["name"]) for t in (home, away)}
    hn, an = name[home["id"]], name[away["id"]]
    key = {"league": league, "season": season}
    events = c["matchFacts"]["events"]["events"]
    starters = {p["id"] for t in ("homeTeam", "awayTeam") for p in c["lineup"][t]["starters"]}
    cards = pd.DataFrame([(e["player"]["id"], e.get("card")) for e in events
                          if e["type"] == "Card" and e.get("player")], columns=["pid", "card"])
    # FotMob occasionally has no player stats for a played match (4205608): no rows, not a crash
    played = [(p, st) for p in (c["playerStats"] or {}).values()
              if (st := _player_stats(p))["minutes"]]  # drops unused subs (some lack a teamId)
    player_home = _sider({p["teamId"] for p, _ in played}, home["id"], away["id"])
    rows = []
    for p, st in played:
        is_home = player_home(p["teamId"])
        mine = cards[cards.pid == p["id"]].card
        rows.append({
            **key, "match_id": match_id, "fotmob_id": p["id"], "date": date,
            "team": hn if is_home else an, "opponent": an if is_home else hn, "is_home": is_home,
            "player_name": p["name"], "position": POSITION.get(p.get("usualPosition")),
            "is_starter": p["id"] in starters, **st,
            "yellow_cards": int((mine == "Yellow").sum()), "red_cards": int(mine.isin(["Red", "YellowRed"]).sum()),
        })
    player_match = pd.DataFrame(rows)
    if league != LEAGUE:  # Big-5 stores player_match only: don't fail on frames we'd discard
        return {"player_match": player_match}

    ht = next((e for e in events if e["type"] == "Half" and e.get("halfStrShort") == "HT"), None)
    ts = _team_stats(c)

    def pair(k):
        return [_num(v) for v in ts.get(k) or [None, None]]

    shots_ha, sot, corners = pair("total_shots"), pair("ShotsOnTarget"), pair("corners")
    fouls, yellow, red = pair("fouls"), pair("yellow_cards"), pair("red_cards")
    referee = (c["matchFacts"]["infoBox"].get("Referee") or {}).get("text") or None
    matches = pd.DataFrame([{
        **key, "date": date, "home_team": hn, "away_team": an,
        "home_goals": home["score"], "away_goals": away["score"],
        "result": _result(home["score"], away["score"]),
        "home_goals_ht": ht and ht["homeScore"], "away_goals_ht": ht and ht["awayScore"],
        "result_ht": ht and _result(ht["homeScore"], ht["awayScore"]),
        "referee": referee,
        "home_shots": shots_ha[0], "away_shots": shots_ha[1],
        "home_shots_on_target": sot[0], "away_shots_on_target": sot[1],
        "home_fouls": fouls[0], "away_fouls": fouls[1],
        "home_corners": corners[0], "away_corners": corners[1],
        "home_yellow": yellow[0], "away_yellow": yellow[1],
        "home_red": red[0], "away_red": red[1],
    }])

    xg, npxg, poss = pair("expected_goals"), pair("expected_goals_non_penalty"), pair("BallPossesion")
    team_match = pd.DataFrame([{
        **key, "game_id": match_id, "date": date, "home_team": hn, "away_team": an,
        "home_goals": home["score"], "away_goals": away["score"],
        "home_xg": xg[0], "away_xg": xg[1], "home_np_xg": npxg[0], "away_np_xg": npxg[1],
        "home_possession": poss[0], "away_possession": poss[1],
    }])

    shot_home = _sider({s["teamId"] for s in c["shotmap"]["shots"]}, home["id"], away["id"])
    shots = pd.DataFrame([{
        **key, "shot_id": s["id"], "game_id": match_id, "date": date,
        "team": hn if shot_home(s["teamId"]) else an, "player": s["playerName"], "player_id": s["playerId"],
        "xg": s.get("expectedGoals"), "xgot": s.get("expectedGoalsOnTarget"),
        # FotMob always draws the shooting team attacking toward x=105
        "location_x": s["x"] / PITCH_X, "location_y": s["y"] / PITCH_Y,
        "minute": s["min"], "body_part": BODY.get(s.get("shotType")),
        "situation": SITUATION.get(s.get("situation"), s.get("situation")),
        "result": "Own Goal" if s.get("isOwnGoal") else
                  ("Blocked Shot" if s.get("isBlocked") else "Saved Shot")
                  if s["eventType"] == "AttemptSaved" else RESULT.get(s["eventType"], s["eventType"]),
    } for s in c["shotmap"]["shots"] if s.get("period") != "PenaltyShootout"])  # kicks aren't shots

    return {"matches": matches, "team_match": team_match, "shots": shots,
            "player_match": player_match}


# player_match column -> player_season column, summed per player-team-season
SEASON_SUMS = {
    "minutes": "minutes", "goals": "goals", "assists": "assists",
    "yellow_cards": "yellow_cards", "red_cards": "red_cards",
    "xg": "xg", "np_xg": "np_xg", "xa": "xa", "xgot": "xgot", "shots": "shots",
    "chances_created": "key_passes", "tackles": "tackles_won", "interceptions": "interceptions",
    "fouls_committed": "fouls_committed", "saves": "saves", "goals_conceded": "goals_against",
    "touches_opp_box": "touches_opp_box", "dribbles": "dribbles", "recoveries": "recoveries",
    "clearances": "clearances", "blocks": "blocks", "aerials_won": "aerials_won",
    "duels_won": "duels_won", "passes_final_third": "passes_final_third",
    "accurate_passes": "accurate_passes",
}
KEY = ["league", "season", "team", "player_name"]


def season_rows(pm: pd.DataFrame, shots: pd.DataFrame) -> pd.DataFrame:
    """player_match rows -> player_season rows (one per player-team-season)."""
    # offset paging in read_hub has no ORDER BY, so a page boundary can repeat a row
    pm = pm.drop_duplicates(["league", "season", "match_id", "fotmob_id"])
    num = [*SEASON_SUMS, "rating"]
    pm = pm.assign(**{c: pd.to_numeric(pm[c]) for c in num})  # all-null cols arrive as object
    pm = pm.assign(_rw=pm["rating"] * pm["minutes"],
                   _rm=pm["minutes"].where(pm["rating"].notna()),  # cameos often go unrated
                   _cs=(pm["position"] == "GK") & (pm["goals_conceded"] == 0))
    out = pm.groupby(KEY).agg(
        **{c: (c, lambda s: s.sum(min_count=1)) for c in [*SEASON_SUMS, "_rw", "_rm", "_cs"]},
        matches_played=("match_id", "nunique"), starts=("is_starter", "sum"),
        fotmob_id=("fotmob_id", "first"),
        primary_position=("position", lambda s: s.mode().iat[0] if s.notna().any() else None),
    ).reset_index().rename(columns=SEASON_SUMS)
    out["position"] = out["primary_position"]
    out["fotmob_rating"] = out.pop("_rw") / out.pop("_rm")
    out["clean_sheets"] = out.pop("_cs").where(out["primary_position"] == "GK")

    pens = shots[shots["situation"] == "Penalty"].groupby(["player_id", "team"]).agg(
        penalties_attempted=("result", "size"),
        penalties_scored=("result", lambda r: (r == "Goal").sum()))
    out = out.join(pens, on=["fotmob_id", "team"])
    pen_cols = ["penalties_attempted", "penalties_scored"]
    out[pen_cols] = out[pen_cols].astype(float).fillna(0).astype(int)  # empty join is object dtype

    a = out["assists"].fillna(0)
    out["nineties"] = (out["minutes"] / 90).round(1)
    out["goals_assists"] = out["goals"] + a
    out["non_penalty_goals"] = out["goals"] - out["penalties_scored"]
    per90 = out["minutes"].where(out["minutes"] > 0) / 90
    out["goals_per90"] = out["goals"] / per90
    out["assists_per90"] = out["assists"] / per90
    out["goals_assists_per90"] = out["goals_assists"] / per90
    out["non_penalty_goals_per90"] = out["non_penalty_goals"] / per90
    out["non_penalty_goals_assists_per90"] = (out["non_penalty_goals"] + a) / per90
    out["tackles_interceptions_per90"] = (out["tackles_won"] + out["interceptions"]) / per90
    out["save_pct"] = out["saves"] / (out["saves"] + out["goals_against"]).where(lambda s: s > 0)
    return out


def push_fotmob(league: str, season: str, force: bool = False,
                match_ids: list[int] | None = None) -> dict[str, int]:
    """One league-season (or just `match_ids`) from FotMob. Rows upserted per table.

    ISL writes all five hub tables. Big-5 writes player_match only: their matches, shots
    and season rows already come from football-data / Understat / FBref, and FotMob's
    different ids and spellings would duplicate them.
    """
    from soccerhub import pipelines as P
    from soccerhub.pipelines import query, supa
    from soccerhub.readers import fotmob as fm  # call-time: readers.fotmob imports pipelines.supa

    payload = fm.fetch_league(league, season, force=force)
    if match_ids is None:
        match_ids = fm.finished_match_ids(payload)
    # Big-5: one name per club per season, from the fixture list. ISL keeps per-match header
    # names (its fixture lists show today's name for past seasons: SC Delhi, not Hyderabad FC)
    names = None if league == LEAGUE else {int(m[side]["id"]): m[side]["name"]
                                           for m in payload["fixtures"]["allMatches"]
                                           for side in ("home", "away")}
    parts = [parse_match(fm.fetch_match(i, season, league, force=force), season, league, names)
             for i in match_ids]
    tables = [("player_match", "player_match", P.PLAYER_MATCH_CONFLICT_KEY)]
    if league == LEAGUE:
        tables += [("matches", "matches", P.MATCHES_CONFLICT_KEY),
                   ("team_match", "team_match_understat", P.TEAM_MATCH_CONFLICT_KEY),
                   ("shots", "shots_understat", P.SHOTS_CONFLICT_KEY)]
    out = {}
    for part, table, key in tables:
        df = pd.concat([p[part] for p in parts], ignore_index=True) if parts else pd.DataFrame()
        if len(df):
            out[table] = supa.upsert_df(df, table, key)
    if league != LEAGUE:
        return out
    # ISL season totals from the whole stored season, not just this batch
    pm = query.read_hub("player_match", league=league, season=season)
    shots = query.read_hub("shots_understat", select="player_id,team,situation,result",
                           league=league, season=season)
    if len(pm):
        out["player_season"] = supa.upsert_df(season_rows(pm, shots), "player_season",
                                              P.CONFLICT_KEY_PLAYER_SEASON)
    return out


def push_fotmob_new(league: str) -> dict[str, int]:
    """Weekly job: current season, only finished matches not yet in player_match.

    Season comes from FotMob, not current_season(): ISL 2025/26 started in Feb 2026.
    Always calls push_fotmob, so ISL season totals rebuild (self-heal) even with nothing new.
    """
    from soccerhub.pipelines import query
    from soccerhub.readers import fotmob as fm

    payload = fm.fetch_league(league, force=True)
    season = payload["allAvailableSeasons"][0][:4]
    stored = set(query.read_hub("player_match", select="match_id",
                                league=league, season=season).get("match_id", []))
    new = [i for i in fm.finished_match_ids(payload) if i not in stored]
    return push_fotmob(league, season, match_ids=new)


def link_ids(us: pd.DataFrame, league: str, season: str, cols: dict[str, str]) -> tuple[int, int]:
    """Set a source's player id on existing Big-5 player_season rows. Returns (linked, hub_rows).

    `us`: one row per source player-stint (player, minutes, id column). Reuses the Understat
    matcher (name, then movers by minutes, then fuzzy with a minutes guard; ties rejected).
    Team names aren't compared: each source spells clubs differently, minutes separate them.
    """
    from soccerhub import pipelines as P
    from soccerhub.pipelines import query, supa
    from soccerhub.pipelines.understat import match_players

    hub = query.read_hub("player_season", select="league,season,team,player_name,minutes",
                         league=league, season=season)
    if us.empty or hub.empty:
        return (0, len(hub))
    matched = match_players(us, hub, cols=cols)
    if len(matched):
        supa.upsert_df(matched, "player_season", P.CONFLICT_KEY_PLAYER_SEASON)
    return (len(matched), len(hub))


def link_fotmob(league: str, season: str) -> tuple[int, int]:
    """Big-5: player_season.fotmob_id from stored player_match minutes."""
    from soccerhub.pipelines import query

    pm = query.read_hub("player_match", select="match_id,fotmob_id,team,player_name,minutes",
                        league=league, season=season)
    # offset paging in read_hub has no ORDER BY: a repeated row would add a match's minutes
    us = pm if pm.empty else (
        pm.drop_duplicates(["match_id", "fotmob_id"]).groupby(["fotmob_id", "team"], as_index=False)
          .agg(player=("player_name", "first"), minutes=("minutes", "sum")))
    return link_ids(us, league, season, {"fotmob_id": "fotmob_id"})


def push_isl(season: str, force: bool = False, match_ids: list[int] | None = None) -> dict[str, int]:
    return push_fotmob(LEAGUE, season, force, match_ids)


def push_isl_new() -> dict[str, int]:
    return push_fotmob_new(LEAGUE)


if __name__ == "__main__":
    # python -m soccerhub.pipelines.fotmob_isl eng 2021 2022 2023 2024 2025 2026
    import sys

    from soccerhub.readers.fotmob import SLUGS

    league = {v: k for k, v in SLUGS.items()}[sys.argv[1]]
    for s in sys.argv[2:]:
        print(s, push_fotmob(league, s), flush=True)
        if league != LEAGUE:
            print(s, "link", link_fotmob(league, s), flush=True)
