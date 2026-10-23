"""Understat pipelines: xG columns onto player_season + team-match xG table."""
from difflib import SequenceMatcher

import pandas as pd

from soccerhub.pipelines.xref import normalize
from soccerhub.readers.understat import fetch_understat

UNDERSTAT_SINCE = 2014   # no data before 2014-15
FUZZY_FLOOR = 0.90       # stricter than xref's 0.85: no birth-year guard here
# minutes should roughly agree between sources for the same player-stint;
# a bigger gap means we're about to attach the wrong player
MINUTES_GUARD = 450
SUBSET_SCORE = 0.95


def _score(a: str, b: str) -> float:
    """Name similarity for understat <-> hub, within one league-season.

    Deliberately NOT xref's scorer. There, candidates came from a 32k-player
    global registry, so a single-token subset ('Yuri' inside anything) was
    false-positive fuel and the rule demanded >= 2 tokens. Here the pool is
    the ~600 players of one league-season and every candidate has already
    passed the minutes guard, so single-token subsets are the common honest
    case: Understat writes the Spanish short name ('Remiro', 'Raillo') where
    FBref writes the legal name ('Alex Remiro', 'Antonio Raillo').
    """
    ta, tb = set(a.split()), set(b.split())
    if ta <= tb or tb <= ta:
        return SUBSET_SCORE
    return SequenceMatcher(None, a, b).ratio()

XG_COLS = {
    "xg": "xg", "np_xg": "np_xg", "xa": "xa",
    "xg_chain": "xg_chain", "xg_buildup": "xg_buildup",
    "shots": "shots", "key_passes": "key_passes",
    "player_id": "understat_id",
}


def match_players(us: pd.DataFrame, hub: pd.DataFrame,
                  cols: dict[str, str] = XG_COLS) -> pd.DataFrame:
    """Understat player-season rows -> hub player_season identities.

    Ladder (Understat has no birth year, so minutes agreement is the guard):
      1. same normalized name, single row on both sides
      2. duplicated names (mid-season movers: one row per stint, both
         sources) paired greedily by closest minutes
      3. fuzzy name for leftovers, minutes-guarded
    Returns hub key columns + `cols` values (source col -> hub col) for matched rows.
    """
    us = us.reset_index(drop=True)
    hub = hub.reset_index(drop=True)
    us_norm = us["player"].map(normalize)
    hub_norm = hub["player_name"].map(normalize)
    us_min = us["minutes"].fillna(0)
    hub_min = hub["minutes"].fillna(0)

    pairs: list[tuple[int, int]] = []  # (hub_pos, us_pos)
    tied: set[int] = set()  # hub rows rung 2 couldn't decide: rung 3 mustn't guess either
    hub_groups = hub.groupby(hub_norm).groups
    us_groups = us.groupby(us_norm).groups

    for norm, hidx in hub_groups.items():
        uidx = us_groups.get(norm)
        if uidx is None:
            continue
        hidx, uidx = list(hidx), list(uidx)
        if len(hidx) == 1 and len(uidx) == 1:
            # a unique name can still be two people (FBref's starter vs another club's cameo)
            if abs(hub_min[hidx[0]] - us_min[uidx[0]]) <= MINUTES_GUARD:
                pairs.append((hidx[0], uidx[0]))
            continue
        # rung 2: same name several times = separate stints; align by minutes
        remaining = list(uidx)
        for h in sorted(hidx, key=lambda i: -hub_min[i]):
            if not remaining:
                break
            gap = sorted((abs(hub_min[h] - us_min[i]), i) for i in remaining)
            if len(gap) > 1 and gap[0][0] == gap[1][0]:
                tied.add(h)  # two stints equally close: unknowable, so no guess
                continue
            u = gap[0][1]
            if gap[0][0] <= MINUTES_GUARD:
                pairs.append((h, u))
                remaining.remove(u)

    # rung 3: leftovers — short-name/accent drift, minutes-guarded.
    # Ties are rejected, not guessed: two hub players scoring alike (two
    # "Gabriel"s in one league) means we cannot know which, so neither gets
    # the xG rather than one getting someone else's.
    used_h = {h for h, _ in pairs}
    used_u = {u for _, u in pairs}
    left_h = [i for i in hub.index if i not in used_h and i not in tied]
    left_u = [i for i in us.index if i not in used_u]
    # longest-minutes first: the clearest cases claim their partner before
    # the marginal ones can muddy the pool
    for u in sorted(left_u, key=lambda i: -us_min[i]):
        best, best_ratio, runner_up = None, 0.0, 0.0
        for h in left_h:
            if abs(hub_min[h] - us_min[u]) > MINUTES_GUARD:
                continue
            ratio = _score(us_norm[u], hub_norm[h])
            if ratio > best_ratio:
                best, best_ratio, runner_up = h, ratio, best_ratio
            elif ratio > runner_up:
                runner_up = ratio
        if best is not None and best_ratio >= FUZZY_FLOOR and runner_up < best_ratio:
            pairs.append((best, u))
            left_h.remove(best)

    if not pairs:
        return pd.DataFrame(columns=["league", "season", "team", "player_name",
                                     *cols.values()])
    hi = [h for h, _ in pairs]
    ui = [u for _, u in pairs]
    out = hub.loc[hi, ["league", "season", "team", "player_name"]].reset_index(drop=True)
    vals = us.loc[ui, list(cols)].rename(columns=cols).reset_index(drop=True)
    return pd.concat([out, vals], axis=1)


