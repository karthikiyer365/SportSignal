"""Action Score: VAEP value for every on-ball action, rated out-of-fold.

Question: every time a player touched the ball, did his team become more or
less likely to score (or concede) in the next 10 actions, and by how much?
Spec: docs/superpowers/specs/2026-10-01-action-score-design.md
"""
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest
from soccerhub.readers.statsbomb_spadl import fetch_statsbomb_spadl
from soccerhub.readers.wyscout_spadl import fetch_wyscout_spadl

# Every complete top-5 league-season in open event data: (league, season start) -> (provider, ids).
# StatsBomb 2015/16: Bundesliga is Leverkusen-only, so left out. Wyscout 2017/18: all five.
# One model per league-season; providers log events differently, so never compare across them.
LEAGUE_SEASONS = {
    ("ENG-Premier League", "2015"): ("statsbomb", 2, 27),
    ("ESP-La Liga", "2015"): ("statsbomb", 11, 27),
    ("ITA-Serie A", "2015"): ("statsbomb", 12, 27),
    ("FRA-Ligue 1", "2015"): ("statsbomb", 7, 27),
    ("ENG-Premier League", "2017"): ("wyscout", 364, 181150),
    ("ESP-La Liga", "2017"): ("wyscout", 795, 181144),
    ("ITA-Serie A", "2017"): ("wyscout", 524, 181248),
    ("FRA-Ligue 1", "2017"): ("wyscout", 412, 181189),
    ("GER-Bundesliga", "2017"): ("wyscout", 426, 181137),
}
MIN_MINUTES_RANK = 900  # guess, not derived: revisit after the reliability check
MIN_MINUTES_HALF = 450  # reliability check: minutes needed in each fold
# zone grid: 6 bands of 17.5 m along the pitch x 5 lanes cut at the penalty-box and six-yard-box
# edges (wings, half-spaces, centre). After the left->right flip, low y = the team's right flank.
BAND_EDGES = [0, 17.5, 35, 52.5, 70, 87.5, 105]
LANE_EDGES = [0, 13.84, 24.84, 43.16, 54.16, 68]
LANES = ["right-wing", "right-half", "centre", "left-half", "left-wing"]
SITE_DIR = Path(__file__).resolve().parents[4] / "site" / "data" / "action_score"


def site_dir(league: str, season: str) -> Path:
    """One folder per league-season, e.g. site/data/action_score/esp-la-liga-2015."""
    return SITE_DIR / f"{league.lower().replace(' ', '-')}-{season}"


def split_by_game(games: pd.DataFrame) -> pd.Series:
    """Fold 0/1 per game_id: alternate games in date order."""
    order = games.sort_values(["game_date", "game_id"]).game_id.to_numpy()
    return pd.Series(np.arange(len(order)) % 2, index=order, name="fold")


def _states(vaep, games: pd.DataFrame, actions: pd.DataFrame):
    """Features + labels for every action. VAEP works one game at a time."""
    by_id = games.set_index("game_id", drop=False)
    X, y = [], []
    for gid, ga in actions.groupby("game_id", sort=True):
        game = by_id.loc[gid]
        Xg = vaep.compute_features(game, ga)
        X.append(Xg.astype({c: "float32" for c in Xg.select_dtypes("float64").columns}))
        y.append(vaep.compute_labels(game, ga))
    return pd.concat(X, ignore_index=True), pd.concat(y, ignore_index=True)


