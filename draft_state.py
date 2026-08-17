"""Live draft session: the pick log, snake-draft math, and your own roster.

The only thing you enter per pick is who got picked. Whether it was your pick
is derived from the pick count and your draft slot via on_the_clock() --
standard snake order, no manual team selection needed. Only your own roster
is tracked; every other pick just comes off the board.

Your draft slot is part of the session (changeable live in the GUI, not just
in config.py), and ownership of each pick is computed fresh from the current
slot rather than stored on the pick -- so changing your slot mid-session
correctly re-evaluates which already-recorded picks are yours instead of
leaving stale data behind.

State is a JSON object, persisted after every change, so closing the app
mid-draft loses nothing.
"""
from __future__ import annotations

import json

from config import MY_DRAFT_SLOT, ROSTER_SLOTS, SEASON, SESSION, TEAMS

SESSION_FILE = SESSION / f"session_{SEASON}.json"

FLEX_ELIGIBLE = {"RB", "WR", "TE"}


def on_the_clock(pick_no: int, teams: int = TEAMS, my_slot: int = MY_DRAFT_SLOT) -> int:
    """1-indexed slot on the clock for the given overall pick number (snake order)."""
    round_no, pos_in_round = divmod(pick_no - 1, teams)
    if round_no % 2 == 0:
        return pos_in_round + 1
    return teams - pos_in_round


def load_session() -> dict:
    if not SESSION_FILE.exists():
        return {"my_slot": MY_DRAFT_SLOT, "picks": []}
    data = json.loads(SESSION_FILE.read_text())
    if isinstance(data, list):  # pre-slot-picker session file: bare pick list
        return {"my_slot": MY_DRAFT_SLOT, "picks": data}
    data.setdefault("my_slot", MY_DRAFT_SLOT)
    data.setdefault("picks", [])
    return data


def _save(session: dict) -> None:
    SESSION_FILE.write_text(json.dumps(session, indent=2))


def load_picks() -> list[dict]:
    return load_session()["picks"]


def load_my_slot() -> int:
    return load_session()["my_slot"]


def set_my_slot(slot: int) -> None:
    session = load_session()
    session["my_slot"] = slot
    _save(session)


def record_pick(mfl_id: str, player: str, pos: str) -> list[dict]:
    session = load_session()
    pick_no = len(session["picks"]) + 1
    session["picks"].append(
        {"pick_no": pick_no, "mfl_id": str(mfl_id), "player": player, "pos": pos}
    )
    _save(session)
    return session["picks"]


def undo_last_pick() -> list[dict]:
    session = load_session()
    if session["picks"]:
        session["picks"].pop()
        _save(session)
    return session["picks"]


def reset_session() -> None:
    """Clear the pick log for a new draft. Keeps my_slot -- that's a league
    setting, not something you re-enter every time you start over."""
    session = load_session()
    session["picks"] = []
    _save(session)


def total_roster_picks(roster_slots: dict = ROSTER_SLOTS) -> int:
    return sum(roster_slots.values())


def is_roster_full(roster: dict) -> bool:
    return all(n == 0 for n in roster["open"].values())


def picks_until_my_turn(picks: list[dict], my_slot: int = MY_DRAFT_SLOT) -> int:
    pick_no = len(picks) + 1
    for offset in range(0, TEAMS * 2):
        if on_the_clock(pick_no + offset, my_slot=my_slot) == my_slot:
            return offset
    return -1  # shouldn't happen


def my_next_pick_no(picks: list[dict], my_slot: int = MY_DRAFT_SLOT) -> int:
    pick_no = len(picks) + 1
    return pick_no + picks_until_my_turn(picks, my_slot)


def my_roster(picks: list[dict], my_slot: int = MY_DRAFT_SLOT, roster_slots: dict = ROSTER_SLOTS) -> dict:
    """Greedily fill required positions in draft order, then FLEX, then bench.

    "Mine" is recomputed from my_slot + pick_no on every call, not stored on
    the pick -- so changing your draft slot re-evaluates ownership instead of
    leaving picks attributed to a slot you no longer are.

    Returns {"starters": {pos: [player, ...]}, "bench": [player, ...],
    "open": {pos: n_still_needed}}.
    """
    mine = [p for p in picks if on_the_clock(p["pick_no"], my_slot=my_slot) == my_slot]

    required = {k: v for k, v in roster_slots.items() if k not in ("FLEX", "BN")}
    starters = {pos: [] for pos in required}
    flex: list[dict] = []
    bench: list[dict] = []

    for p in mine:
        pos = p["pos"]
        cap = required.get(pos, 0)
        if pos in starters and len(starters[pos]) < cap:
            starters[pos].append(p)
        elif pos in FLEX_ELIGIBLE:
            flex.append(p)
        else:
            bench.append(p)

    flex_cap = roster_slots.get("FLEX", 0)
    starters["FLEX"] = flex[:flex_cap]
    bench = flex[flex_cap:] + bench

    bench_cap = roster_slots.get("BN", 0)
    overflow = bench[bench_cap:]
    bench = bench[:bench_cap]

    open_slots = {}
    for pos, cap in required.items():
        open_slots[pos] = max(0, cap - len(starters.get(pos, [])))
    open_slots["FLEX"] = max(0, flex_cap - len(starters["FLEX"]))
    open_slots["BN"] = max(0, bench_cap - len(bench))

    return {"starters": starters, "bench": bench, "open": open_slots, "overflow": overflow}


def my_value_summary(
    picks: list[dict], my_slot: int = MY_DRAFT_SLOT, adp_rank_by_id: dict | None = None
) -> dict:
    """Running value stats across just your own picks so far.

    Value for a pick = the pick number you took them at minus their
    pre-draft adp_rank -- same definition live_board uses for value_delta,
    just evaluated at the moment you actually took them rather than "right
    now." A self-scorecard, not a league comparison -- opponents aren't
    tracked here, same as everywhere else.
    """
    adp_rank_by_id = adp_rank_by_id or {}
    mine = [p for p in picks if on_the_clock(p["pick_no"], my_slot=my_slot) == my_slot]

    values = []
    for p in mine:
        rank = adp_rank_by_id.get(p["mfl_id"])
        if rank is not None:
            values.append(
                {"player": p["player"], "pos": p["pos"], "pick_no": p["pick_no"], "value": p["pick_no"] - rank}
            )

    if not values:
        return {"n": 0, "avg": 0.0, "best": None, "worst": None}

    avg = sum(v["value"] for v in values) / len(values)
    return {
        "n": len(values),
        "avg": avg,
        "best": max(values, key=lambda v: v["value"]),
        "worst": min(values, key=lambda v: v["value"]),
    }


def bye_collisions(starters: dict, bye_week_by_mfl_id: dict) -> list[str]:
    """Flag bye weeks where 2+ starters (any slot, bench excluded) are out together.

    Cross-position on purpose: a starting RB and a starting WR sharing a bye
    week is just as much a hole in your lineup that week as two RBs sharing
    one.
    """
    weeks: dict[int, list[str]] = {}
    for players in starters.values():
        for p in players:
            wk = bye_week_by_mfl_id.get(p["mfl_id"])
            if wk is None:
                continue
            weeks.setdefault(wk, []).append(f"{p['player']} ({p['pos']})")

    return [
        f"bye week {wk}: {', '.join(names)}"
        for wk, names in sorted(weeks.items())
        if len(names) > 1
    ]