def push_player_xg(league: str, season: str, force: bool = False) -> tuple[int, int]:
    """Understat xG/xA -> existing player_season rows (partial-column upsert).

    Only matched rows are pushed, keyed by the hub's own identity — an
    unmatched Understat row can never create an orphan. Returns
    (matched, understat_total).
    """
    from soccerhub.pipelines import CONFLICT_KEY_PLAYER_SEASON
    from soccerhub.pipelines.query import read_hub
    from soccerhub.pipelines.supa import upsert_df

    if int(season) < UNDERSTAT_SINCE:
        return (0, 0)
    us = pd.read_parquet(
        fetch_understat(league, season, "player_season", force=force).path
    )
    hub = read_hub("player_season", select="league,season,team,player_name,minutes",
                   league=league, season=season)
    matched = match_players(us, hub)
    if len(matched):
        matched = matched.round({c: 3 for c in
                                 ["xg", "np_xg", "xa", "xg_chain", "xg_buildup"]})
        upsert_df(matched, "player_season", CONFLICT_KEY_PLAYER_SEASON)
    return (len(matched), len(us))


TEAM_MATCH_COLS = [
    "game_id", "date", "home_team", "away_team",
    "home_goals", "away_goals", "home_xg", "away_xg",
    "home_np_xg", "away_np_xg", "home_expected_points", "away_expected_points",
    "home_ppda", "away_ppda", "home_deep_completions", "away_deep_completions",
]


def push_team_match(league: str, season: str, force: bool = False) -> int:
    """Understat per-match team xG -> team_match_understat table."""
    from soccerhub.pipelines import TEAM_MATCH_CONFLICT_KEY
    from soccerhub.pipelines.supa import upsert_df

    if int(season) < UNDERSTAT_SINCE:
        return 0
    df = pd.read_parquet(
        fetch_understat(league, season, "team_match", force=force).path
    )
    df = df[TEAM_MATCH_COLS].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df.insert(0, "league", league)
    df.insert(1, "season", season)  # canonical start year, not understat's code
    return upsert_df(df, "team_match_understat", TEAM_MATCH_CONFLICT_KEY)


SHOT_COLS = [
    "shot_id", "game_id", "date", "team", "player", "player_id",
    "assist_player", "assist_player_id", "xg", "location_x", "location_y",
    "minute", "body_part", "situation", "result",
]


def push_shots(league: str, season: str, force: bool = False) -> int:
    """Understat shot events -> shots_understat table (~10.5k rows/league-season).

    Upstream is one page per match, so a fresh fetch takes ~3 min per
    league-season — the slow grain; cron refreshes only the current season.
    """
    from soccerhub.pipelines import SHOTS_CONFLICT_KEY
    from soccerhub.pipelines.supa import upsert_df

    if int(season) < UNDERSTAT_SINCE:
        return 0
    df = pd.read_parquet(fetch_understat(league, season, "shots", force=force).path)
    df = df[SHOT_COLS].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["xg"] = df["xg"].round(4)
    df.insert(0, "league", league)
    df.insert(1, "season", season)  # canonical start year, not understat's code
    return upsert_df(df, "shots_understat", SHOTS_CONFLICT_KEY)
