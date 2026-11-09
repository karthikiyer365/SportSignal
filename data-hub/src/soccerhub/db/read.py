"""Read path: Supabase is the source of truth for all downstream phases.

Reads use the anon (publishable) key — RLS makes them select-only.
"""
import json
import os
import urllib.parse
import urllib.request

import pandas as pd

PAGE = 1000  # PostgREST default max-rows


def read_hub(table: str, select: str = "*", **eq_filters) -> pd.DataFrame:
    """Fetch a whole table (or filtered slice) from Supabase as a DataFrame.

    read_hub("player_season", league="ITA-Serie A", season="2023")
    """
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_PUBLISHABLE_KEY"]
    params = [("select", select)] + [(k, f"eq.{v}") for k, v in eq_filters.items()]
    rows: list = []
    offset = 0
    while True:
        q = urllib.parse.urlencode(
            params + [("offset", str(offset)), ("limit", str(PAGE))]
        )
        req = urllib.request.Request(
            f"{base}/rest/v1/{table}?{q}", headers={"apikey": key}
        )
        chunk = json.load(urllib.request.urlopen(req))
        rows += chunk
        if len(chunk) < PAGE:
            return pd.DataFrame(rows)
        offset += PAGE
