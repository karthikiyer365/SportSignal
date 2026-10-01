"""Action Score: VAEP value for every on-ball action, rated out-of-fold.

Question: every time a player touched the ball, did his team become more or
less likely to score (or concede) in the next 10 actions, and by how much?
Spec: docs/superpowers/specs/2026-10-01-action-score-design.md
"""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest
from soccerhub.readers.statsbomb_spadl import fetch_statsbomb_spadl

# StatsBomb open data's complete 2015/16 leagues (ids verified 2026-10-01).
# Bundesliga 2015/16 is Leverkusen-only, so it's left out. Each league gets its own model.
LEAGUES_2015 = {
    "ENG-Premier League": (2, 27),
    "ESP-La Liga": (11, 27),
    "ITA-Serie A": (12, 27),
    "FRA-Ligue 1": (7, 27),
}
MIN_MINUTES_RANK = 900  # guess, not derived: revisit after the reliability check
MIN_MINUTES_HALF = 450  # reliability check: minutes needed in each fold
THIRDS = ["own", "middle", "attacking"]
LANES = ["right", "centre", "left"]  # after left->right flip, low y = right flank (checked on 5 games)
SITE_DIR = Path(__file__).resolve().parents[4] / "site" / "data" / "action_score"


def site_dir(league: str, season: str = "2015") -> Path:
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


def add_zone(actions: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Flip the away team so every team attacks left->right, then tag 9 pitch zones:
    third (by start_x) x lane (by start_y), e.g. 'attacking-left'.

    Run AFTER rating: VAEP expects raw orientation and would flip the away team twice.
    """
    from socceraction.spadl import play_left_to_right

    home = games.set_index("game_id").home_team_id
    out = pd.concat(
        [play_left_to_right(ga, home[gid]) for gid, ga in actions.groupby("game_id", sort=False)]
    ).loc[actions.index]
    third = pd.cut(out.start_x.clip(0, 105), [0, 35, 70, 105], labels=THIRDS, include_lowest=True)
    lane = pd.cut(out.start_y.clip(0, 68), [0, 68 / 3, 2 * 68 / 3, 68], labels=LANES, include_lowest=True)
    return out.assign(start_zone=third.astype(str) + "-" + lane.astype(str))


def player_table(rated: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    """One row per player per team: what he added on the ball, total and per 90."""
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
    """Where on the pitch each team gains or loses value."""
    return rated.groupby(["team_id", "start_zone"], as_index=False).agg(
        vaep_total=("vaep_value", "sum"), n_actions=("vaep_value", "size")
    )


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


def export_action_score_site(games, players, rated, table, out_dir=SITE_DIR) -> dict[str, int]:
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
    for pid, df in rated.groupby("player_id"):
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
        bucket.upload(f"{league_dir.name}/player_actions/{f.name}", f.read_bytes(),
                      {"content-type": "application/json", "upsert": "true", "cache-control": "86400"})
    return len(files)


LIABILITIES = """\
Liabilities (read before quoting any number):
- Model dependence: one StatsBomb season, one learner (xgboost), 2-fold out-of-fold.
- Blind spots: undervalues defending; off-ball runs are invisible.
- Team style inflates players: Leicester's counter-attacking shapes their numbers.
- Meaning: "what he added on the ball this season", not "how good he is"."""


def build_action_score(
    competition_id: int = 2, season_id: int = 27, force: bool = False, refetch: bool = False
) -> dict[str, Manifest]:
    """force = re-run the model (minutes); refetch = re-download every game (20-40 min).

    The ratings cache key has no code version: after changing the model, folds or zones, pass force=True.
    """
    src = fetch_statsbomb_spadl(competition_id, season_id, refetch)
    params = {"competition_id": competition_id, "season_id": season_id}
    games = pd.read_parquet(src["games"].path)
    actions_m = cached_fetch(
        "action_score", "actions_vaep", params,
        lambda: add_zone(rate_out_of_fold(games, pd.read_parquet(src["actions"].path)), games), force,
    )
    return {"games": src["games"], "players": src["players"], "actions_vaep": actions_m}


def main(force: bool = False, leagues=None, upload: bool = False):
    for league in leagues or LEAGUES_2015:
        print(f"\n===== {league} 2015/16 =====")
        competition_id, season_id = LEAGUES_2015[league]
        m = build_action_score(competition_id, season_id, force=force)
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
        print("site export bytes:", export_action_score_site(games, players, rated, table, site_dir(league)))
        if upload:
            print("uploaded player files:", upload_player_actions(site_dir(league)))
    print(LIABILITIES)


if __name__ == "__main__":
    import sys

    # python -m soccerhub.pipelines.action_score [--force] [--upload] ["ESP-La Liga" ...]
    main(force="--force" in sys.argv, leagues=[a for a in sys.argv[1:] if a in LEAGUES_2015],
         upload="--upload" in sys.argv)
