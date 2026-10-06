"""Statcast pitches for the baseball pitch-quality project.

Question: how good is each pitch on physics alone, before the result is known?
Raw pitches stay in the parquet cache; a slim copy per season goes to the public
`statcast` Storage bucket for Colab, and only a season x pitcher x pitch_type
summary goes to Postgres (a raw season would blow the 500 MB free-plan DB cap).
Plan: Baseball Analytics/BASEBALL.md
"""
import io
import os
from calendar import monthrange

import numpy as np
import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.pipelines.supa import retry, upsert_df

SEASONS = range(2020, 2027)  # Hawk-Eye era: spin_axis and arm_angle are reliable from 2020
BUCKET = "statcast"  # public Supabase Storage bucket, created by hand in the dashboard
MIN_PITCHES = 25  # per season x pitcher x pitch_type row in pitch_arsenal
# whiff_pct is null below this: split-half reliability reaches 0.5 at ~50 pitches (notebook chart V4).
# rv_per_100 is never reliable within a season (0.2 at 400 pitches), so it stays as "results", not skill.
MIN_PITCHES_RV = 50
KEY = ["game_pk", "at_bat_number", "pitch_number"]
COLS = KEY + [
    "game_date", "pitcher", "batter", "player_name", "p_throws", "stand", "balls", "strikes",
    "pitch_type", "release_speed", "release_spin_rate", "spin_axis", "pfx_x", "pfx_z",
    "release_pos_x", "release_pos_z", "release_extension", "arm_angle", "plate_x", "plate_z",
    "vx0", "vy0", "vz0", "ax", "ay", "az", "description", "events", "delta_run_exp",
    "estimated_woba_using_speedangle",
]
WHIFFS = {"swinging_strike", "swinging_strike_blocked", "foul_tip"}
SWINGS = WHIFFS | {"foul", "foul_bunt", "hit_into_play", "missed_bunt"}


def fetch_month(year: int, month: int, force: bool = False):
    """One month of raw Statcast (all ~119 cols, every game type). pybaseball's own cache stays off."""
    import pybaseball

    start, end = f"{year}-{month:02d}-01", f"{year}-{month:02d}-{monthrange(year, month)[1]}"
    return cached_fetch("statcast", "pitches", {"year": year, "month": month},
                        lambda: pybaseball.statcast(start, end, verbose=False), force=force)


def load_season(year: int, force: bool = False) -> pd.DataFrame:
    """Regular-season pitches, deduped, slim columns, left-handers mirrored."""
    months = [pd.read_parquet(fetch_month(year, m, force).path) for m in range(3, 12)]
    df = pd.concat([m for m in months if len(m)], ignore_index=True)
    df = df[df.game_type == "R"].drop_duplicates(KEY)
    return normalise_hand(df[COLS].reset_index(drop=True))


def normalise_hand(df: pd.DataFrame) -> pd.DataFrame:
    """Mirror LHP so every pitcher reads as a righty: arm-side is negative x for everyone.

    plate_x and arm_angle stay raw; p_throws is kept so the flip can be undone.
    """
    df = df.copy()
    lhp = df.p_throws == "L"
    for col in ["pfx_x", "release_pos_x", "vx0", "ax"]:
        df.loc[lhp, col] = -df.loc[lhp, col]
    df.loc[lhp, "spin_axis"] = 360 - df.loc[lhp, "spin_axis"]
    return df


def _circular_mean(deg: pd.Series) -> float:
    rad = np.deg2rad(deg.dropna().astype(float))
    return float(np.rad2deg(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean())) % 360) if len(rad) else np.nan


def arsenal(df: pd.DataFrame, season: int) -> pd.DataFrame:
    """season x pitcher x pitch_type summary for the pitch_arsenal table. Expects normalise_hand output."""
    df = df[df.pitch_type.notna()].assign(
        swing=lambda d: d.description.isin(SWINGS),
        whiff=lambda d: d.description.isin(WHIFFS),
        rv=lambda d: -d.delta_run_exp.astype(float),  # delta_run_exp is the batter's view
    )
    g = df.groupby(["pitcher", "pitch_type"])
    out = g.agg(
        pitcher_name=("player_name", "first"), p_throws=("p_throws", "first"), n=("pitch_type", "size"),
        velo=("release_speed", "mean"), spin=("release_spin_rate", "mean"),
        pfx_z=("pfx_z", "mean"), pfx_x=("pfx_x", "mean"),
        release_x=("release_pos_x", "mean"), release_z=("release_pos_z", "mean"),
        extension=("release_extension", "mean"), arm_angle=("arm_angle", "mean"),
        rv=("rv", "mean"), swings=("swing", "sum"), whiffs=("whiff", "sum"),
        xwobacon=("estimated_woba_using_speedangle", "mean"),
    ).reset_index()
    out["spin_axis"] = g.spin_axis.apply(_circular_mean).values
    out["usage_pct"] = out.n / out.groupby("pitcher").n.transform("sum")
    out["ivb_in"], out["hb_arm_in"] = out.pfx_z * 12, -out.pfx_x * 12  # feet -> inches, + = arm side
    out["rv_per_100"] = out.rv * 100  # + = good for the pitcher
    out["whiff_pct"] = (out.whiffs / out.swings.where(out.swings > 0)).where(out.n >= MIN_PITCHES_RV)
    out["season"] = season
    out = out[out.n >= MIN_PITCHES]
    cols = ["season", "pitcher", "pitch_type", "pitcher_name", "p_throws", "n", "usage_pct", "velo", "spin",
            "spin_axis", "ivb_in", "hb_arm_in", "release_x", "release_z", "extension", "arm_angle",
            "rv_per_100", "whiff_pct", "xwobacon"]
    return out[cols].astype({c: "float64" for c in cols[5:] if c != "n"}).reset_index(drop=True)


def upload_season(df: pd.DataFrame, season: int) -> int:
    """Slim float32 parquet per month to the public bucket at pitches/<season>/<MM>.parquet.

    One file per month (~7 MB) because a full season (~50 MB) hits the free plan's 50 MB file limit.
    Colab reads them with pd.read_parquet(public_url). Returns total bytes sent.
    """
    from supabase import create_client

    floats = df.select_dtypes("number").columns.difference(KEY + ["pitcher", "batter", "balls", "strikes"])
    df = df.astype({c: "float32" for c in floats})
    bucket = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]).storage.from_(BUCKET)
    sent = 0
    for month, part in df.groupby(pd.to_datetime(df.game_date).dt.month):
        buf = io.BytesIO()
        part.to_parquet(buf, compression="zstd", index=False)
        body = buf.getvalue()
        retry(lambda: bucket.upload(f"pitches/{season}/{month:02d}.parquet", body,
                                    {"content-type": "application/octet-stream", "upsert": "true"}))
        sent += len(body)
    return sent


def main(seasons, force: bool = False, upload: bool = False) -> None:
    for season in seasons:
        df = load_season(season, force)
        ars = arsenal(df, season)
        print(f"{season}: {len(df):,} pitches, {len(ars):,} arsenal rows")
        if upload:
            print("  parquet MB:", round(upload_season(df, season) / 1e6, 1))
            print("  pitch_arsenal rows:", upsert_df(ars, "pitch_arsenal", "season,pitcher,pitch_type"))


if __name__ == "__main__":
    import sys

    # python -m soccerhub.pipelines.statcast [--force] [--upload] [2024 2025 ...]   (default: 2020-2026)
    years = [int(a) for a in sys.argv[1:] if not a.startswith("--")] or list(SEASONS)
    main(years, force="--force" in sys.argv, upload="--upload" in sys.argv)
