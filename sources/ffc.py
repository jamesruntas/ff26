"""Fantasy Football Calculator ADP.

Population: mock drafts run on FFC's own site, computer picks filtered out.
Free for personal and commercial use; they ask for attribution back and ask
that you not hammer it -- the data only changes once a day.

No shared player id, so this feed goes through name matching in ids.py.
"""
from __future__ import annotations

import pandas as pd

from config import SCORING, SEASON, TEAMS, norm_team
from fetch import get_json

BASE = "https://fantasyfootballcalculator.com/api/v1/adp"


def fetch(scoring: str = SCORING, teams: int = TEAMS, year: int = SEASON, use_cache: bool = True) -> pd.DataFrame:
    url = f"{BASE}/{scoring}?teams={teams}&year={year}"
    body = get_json(url, tag="ffc", use_cache=use_cache)

    players = body.get("players") or []
    if not players:
        raise ValueError("FFC returned no players -- check the season/format in config.py")

    df = pd.DataFrame(players)
    df["team"] = df["team"].map(norm_team)
    df["position"] = df["position"].str.upper().replace({"PK": "K", "DEF": "DST"})
    df = df.rename(columns={"adp": "adp_ffc", "times_drafted": "n_ffc"})

    meta = body.get("meta", {})
    df.attrs["total_drafts"] = meta.get("total_drafts")

    return df[["name", "position", "team", "adp_ffc", "n_ffc", "high", "low", "stdev"]]


def draft_pct(df: pd.DataFrame) -> pd.Series:
    """FFC gives raw counts, not percentages. Convert using the max observed."""
    denom = df["n_ffc"].max()
    return (df["n_ffc"] / denom * 100).round(1) if denom else pd.Series(0.0, index=df.index)
