"""Upsert pipeline outputs into Supabase Postgres (service role, RLS bypassed)."""
import os
import time

import pandas as pd
from supabase import create_client

from soccerhub.manifest import Manifest

CHUNK = 500
CONFLICT_KEY = "league,season,team,player_name"


def push_to_supabase(
    manifest: Manifest, table: str, on_conflict: str = CONFLICT_KEY
) -> int:
    return upsert_df(pd.read_parquet(manifest.path), table, on_conflict)


def upsert_df(df: pd.DataFrame, table: str, on_conflict: str) -> int:
    client = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    )
    df = df.copy()
    for col in df.columns:
        # pandas upcasts nullable ints to float ('25000000.0' breaks bigint
        # columns in postgres) — send whole-number floats back as ints
        if pd.api.types.is_float_dtype(df[col]):
            s = df[col].dropna()
            if len(s) and (s % 1 == 0).all():
                df[col] = df[col].astype("Int64")
    records = df.astype(object).where(pd.notna(df), None).to_dict("records")
    for i in range(0, len(records), CHUNK):
        chunk = records[i : i + CHUNK]
        retry(lambda: client.table(table).upsert(chunk, on_conflict=on_conflict).execute())
    return len(records)


def retry(fn, attempts: int = 3):
    """A TLS blip over hundreds of sequential calls must not end the run. Upserts are idempotent."""
    for attempt in range(attempts):
        try:
            return fn()
        except Exception:  # ponytail: retries every error; a real 403 just fails 3 times, then raises
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)
