"""CPU pick logic for auto-filling other teams' picks in a mock draft.

Deliberately simple and stateless: opponents aren't roster-tracked (only your
own team is, in draft_state.my_roster), so there's no notion of "this team
needs a QB" to lean on. A CPU pick is just "mostly the next-best player by
consensus adp_rank, with enough randomness that it isn't a robotic exact-ADP
order" -- a weighted random draw from the top MOCK_POOL_SIZE available
players, weights decaying geometrically by rank so the top player is likeliest
but not guaranteed.
"""
from __future__ import annotations

import pandas as pd

from config import MOCK_DECAY, MOCK_POOL_SIZE


def pick_for_cpu(board: pd.DataFrame, pool_size: int = MOCK_POOL_SIZE, decay: float = MOCK_DECAY) -> pd.Series:
    """Pick one row from the board's best-available players, ADP-weighted."""
    pool = board.sort_values("adp_rank").head(pool_size)
    weights = [decay**i for i in range(len(pool))]
    return pool.sample(n=1, weights=weights).iloc[0]
