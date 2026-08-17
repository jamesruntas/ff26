"""The board you actually look at during a draft.

Reads the pre-computed master CSV fresh each call (one small file, cheap) and
layers on everything that only makes sense in the context of a live draft:
who's still available, value relative to where you're picking, whether a
player is likely to survive to your next turn, tiers, and how depleted each
position's tiers are.

Tiers are assigned once against the *full* pre-draft board, not recomputed on
the shrinking live board. That matters: if tiers were recomputed after
removing drafted players, the gap between two survivors can only grow, so a
tier that started as one contiguous group can silently fracture into extra
pieces as the draft goes on. Pegging to the full board keeps tier membership
fixed for the whole draft, which is also what tier_depletion() needs -- a
stable "how many of this original group are gone" baseline to count against.
"""
from __future__ import annotations

import pandas as pd
from scipy.stats import norm

import draft_state
import tiers
from config import MY_DRAFT_SLOT, RUN_THRESHOLD, RUN_WINDOW, TEAMS, master_csv_path


def _full_tiered_board() -> pd.DataFrame:
    df = pd.read_csv(master_csv_path(), dtype={"mfl_id": str})
    return tiers.assign_tiers(df)


def _survival_prob(row: pd.Series, next_pick_no: int) -> float:
    """P(player still available at next_pick_no), modeled as ADP ~ Normal.

    Prefers FFC's real per-player stdev. When that's missing, falls back to
    adp_spread / 4 -- not a real standard deviation, just the least-bad proxy
    on hand from the three-source spread. Flagged as an approximation, not a
    real distributional fit.
    """
    mean = row["adp_master"]
    if pd.isna(mean):
        return float("nan")
    scale = row.get("adp_ffc_stdev")
    if pd.isna(scale) or scale is None or scale <= 0:
        spread = row.get("adp_spread")
        scale = max(spread / 4, 1) if pd.notna(spread) else 5.0
    return float(norm.sf(next_pick_no, loc=mean, scale=scale))


def _depletion_from_full(full: pd.DataFrame, drafted_ids: set[str]) -> pd.DataFrame:
    total = full.groupby(["pos", "tier"]).size().rename("total")
    drafted = full[full["mfl_id"].isin(drafted_ids)].groupby(["pos", "tier"]).size()
    drafted = drafted.rename("drafted")

    out = pd.concat([total, drafted], axis=1).fillna(0).astype(int)
    out["remaining"] = out["total"] - out["drafted"]
    return out.reset_index().sort_values(["pos", "tier"]).reset_index(drop=True)


def build(picks: list[dict] | None = None, my_slot: int = MY_DRAFT_SLOT) -> pd.DataFrame:
    picks = picks if picks is not None else draft_state.load_picks()
    drafted_ids = {p["mfl_id"] for p in picks}

    full = _full_tiered_board()
    depletion = _depletion_from_full(full, drafted_ids)
    df = full[~full["mfl_id"].isin(drafted_ids)].copy()

    next_pick_no = len(picks) + 1
    my_next = draft_state.my_next_pick_no(picks, my_slot=my_slot)

    df["value_delta"] = next_pick_no - df["adp_rank"]
    df["value_delta_rounds"] = df["value_delta"] / TEAMS
    df["survival_prob"] = df.apply(lambda r: _survival_prob(r, my_next), axis=1)

    # Scarcity-weighted value: the same pick-count fall means more when the
    # player's tier is nearly drafted out. remaining/total of 1.0 (untouched
    # tier) leaves value_delta unchanged; approaching 0 (nearly gone) roughly
    # doubles it. A multiplier, not a replacement -- value_delta stays the
    # transparent, easy-to-explain number; this is the "and weighted for
    # scarcity" upgrade on top of it.
    df = df.merge(depletion[["pos", "tier", "remaining", "total"]], on=["pos", "tier"], how="left")
    depleted_share = 1 - (df["remaining"] / df["total"]).fillna(1)
    df["scarcity_multiplier"] = 1 + depleted_share
    df["scarcity_value"] = df["value_delta"] * df["scarcity_multiplier"]

    return df.sort_values("adp_rank").reset_index(drop=True)


def tier_depletion(picks: list[dict] | None = None) -> pd.DataFrame:
    """How drafted-out each (position, tier) group is.

    Counts against the fixed full-board tier membership, so "3/8 left" means
    the same thing at pick 5 and at pick 50 -- it's the same group of 8
    players the whole draft, just fewer of them still on the board.
    """
    picks = picks if picks is not None else draft_state.load_picks()
    drafted_ids = {p["mfl_id"] for p in picks}
    return _depletion_from_full(_full_tiered_board(), drafted_ids)


def bye_week_lookup() -> dict[str, int]:
    """mfl_id -> bye_week for every player in the board, drafted or not."""
    df = pd.read_csv(master_csv_path(), dtype={"mfl_id": str})
    return df.set_index("mfl_id")["bye_week"].dropna().astype(int).to_dict()


def adp_rank_lookup() -> dict[str, int]:
    """mfl_id -> adp_rank for every player in the board, drafted or not."""
    df = pd.read_csv(master_csv_path(), dtype={"mfl_id": str})
    return df.set_index("mfl_id")["adp_rank"].dropna().astype(int).to_dict()


def positional_run(picks: list[dict], window: int = RUN_WINDOW, threshold: int = RUN_THRESHOLD) -> str | None:
    """If a position is >= threshold of the last `window` picks, name it."""
    recent = picks[-window:]
    if len(recent) < threshold:
        return None
    counts: dict[str, int] = {}
    for p in recent:
        counts[p["pos"]] = counts.get(p["pos"], 0) + 1
    pos, n = max(counts.items(), key=lambda kv: kv[1]) if counts else (None, 0)
    if n >= threshold:
        return f"{pos} run: {n} of the last {len(recent)} picks"
    return None
