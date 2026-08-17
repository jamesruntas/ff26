"""Player identity. Everything in this project is keyed to MFL id.

Three feeds, three id schemes:
  MFL   -> mfl_id directly, no work needed
  ESPN  -> espn_id, present in the crosswalk
  FFC   -> no shared id at all, so we match on normalised name + position

Name matching is the weak link and it is always rookies and suffix changes
that break it. When a player falls out, add them to MANUAL_MFL_IDS rather
than loosening the matcher -- a fuzzy matcher that is generous enough to
catch "Marvin Harrison Jr." will eventually merge two different players.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

from config import PLAYERIDS_URL, norm_team


_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# FFC name (normalised) -> MFL id. Fill in as breakages appear each preseason.
MANUAL_MFL_IDS: dict[str, str] = {
    # "example player": "16789",
}


def merge_name(name: str) -> str:
    """Match DynastyProcess's `merge_name` convention as closely as possible."""
    if not isinstance(name, str):
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().replace(".", "").replace("'", "").replace("-", " ")
    s = re.sub(r"[^a-z ]", " ", s)
    parts = [p for p in s.split() if p and p not in _SUFFIXES]
    return " ".join(parts)


def load_crosswalk() -> pd.DataFrame:
    """Fetch DynastyProcess db_playerids and return one row per mfl_id."""
    df = pd.read_csv(PLAYERIDS_URL, low_memory=False, dtype=str)
    keep = ["mfl_id", "espn_id", "sleeper_id", "name", "merge_name", "position", "team"]
    df = df[[c for c in keep if c in df.columns]].copy()

    df = df[df["mfl_id"].notna()]
    df["mfl_id"] = df["mfl_id"].astype(str).str.strip()
    # MFL ids are strings; sub-1000 ids carry a leading zero and break if you
    # ever let them become ints.
    df["mfl_id"] = df["mfl_id"].str.zfill(4)

    if "merge_name" not in df.columns:
        df["merge_name"] = df["name"].map(merge_name)
    else:
        df["merge_name"] = df["merge_name"].fillna("").map(merge_name)

    df["position"] = df["position"].fillna("").str.upper().str.replace("PK", "K")
    df["team"] = df["team"].map(norm_team)
    df["espn_id"] = df["espn_id"].astype(str).str.strip().replace({"nan": None})

    return df.drop_duplicates(subset=["mfl_id"], keep="first").reset_index(drop=True)


def attach_mfl_id_by_name(
    df: pd.DataFrame, xwalk: pd.DataFrame, name_col: str = "name", pos_col: str = "position"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Join a name-keyed feed onto mfl_id. Returns (matched, unmatched)."""
    work = df.copy()
    work["merge_name"] = work[name_col].map(merge_name)
    work["_pos"] = work[pos_col].fillna("").str.upper().str.replace("PK", "K")

    lookup = xwalk[["mfl_id", "merge_name", "position"]].rename(columns={"position": "_pos"})

    # Pass 1: name + position. Strictest, catches the overwhelming majority.
    out = work.merge(lookup, on=["merge_name", "_pos"], how="left")

    # Pass 2: name alone, but only where the name is unique in the crosswalk.
    still = out["mfl_id"].isna()
    if still.any():
        uniq = xwalk.groupby("merge_name")["mfl_id"].nunique()
        solo = xwalk[xwalk["merge_name"].isin(uniq[uniq == 1].index)]
        solo = solo[["mfl_id", "merge_name"]].rename(columns={"mfl_id": "_alt"})
        out = out.merge(solo, on="merge_name", how="left")
        out.loc[still, "mfl_id"] = out.loc[still, "_alt"]
        out = out.drop(columns=["_alt"])

    # Pass 3: manual overrides always win.
    override = out["merge_name"].map(MANUAL_MFL_IDS)
    out["mfl_id"] = override.fillna(out["mfl_id"])

    matched = out[out["mfl_id"].notna()].copy()
    matched["mfl_id"] = matched["mfl_id"].astype(str).str.zfill(4)
    unmatched = out[out["mfl_id"].isna()].copy()
    return matched.drop(columns=["_pos"]), unmatched.drop(columns=["_pos"])


def attach_dst_mfl_id(
    df: pd.DataFrame, dst_xwalk: pd.DataFrame, team_col: str = "team"
) -> pd.DataFrame:
    """Match team-defense rows to mfl_id by team code, not name.

    The main crosswalk has no defenses to match against; dst_xwalk (see
    sources.mfl.fetch_dst_ids) is team -> mfl_id instead. A defense's
    identity is unambiguous from its team, so this sidesteps name matching
    for the one position where it can't work at all.
    """
    lookup = dst_xwalk.set_index("team")["mfl_id"]
    out = df.copy()
    out["mfl_id"] = out[team_col].map(lookup)
    return out