def rate_out_of_fold(games: pd.DataFrame, actions: pd.DataFrame, learner: str = "xgboost") -> pd.DataFrame:
    """Each game is rated by the model trained on the other fold, so no game grades itself.

    Takes raw SPADL (home attacks ->, away <-): VAEP flips the away team itself.
    """
    from socceraction.vaep import VAEP, formula

    actions = actions.sort_values(["game_id", "action_id"]).reset_index(drop=True)
    X, y = _states(VAEP(), games, actions)
    fold = actions.game_id.map(split_by_game(games)).to_numpy()
    out = actions.assign(
        fold=fold,
        label_scores=y.scores.to_numpy(),
        label_concedes=y.concedes.to_numpy(),
        p_scores=np.nan,
        p_concedes=np.nan,
    )
    np.random.seed(0)  # VAEP.fit draws its early-stopping split from the global RNG; fixed = same rankings each run
    for k in (0, 1):
        model = VAEP().fit(X[fold != k], y[fold != k], learner=learner, fit_params={"verbose": False})
        # ponytail: private call, socceraction has no public predict_proba
        probs = model._estimate_probabilities(X[fold == k])
        out.loc[fold == k, "p_scores"] = probs.scores.to_numpy()
        out.loc[fold == k, "p_concedes"] = probs.concedes.to_numpy()
    # formula.value compares each action with the one before it, so it must run per game
    values = [
        formula.value(ga.reset_index(drop=True), ga.p_scores.reset_index(drop=True),
                      ga.p_concedes.reset_index(drop=True))
        for _, ga in out.groupby("game_id", sort=True)
    ]
    return pd.concat([out, pd.concat(values, ignore_index=True)], axis=1)


