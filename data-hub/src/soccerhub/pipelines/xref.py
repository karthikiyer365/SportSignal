"""Player entity resolution: FBref names -> Transfermarkt ids."""
import re
import unicodedata
from difflib import SequenceMatcher

import pandas as pd

from soccerhub.cache import cached_fetch
from soccerhub.manifest import Manifest
from soccerhub.readers.fbref import fetch_fbref_season
from soccerhub.readers.transfermarkt import fetch_transfermarkt_players

MAPPING_URL = (
    "https://raw.githubusercontent.com/JaseZiv/worldfootballR_data/"
    "master/raw-data/fbref-tm-player-mapping/output/fbref_to_tm_mapping.csv"
)

FUZZY_FLOOR = 0.85  # ponytail: single global threshold, tune per-league if noisy

# Manual review verdicts: fbref_name -> tm_id (or None = force unmatched).
# For pairs no automatic rule can settle (e.g. Nathan Doyle vs Nathan Dyer:
# different players, same birth year, name ratio above the floor).
OVERRIDES: dict[str, int | None] = {
    "Nathan Doyle": None,  # vs Nathan Dyer: same birth year, different player
    # mononym TM names, manually verified via birth year + club + position:
    "Alysson Edward": 1005583,   # Alysson, Aston Villa
    "Bruno": 51528,              # Bruno Saltor, Brighton
    "Eduardo da Silva": 24633,   # Eduardo, Arsenal->Shakhtar
    "Estêvão Willian": 1056993,  # Estêvão, Chelsea
    "Gabriel Magalhães": 435338, # Gabriel, Arsenal
    "Guly do Prado": 22801,      # Guly, Southampton
    "Henrique Hilário": 13886,   # Hilário, Chelsea GK
    "José Bosingwa": 9813,       # Bosingwa, Chelsea/QPR
    "Jota": 176591,              # Jota Peleteiro, Aston Villa
    "Maicon Sisenando": 18301,   # Maicon, Man City
    "Mohamed Gedo": 104941,      # Gedo, Hull City
}


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _load_mapping() -> pd.DataFrame:
    # upstream file is utf-8 with a few stray latin-1 bytes; strict utf-8
    # raises, latin-1 mojibakes every accent -> utf-8 + replace stray bytes
    return pd.read_csv(MAPPING_URL, encoding="utf-8", encoding_errors="replace")


def _tm_id_from_url(url: str):
    m = re.search(r"/spieler/(\d+)", str(url))
    return int(m.group(1)) if m else None


def _score(a: str, b: str) -> float:
    """Name similarity. Token-subset beats raw ratio: 'angel di maria' vs
    'angel di maria hernandez' is the same person (short name inside legal
    name) but SequenceMatcher alone scores it 0.74 — below the floor.
    The shorter name needs >= 2 tokens: mononyms ('Alan', 'Diego') are
    substrings of half the league and proved to be pure false-positive fuel.
    """
    ta, tb = set(a.split()), set(b.split())
    if min(len(ta), len(tb)) >= 2 and (ta <= tb or tb <= ta):
        return 0.95
    return SequenceMatcher(None, a, b).ratio()


def build_player_xref(
    league: str, season: str, force: bool = False, refetch: bool = False
) -> Manifest:
    """One row per FBref (player, team) in a league-season -> tm_id + method.

    force rebuilds this derived table; refetch additionally re-downloads the
    source data (fbref pages, TM registry) instead of trusting reader caches.
    """

    def produce():
        fbref = pd.read_parquet(
            fetch_fbref_season(league, season, force=refetch).path
        ).reset_index()
        if isinstance(fbref.columns, pd.MultiIndex):
            # real fbref frames have ('Performance','Gls')-style columns;
            # we only need the index-derived flat ones (player/team/born)
            fbref.columns = [c[0] for c in fbref.columns]
        players = fbref[["player", "team"]].drop_duplicates()
        born = (
            fbref.groupby("player")["born"].first()
            if "born" in fbref.columns
            else pd.Series(dtype="object")
        )

        mapping = _load_mapping()
        mapping["tm_id"] = mapping["UrlTmarkt"].map(_tm_id_from_url)
        # homonyms (two Aaron Ramseys) make a name-keyed dict pick arbitrarily
        # -> drop ambiguous names, let year-guarded exact/fuzzy resolve them
        mapping = mapping.drop_duplicates("PlayerFBref", keep=False)
        map_by_name = mapping.set_index("PlayerFBref")["tm_id"].to_dict()

        # full registry, not current-league squads: historical seasons are
        # full of players who since retired or transferred out
        tm = pd.read_parquet(fetch_transfermarkt_players(None, force=refetch).path)
        tm["norm"] = tm["name"].map(normalize)
        exact_by_norm = tm.set_index("norm")["player_id"].to_dict()
        tm_year = pd.to_datetime(tm["date_of_birth"], errors="coerce").dt.year

        # token blocking: fuzzy only against registry names sharing a word,
        # else 32k-candidate scans per leftover make backfills crawl
        token_idx: dict[str, list[int]] = {}
        for i, cand in enumerate(tm["norm"]):
            for tok in cand.split():
                token_idx.setdefault(tok, []).append(i)

        year_by_id = dict(zip(tm["player_id"], tm_year))

        rows = []
        for _, r in players.iterrows():
            name = r["player"]
            b = born.get(name)

            def year_ok(tm_id) -> bool:
                ty = year_by_id.get(tm_id)
                return not (
                    pd.notna(b) and ty is not None and pd.notna(ty)
                    and abs(int(b) - int(ty)) > 1
                )

            # 0. manual review verdicts beat every rung
            if name in OVERRIDES:
                tm_id = OVERRIDES[name]
                if tm_id is None:
                    rows.append((name, r["team"], None, "unmatched", 0.0))
                else:
                    rows.append((name, r["team"], int(tm_id), "override", 1.0))
                continue
            # 1. mapping file (year-guarded: file itself has stale/homonym rows)
            tm_id = map_by_name.get(name)
            if tm_id is not None and pd.notna(tm_id) and year_ok(int(tm_id)):
                rows.append((name, r["team"], int(tm_id), "mapping_file", 1.0))
                continue
            # 2. exact normalized (year-guarded: homonyms share names)
            tm_id = exact_by_norm.get(normalize(name))
            if tm_id is not None and year_ok(int(tm_id)):
                rows.append((name, r["team"], int(tm_id), "exact", 1.0))
                continue
            # 3. fuzzy among token-sharing candidates, birth-year guard
            best_ratio, best_id = 0.0, None
            norm_name = normalize(name)
            cand_idx = sorted(
                {i for tok in norm_name.split() for i in token_idx.get(tok, [])}
            )
            for i in cand_idx:
                cand = tm["norm"].iloc[i]
                ratio = _score(norm_name, cand)
                if ratio <= best_ratio:
                    continue
                ty = tm_year.iloc[i]
                if pd.notna(b) and pd.notna(ty) and abs(int(b) - int(ty)) > 1:
                    continue
                best_ratio, best_id = ratio, int(tm["player_id"].iloc[i])
            if best_ratio >= FUZZY_FLOOR:
                rows.append((name, r["team"], best_id, "fuzzy", round(best_ratio, 3)))
            else:
                rows.append((name, r["team"], None, "unmatched", 0.0))

        out = pd.DataFrame(
            rows, columns=["fbref_name", "team", "tm_id", "method", "confidence"]
        )
        out["tm_id"] = out["tm_id"].astype("Int64")
        return out

    return cached_fetch(
        "xref", "players", {"league": league, "season": season}, produce, force
    )
