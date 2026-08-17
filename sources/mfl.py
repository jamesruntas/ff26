"""MyFantasyLeague ADP.

Population: real home-league drafts conducted on MFL. They do not accept
imported drafts from other platforms, which is exactly why this feed counts as
an independent source rather than a re-publication of someone else's numbers.

The filters below are load-bearing. MFL's league mix skews dynasty, keeper and
superflex, so an unfiltered pull will mangle your top 30 by blending superflex
QB pricing into 1QB ADP. IS_MOCK=0 / IS_KEEPER=0 / FCOUNT=12 / IS_PPR=1 is the
combination that gets you 12-team PPR redraft and nothing else.

Use the api.myfantasyleague.com host (not a www## host) for non-league
requests -- it spreads load across servers, and their rate limits are applied
per server.
"""
from __future__ import annotations

import pandas as pd

from config import IS_PPR, SEASON, TEAMS, norm_team
from fetch import get_json

BASE = "https://api.myfantasyleague.com"


def fetch(
    year: int = SEASON,
    teams: int = TEAMS,
    is_ppr: int = IS_PPR,
    period: str = "RECENT",
    cutoff: int = 5,
) -> pd.DataFrame:
    url = (
        f"{BASE}/{year}/export?TYPE=adp"
        f"&PERIOD={period}"
        f"&FCOUNT={teams}"
        f"&IS_PPR={is_ppr}"
        f"&IS_KEEPER=0"
        f"&IS_MOCK=0"
        f"&CUTOFF={cutoff}"
        f"&DETAILS=0"
        f"&JSON=1"
    )
    body = get_json(url, tag="mfl")

    node = body.get("adp", {})
    players = node.get("player") or []
    if not players:
        raise ValueError(
            "MFL returned no players. Early in preseason the filtered pool can "
            "genuinely be empty -- try PERIOD=ALL or a lower CUTOFF."
        )

    df = pd.DataFrame(players)
    # Ids are strings. Sub-1000 ids need the leading zero (BAL DST is "0531",
    # not 531) and will silently mismatch if pandas infers them as ints.
    df["mfl_id"] = df["id"].astype(str).str.strip().str.zfill(4)

    df["adp_mfl"] = pd.to_numeric(df["averagePick"], errors="coerce")
    df["n_mfl"] = pd.to_numeric(df.get("draftsSelectedIn"), errors="coerce")
    df["pct_mfl"] = pd.to_numeric(df.get("draftSelPct"), errors="coerce")

    total = pd.to_numeric(node.get("totalDrafts"), errors="coerce")
    if pd.isna(df["pct_mfl"]).all() and total:
        df["pct_mfl"] = (df["n_mfl"] / total * 100).round(1)

    out = df[["mfl_id", "adp_mfl", "n_mfl", "pct_mfl"]].dropna(subset=["adp_mfl"])
    out.attrs["total_drafts"] = total
    return out.reset_index(drop=True)


def fetch_dst_ids(year: int = SEASON) -> pd.DataFrame:
    """mfl_id -> team for the 32 team defenses.

    Roster metadata, not ADP -- pulled from MFL's players export, not the adp
    one. Exists because DynastyProcess's id crosswalk (ids.load_crosswalk)
    doesn't carry team defenses at all, so FFC's and ESPN's DST rows have
    nothing to resolve an mfl_id against. A defense's identity is just its
    team -- unambiguous -- so it gets matched by team code instead of the
    usual name/id crosswalk.
    """
    url = f"{BASE}/{year}/export?TYPE=players&DETAILS=1&JSON=1"
    body = get_json(url, tag="mfl_players")

    players = body.get("players", {}).get("player") or []
    df = pd.DataFrame(players)
    dst = df[df["position"].isin(["Def", "DEF", "DST"])].copy()
    if dst.empty:
        raise ValueError("MFL players export returned no team defenses -- check TYPE=players still works.")

    dst["mfl_id"] = dst["id"].astype(str).str.strip().str.zfill(4)
    dst["team"] = dst["team"].map(norm_team)
    return dst[["mfl_id", "team"]].reset_index(drop=True)