def attack_left_to_right(actions: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Flip the away team so every team attacks left->right (how zones and pitch maps read).

    Run AFTER rating: VAEP expects raw orientation and would flip the away team twice.
    """
    from socceraction.spadl import play_left_to_right

    home = games.set_index("game_id").home_team_id
    return pd.concat(
        [play_left_to_right(ga, home[gid]) for gid, ga in actions.groupby("game_id", sort=False)]
    ).loc[actions.index]


UNKNOWN_PLAYER = 0  # Wyscout files unattributed actions under player_id 0: team value, not a player


def player_table(rated: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    """One row per player per team: what he added on the ball, total and per 90."""
    rated, players = rated[rated.player_id != UNKNOWN_PLAYER], players[players.player_id != UNKNOWN_PLAYER]
    minutes = players.groupby(["player_id", "team_id"], as_index=False).agg(
        player_name=("player_name", "first"),
        team_name=("team_name", "first"),
        minutes=("minutes_played", "sum"),
    )
    value = rated.groupby(["player_id", "team_id"], as_index=False).agg(
        n_actions=("vaep_value", "size"), vaep_total=("vaep_value", "sum")
    )
    t = minutes.merge(value, on=["player_id", "team_id"], how="left").fillna(
        {"n_actions": 0, "vaep_total": 0.0}
    )
    t["vaep_per90"] = t.vaep_total / t.minutes.where(t.minutes > 0) * 90
    return t.sort_values("vaep_total", ascending=False, ignore_index=True)


def _points(games: pd.DataFrame) -> pd.Series:
    h, a = games.home_score, games.away_score
    home = pd.Series(np.select([h > a, h == a], [3, 1], 0), index=games.home_team_id)
    away = pd.Series(np.select([a > h, h == a], [3, 1], 0), index=games.away_team_id)
    return pd.concat([home, away]).groupby(level=0).sum().rename("points")


def _reliability(rated: pd.DataFrame, players: pd.DataFrame, games: pd.DataFrame):
    """Spearman of per-90 value, fold 0 vs fold 1, for players with enough minutes in both."""
    fold = split_by_game(games)
    mins = players.assign(fold=players.game_id.map(fold)).groupby(["player_id", "fold"]).minutes_played.sum()
    vaep = rated.groupby(["player_id", "fold"]).vaep_value.sum().reindex(mins.index, fill_value=0.0)
    per90 = (vaep / mins * 90)[mins >= MIN_MINUTES_HALF].unstack("fold").reindex(columns=[0, 1]).dropna()
    if len(per90) < 3:
        return float("nan"), len(per90)
    return per90[0].corr(per90[1], method="spearman"), len(per90)


def validate(rated: pd.DataFrame, games: pd.DataFrame, players: pd.DataFrame) -> dict:
    """Calibration, team sanity, reliability. Says whether the ratings mean anything."""
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import brier_score_loss, roc_auc_score

    ys, yc = rated.label_scores.astype(int), rated.label_concedes.astype(int)
    prob_true, prob_pred = calibration_curve(ys, rated.p_scores, n_bins=10, strategy="quantile")
    team = pd.concat([rated.groupby("team_id").vaep_value.sum(), _points(games)], axis=1, join="inner")
    rel, n = _reliability(rated, players, games)
    return {
        "auc_scores": roc_auc_score(ys, rated.p_scores),
        "brier_scores": brier_score_loss(ys, rated.p_scores),
        "auc_concedes": roc_auc_score(yc, rated.p_concedes),
        "calibration_max_gap": float(np.abs(prob_true - prob_pred).max()),
        "team_spearman": team.vaep_value.corr(team.points, method="spearman"),
        "team_table": team.sort_values("vaep_value", ascending=False),
        "reliability_spearman": rel,
        "reliability_n": n,
    }


def zone_summary(rated: pd.DataFrame) -> pd.DataFrame:
    """Where on the pitch each team gains or loses value: 6 x 5 grid, each zone carrying its rectangle."""
    band = pd.cut(rated.start_x.clip(0, 105), BAND_EDGES, labels=False, include_lowest=True)
    lane = pd.cut(rated.start_y.clip(0, 68), LANE_EDGES, labels=False, include_lowest=True)
    z = rated.assign(band=band, lane=lane).groupby(["team_id", "band", "lane"], as_index=False).agg(
        vaep_total=("vaep_value", "sum"), n_actions=("vaep_value", "size")
    )
    return z.assign(
        zone=z.band.astype(str) + "-" + z.lane.map(dict(enumerate(LANES))),
        x0=z.band.map(BAND_EDGES.__getitem__), x1=(z.band + 1).map(BAND_EDGES.__getitem__),
        y0=z.lane.map(LANE_EDGES.__getitem__), y1=(z.lane + 1).map(LANE_EDGES.__getitem__),
    ).drop(columns=["band", "lane"])


def _player_file(df: pd.DataFrame) -> dict:
    """Every action of one player as columns of plain numbers (~30 bytes per action, not ~140)."""
    types = sorted(df.type_name.unique())
    code = {t: i for i, t in enumerate(types)}
    xy = lambda c: df[c].round().astype(int).tolist()  # 1 m precision is plenty for a pitch map
    return {
        "types": types,
        "g": df.game_id.astype(int).tolist(),
        # football minute: kick-off is 1', second half starts 46'; stoppage time overflows (45+2 -> 47)
        "m": (df.time_seconds // 60 + 1 + 45 * (df.period_id - 1)).astype(int).tolist(),
        "t": df.type_name.map(code).tolist(),
        "r": (df.result_name == "success").astype(int).tolist(),
        "x0": xy("start_x"), "y0": xy("start_y"), "x1": xy("end_x"), "y1": xy("end_y"),
        "v": df.vaep_value.round(3).tolist(),
    }


def export_action_score_site(games, players, rated, table, out_dir) -> dict[str, int]:
    """Write the Team Analysis files for one league-season. Returns bytes per file.

    players / zones / games are small and live in git. player_actions/ holds every action
    (~22 MB per league): git-ignored, served locally, uploaded to Supabase Storage for the live site.
    """
    teams = players.drop_duplicates("team_id").set_index("team_id").team_name
    zones = zone_summary(rated).assign(team_name=lambda d: d.team_id.map(teams))
    played = games.sort_values(["game_date", "game_id"]).assign(
        game_date=lambda d: pd.to_datetime(d.game_date).dt.strftime("%Y-%m-%d"),
        home_team=lambda d: d.home_team_id.map(teams),
        away_team=lambda d: d.away_team_id.map(teams),
    )[["game_id", "game_date", "home_team", "away_team", "home_score", "away_score"]]

    out_dir = Path(out_dir)
    (out_dir / "player_actions").mkdir(parents=True, exist_ok=True)
    sizes = {}
    for name, df in {"players": table, "zones": zones, "games": played}.items():
        path = out_dir / f"{name}.json"
        df.round(4).to_json(path, orient="records")
        sizes[name] = path.stat().st_size
    sizes["player_actions"] = 0
    for pid, df in rated[rated.player_id != UNKNOWN_PLAYER].groupby("player_id"):
        path = out_dir / "player_actions" / f"{int(pid)}.json"
        path.write_text(json.dumps(_player_file(df), separators=(",", ":")))
        sizes["player_actions"] += path.stat().st_size
    return sizes


BUCKET = "action-score"  # public Supabase Storage bucket, created by hand in the dashboard


def _storage():
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]).storage


def upload_player_actions(league_dir) -> int:
    """Upload <league>/player_actions/*.json to the public bucket. Re-runs overwrite. Returns files sent."""
    league_dir = Path(league_dir)
    bucket = _storage().from_(BUCKET)
    files = sorted((league_dir / "player_actions").glob("*.json"))
    for f in files:
        for attempt in range(3):  # a TLS blip over ~4,800 sequential uploads must not end the run
            try:
                bucket.upload(f"{league_dir.name}/player_actions/{f.name}", f.read_bytes(),
                              {"content-type": "application/json", "upsert": "true", "cache-control": "86400"})
                break
            except Exception:  # ponytail: retries every error; a real 403 just fails 3 times, then raises
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
    return len(files)


LIABILITIES = """\
Liabilities (read before quoting any number):
- Model dependence: one model per league-season, one learner (xgboost), 2-fold out-of-fold.
- Provider: StatsBomb (2015/16) and Wyscout (2017/18) log events differently; never compare across.
- Blind spots: undervalues defending; off-ball runs are invisible.
- Team style inflates players: Leicester's counter-attacking shapes their numbers.
- Meaning: "what he added on the ball this season", not "how good he is"."""


def build_action_score(
    competition_id: int = 2, season_id: int = 27, force: bool = False, refetch: bool = False,
    provider: str = "statsbomb",
) -> dict[str, Manifest]:
    """force = re-run the model (minutes); refetch = re-download every game (20-40 min).

    The ratings cache key has no code version: after changing the model, folds or zones, pass force=True.
    """
    fetch = fetch_wyscout_spadl if provider == "wyscout" else fetch_statsbomb_spadl
    src = fetch(competition_id, season_id, refetch)  # provider ids never overlap, so cache keys don't either
    params = {"competition_id": competition_id, "season_id": season_id}
    games = pd.read_parquet(src["games"].path)
    actions_m = cached_fetch(
        "action_score", "actions_vaep", params,
        lambda: attack_left_to_right(rate_out_of_fold(games, pd.read_parquet(src["actions"].path)), games), force,
    )
    return {"games": src["games"], "players": src["players"], "actions_vaep": actions_m}


def selected(only) -> list[tuple[str, str]]:
    """League-seasons to run: league names narrow the leagues AND years narrow the seasons."""
    leagues = {o for o in only if o in {lg for lg, _ in LEAGUE_SEASONS}}
    seasons = {o for o in only if o in {s for _, s in LEAGUE_SEASONS}}
    return [k for k in LEAGUE_SEASONS if (not leagues or k[0] in leagues) and (not seasons or k[1] in seasons)]


def main(force: bool = False, only=(), upload: bool = False):
    """Rate and export every league-season, or only the ones `selected(only)` picks."""
    for league, season in selected(only):
        provider, competition_id, season_id = LEAGUE_SEASONS[(league, season)]
        print(f"\n===== {league} {season}/{int(season[2:]) + 1} ({provider}) =====")
        m = build_action_score(competition_id, season_id, force=force, provider=provider)
        games, players = pd.read_parquet(m["games"].path), pd.read_parquet(m["players"].path)
        rated = pd.read_parquet(m["actions_vaep"].path)
        table = player_table(rated, players)  # one groupby: cheap, so never cached and never stale

        report = validate(rated, games, players)
        for k, v in report.items():
            if k != "team_table":
                print(f"{k:22} {v:.3f}" if isinstance(v, float) else f"{k:22} {v}")
        teams = players.drop_duplicates("team_id").set_index("team_id").team_name
        print(report["team_table"].rename(index=teams).to_string())

        ranked = table[table.minutes >= MIN_MINUTES_RANK].sort_values("vaep_per90", ascending=False)
        print(ranked.head(10).to_string(index=False))
        print("site export bytes:", export_action_score_site(games, players, rated, table, site_dir(league, season)))
        if upload:
            print("uploaded player files:", upload_player_actions(site_dir(league, season)))
    print(LIABILITIES)


if __name__ == "__main__":
    import sys

    # python -m soccerhub.pipelines.action_score [--force] [--upload] ["ESP-La Liga" | 2017 ...]
    main(force="--force" in sys.argv, only=[a for a in sys.argv[1:] if not a.startswith("--")],
         upload="--upload" in sys.argv)
