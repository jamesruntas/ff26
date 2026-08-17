"""Blend an arbitrary number of feeds into one ranking.

Why rank-normalise instead of averaging raw ADP: feeds have different roster
sizes, different depth, and different player universes, so a raw pick number
does not mean the same thing across them. A player sitting at 150 in one feed
may not exist at all in a feed that only reports 180 deep. Converting each
source to a within-source rank first puts them on a common scale; the median
of those ranks is then robust to one source going strange on a single player.

adp_master is reported separately as the median of the raw ADP values, because
a pick number is what you actually want to read on draft day. Use adp_rank for
ordering and adp_master for "where does he go".

adp_spread (max - min across sources) is the column that earns its keep. All
these drafter pools read the same news, so they will agree most of the time;
the disagreements are where platform format is doing the work, and that is the
actionable signal.

The source list itself lives entirely in main.py's collect() -- adding a
fourth feed (an API-fetched one, or a hand-typed CSV via
reference_data.load_custom_sources) is just one more adp_<tag> column passed
in through adp_cols, nothing here hardcodes a count.
"""
from __future__ import annotations

import pandas as pd

from config import MIN_DRAFT_PCT, MIN_SOURCES


def apply_sample_floor(df: pd.DataFrame, pct_cols: dict[str, str]) -> pd.DataFrame:
    """Null out an ADP where that source barely drafted the player.

    A player taken in 3% of drafts has an ADP, but it is the ADP of the three
    people who reached for him, not a market price. Sources with no sample-size
    concept (a hand-typed custom list) just aren't in pct_cols, so they skip
    this floor entirely -- there's no "thin sample" to detect on a list you
    typed yourself.
    """
    out = df.copy()
    for adp_col, pct_col in pct_cols.items():
        if pct_col in out.columns:
            thin = out[pct_col].fillna(0) < MIN_DRAFT_PCT
            out.loc[thin, adp_col] = pd.NA
    return out


def build_master(df: pd.DataFrame, adp_cols: list[str]) -> pd.DataFrame:
    out = df.copy()

    for col in adp_cols:
        if col not in out.columns:
            out[col] = pd.NA
        out[col] = pd.to_numeric(out[col], errors="coerce")

    # Within-source ranks put every feed on a common scale.
    rank_cols = []
    for col in adp_cols:
        rc = col.replace("adp_", "rank_")
        out[rc] = out[col].rank(method="min")
        rank_cols.append(rc)

    out["sources_n"] = out[adp_cols].notna().sum(axis=1)
    out = out[out["sources_n"] >= MIN_SOURCES].copy()

    out["_median_rank"] = out[rank_cols].median(axis=1, skipna=True)
    out["adp_master"] = out[adp_cols].median(axis=1, skipna=True).round(2)

    out["adp_spread"] = (
        out[adp_cols].max(axis=1, skipna=True) - out[adp_cols].min(axis=1, skipna=True)
    ).round(1)

    out = out.sort_values(["_median_rank", "adp_master"], kind="mergesort").reset_index(drop=True)
    out["adp_rank"] = range(1, len(out) + 1)

    # Round-and-pick notation, e.g. 1.03 for the third pick of round one.
    def _slot(adp, teams=12):
        if pd.isna(adp):
            return ""
        pick = max(1, int(round(adp)))
        rnd, within = divmod(pick - 1, teams)
        return f"{rnd + 1}.{within + 1:02d}"

    out["adp_slot"] = out["adp_master"].map(_slot)
    return out.drop(columns=["_median_rank"] + rank_cols)


def source_agreement(df: pd.DataFrame, adp_cols: list[str]) -> pd.DataFrame:
    """Pairwise Spearman between the feeds. A sanity check, not an output.

    Expect high correlation -- these pools all read the same news. What you are
    watching for is a pair that is *too* correlated (one may be derivative) or
    one feed that has drifted away from the others (likely a filter or format
    mismatch in the pull, not a market insight).
    """
    sub = df[adp_cols].dropna(how="all")
    return sub.corr(method="spearman").round(3)
