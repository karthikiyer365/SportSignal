"""FotMob ISL data (plain HTTP JSON, no key). Unofficial API: cache everything.

Raw payloads are kept gzipped under the local cache and, for matches, archived to
the private `fotmob` Storage bucket so a FotMob change or block can't lose history.
"""
import gzip
import json
import os
import time
import urllib.parse
import urllib.request

from soccerhub.cache import cache_root
from soccerhub.pipelines.supa import retry

ISL_ID = 9478
BASE = "https://www.fotmob.com/api/data"
BUCKET = "fotmob"
MIN_GAP_S = 2.0  # one request at a time, politely spaced
UA = "Mozilla/5.0 (Macintosh) Chrome/126"
_last_call = 0.0


def fotmob_season(season: str) -> str:
    """Hub start-year season '2024' -> FotMob label '2024/2025'."""
    return f"{season}/{int(season) + 1}"


def _get_json(url: str) -> dict:
    global _last_call
    time.sleep(max(0.0, _last_call + MIN_GAP_S - time.monotonic()))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    finally:
        _last_call = time.monotonic()


def _raw_path(name: str):
    return cache_root() / "fotmob" / "raw" / f"{name}.json.gz"


def _cached(name: str, url: str, force: bool) -> tuple[dict, bytes | None]:
    """(payload, gz bytes if freshly downloaded else None)."""
    path = _raw_path(name)
    if path.exists() and not force:
        return json.loads(gzip.decompress(path.read_bytes())), None
    data = retry(lambda: _get_json(url))
    gz = gzip.compress(json.dumps(data).encode())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gz)
    return data, gz


def _archive(match_id: int, season: str, gz: bytes) -> None:
    from supabase import create_client

    bucket = create_client(os.environ["SUPABASE_URL"],
                           os.environ["SUPABASE_SERVICE_ROLE_KEY"]).storage.from_(BUCKET)
    retry(lambda: bucket.upload(f"isl/{season}/{match_id}.json.gz", gz,
                                {"content-type": "application/gzip", "upsert": "true"}))


def fetch_league(season: str | None = None, force: bool = False) -> dict:
    """ISL season payload: fixtures (match ids, status), table, available seasons.

    season=None is FotMob's current season (allAvailableSeasons[0] names it).
    """
    params = {"id": ISL_ID} | ({"season": fotmob_season(season)} if season else {})
    url = f"{BASE}/leagues?{urllib.parse.urlencode(params)}"
    return _cached(f"league_{season or 'current'}", url, force)[0]


def fetch_match(match_id: int, season: str, force: bool = False,
                archive: bool = True) -> dict:
    """matchDetails payload: shotmap, playerStats, lineup, team stats, events."""
    data, gz = _cached(f"match_{match_id}", f"{BASE}/matchDetails?matchId={match_id}", force)
    if archive and gz is not None:
        _archive(match_id, season, gz)
    return data


def finished_match_ids(league_payload: dict) -> list[int]:
    return [int(m["id"]) for m in league_payload["fixtures"]["allMatches"]
            if m["status"].get("finished") and not m["status"].get("cancelled")]
