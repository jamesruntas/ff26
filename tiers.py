"""Draft-day tiering: group players within a position by adp_rank gaps.

Deterministic and explainable mid-draft -- no clustering to second-guess when
you have thirty seconds on the clock. A new tier starts whenever the gap to
the previous player's adp_rank (within the same position) exceeds that
position's threshold in config.TIER_GAP_RANK.
"""
from __future__ import annotations

import pandas as pd

from config import TIER_GAP_RANK


def assign_tiers(df: pd.DataFrame, gap_rank: dict[str, int] = TIER_GAP_RANK) -> pd.DataFrame:
    out = df.copy()
    out["tier"] = pd.NA

    for pos, group in out.groupby("pos"):
        threshold = gap_rank.get(pos, 4)
        ordered = group.sort_values("adp_rank")
        tier = 1
        prev_rank = None
        tiers = []
        for rank in ordered["adp_rank"]:
            if prev_rank is not None and (rank - prev_rank) > threshold:
                tier += 1
            tiers.append(tier)
            prev_rank = rank
        out.loc[ordered.index, "tier"] = tiers

    return out
