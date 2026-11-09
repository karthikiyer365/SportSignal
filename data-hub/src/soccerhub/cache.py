import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from soccerhub.errors import SoccerhubError
from soccerhub.manifest import Manifest, infer_date_range


def cache_root() -> Path:
    return Path(os.environ.get("SOCCERHUB_CACHE", "./data")).resolve()


def cache_key(source: str, dataset: str, params: dict) -> str:
    payload = json.dumps(
        {"source": source, "dataset": dataset, "params": params}, sort_keys=True
    )
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def parquet_path(source: str, key: str) -> Path:
    return cache_root() / source / f"{key}.parquet"


def manifest_path(source: str, key: str) -> Path:
    return cache_root() / source / f"{key}.json"


def cache_hit(source: str, key: str) -> bool:
    return parquet_path(source, key).exists() and manifest_path(source, key).exists()


def write_parquet(path: Path, df) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp)
    tmp.replace(path)


def read_manifest(source: str, key: str) -> Manifest:
    return Manifest.from_json(manifest_path(source, key).read_text())


def cached_fetch(
    source: str,
    dataset: str,
    params: dict,
    produce: Callable[[], "object"],
    force: bool = False,
) -> Manifest:
    key = cache_key(source, dataset, params)
    if not force and cache_hit(source, key):
        return read_manifest(source, key)

    try:
        df = produce()
    except Exception as exc:  # noqa: BLE001 — wrap any library/network failure
        raise SoccerhubError(f"{source}.{dataset} fetch failed: {exc}") from exc

    ppath = parquet_path(source, key)
    write_parquet(ppath, df)

    manifest = Manifest(
        path=str(ppath),
        source=source,
        dataset=dataset,
        params=params,
        rows=len(df),
        cols=len(df.columns),
        date_range=infer_date_range(df),
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    manifest_path(source, key).write_text(manifest.to_json())
    return manifest
