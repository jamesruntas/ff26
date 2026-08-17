"""ESPN ADP via the undocumented fantasy v3 API.

Population: drafts on ESPN's own platform. No key, no auth.

Two things to know. First, the X-Fantasy-Filter header is mandatory -- without
it you get capped at 50 players. Second, this endpoint is undocumented, so
treat a schema change as a matter of when, not if; the parse below fails loudly
rather than silently returning half a dataset.

Open question worth checking yourself: ESPN does not state whether autodrafted
picks are excluded. FFC says plainly that it strips computer picks; ESPN says
nothing. If ESPN's ADP order tracks ESPN's own published rank order almost
exactly, that is your tell that autodraft is leaking in and the feed is partly
restating ESPN's editorial rankings. `espn_adp_vs_rank_corr()` below gives you
that diagnostic.
"""
from __future__ import annotations

import json

import pandas as pd

from config import ESPN_LEAGUE_DEFAULT, SEASON, norm_team
from fetch import get_json

BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"

POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}

PRO_TEAMS = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL",
    7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV",
    14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG",
    20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF",
    26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}


def fetch(
    year: int = SEASON, limit: int = 700, rank_type: str = "PPR", use_cache: bool = True
) -> pd.DataFrame:
    url = f"{BASE}/{year}/segments/0/leaguedefaults/{ESPN_LEAGUE_DEFAULT}?view=kona_player_info"
    fantasy_filter = {
        "players": {
            "limit": limit,
            "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": rank_type},
        }
    }
    body = get_json(
        url, tag="espn", headers={"X-Fantasy-Filter": json.dumps(fantasy_filter)}, use_cache=use_cache
    )

    entries = body.get("players")
    if not entries:
        raise ValueError(
            "ESPN returned no players. Most likely the X-Fantasy-Filter header was "
            "rejected or the endpoint schema moved."
        )

    rows = []
    for item in entries:
        p = item.get("player") or {}
        own = p.get("ownership") or {}
        adp = own.get("averageDraftPosition")
        if not adp or adp <= 0:
            continue  # undrafted players carry 0

        ranks = (p.get("draftRanksByRankType") or {}).get(rank_type) or {}
        rows.append(
            {
                "espn_id": str(item.get("id") or p.get("id")),
                "name": p.get("fullName"),
                "position": POSITIONS.get(p.get("defaultPositionId"), "UNK"),
                "team": PRO_TEAMS.get(p.get("proTeamId"), "FA"),
                "adp_espn": float(adp),
                "pct_espn": own.get("percentOwned"),
                "espn_rank": ranks.get("rank"),
            }
        )

    if not rows:
        raise ValueError("ESPN parsed cleanly but every ADP was zero -- too early in preseason?")

    df = pd.DataFrame(rows)
    df["team"] = df["team"].map(norm_team)
    return df


def espn_adp_vs_rank_corr(df: pd.DataFrame) -> float:
    """Spearman correlation between ESPN ADP and ESPN's own editorial rank.

    Near 1.0 means the 'market' is mostly autodrafters following ESPN's list,
    i.e. the feed is less independent than it looks. Anything above ~0.98 is
    worth a hard look before you weight this source equally.
    """
    sub = df.dropna(subset=["adp_espn", "espn_rank"])
    return float(sub["adp_espn"].corr(sub["espn_rank"], method="spearman"))
