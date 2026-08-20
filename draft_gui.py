"""Live draft tracker. Run alongside your actual draft (ESPN, paper, whatever)
and record each pick as it happens.

    python -m streamlit run draft_gui.py

Nothing here talks to ESPN or any network -- it's a manual pick log plus the
live board/roster views computed from it. State persists to draft/session_*
.json, so closing the tab mid-draft loses nothing.
"""
from __future__ import annotations

import streamlit as st

import draft_state
import live_board
import mock_draft
import reference_data
from config import (
    ACT_NOW_SURVIVAL,
    CUSTOM_SOURCES,
    FALLERS_SHOWN,
    OLINE_BOTTOM,
    OLINE_TOP5,
    ROSTER_SLOTS,
    SAFE_VALUE_SURVIVAL,
    SEASON,
    TEAMS,
    VALUE_FALL_THRESHOLD,
)

st.set_page_config(page_title=f"ADP Master {SEASON} -- Live Draft", layout="wide")

# Medal colors for the first three tiers, then a repeating muted set -- tiers
# are per-position and can run deep (a dozen+), so past bronze this is just
# "same color = same tier," not a medal claim.
TIER_COLORS = [
    "rgba(255, 215, 0, 0.28)",   # 1: gold
    "rgba(192, 192, 192, 0.30)",  # 2: silver
    "rgba(205, 127, 50, 0.28)",  # 3: bronze
    "rgba(100, 181, 246, 0.20)",
    "rgba(129, 199, 132, 0.20)",
    "rgba(186, 104, 200, 0.20)",
    "rgba(255, 138, 101, 0.20)",
    "rgba(77, 208, 225, 0.20)",
]

POS_COLORS = {
    "QB": "#3a86ff", "RB": "#2a9d8f", "WR": "#f4a261",
    "TE": "#9b5de5", "K": "#adb5bd", "DST": "#495057",
}

OFF_FLAG_STYLE = {
    "TOP5": ("#06d6a0", "#0b3d2e", "TOP5 OFFENCE"),
    "BOT5": ("#ef476f", "#4a0d1e", "BOT5 OFFENCE"),
}


def _badge(text: str, bg: str, fg: str = "#ffffff") -> str:
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 7px;border-radius:5px;'
        f'font-size:0.78rem;font-weight:700;margin-right:5px;white-space:nowrap;">{text}</span>'
    )


def tier_color(tier) -> str:
    return TIER_COLORS[(int(tier) - 1) % len(TIER_COLORS)]


def row_background(pos: str, tier) -> str:
    """Left 10% solid position color, right 90% the tier tint -- a hard-edge
    split so the position reads as a distinct marker, not just another tint."""
    pos_c = POS_COLORS.get(pos, "#6c757d")
    tier_c = tier_color(tier)
    return f"linear-gradient(to right, {pos_c} 0%, {pos_c} 10%, {tier_c} 10%, {tier_c} 100%)"


def depletion_color(remaining: int, total: int) -> str:
    if total == 0:
        return "#6c757d"
    if remaining <= 1:
        return "#ef476f"  # critical -- last one (or none) left in this tier
    if remaining / total <= 0.34:
        return "#ffb703"  # getting thin
    return "#6c757d"  # plenty left, neutral


def survival_color(prob: float) -> str:
    if prob != prob:  # NaN
        return "#6c757d"
    if prob < 0.2:
        return "#ef476f"  # unlikely to survive to your next pick -- act now
    if prob < 0.5:
        return "#ffb703"
    return "#2a9d8f"  # comfortably likely to still be there


def value_signal(value_delta: float, survival_prob: float) -> tuple[str, str, str] | None:
    """Combine value_delta and survival_prob into one "what do I do" read.

    None for anything that isn't meaningfully falling -- keeps the badge only
    on rows where it's actually saying something.
    """
    if value_delta != value_delta or value_delta < VALUE_FALL_THRESHOLD:
        return None
    if survival_prob == survival_prob and survival_prob < ACT_NOW_SURVIVAL:
        return ("ACT NOW", "#ef476f", "#ffffff")
    if survival_prob == survival_prob and survival_prob >= SAFE_VALUE_SURVIVAL:
        return ("VALUE, SAFE", "#2a9d8f", "#ffffff")
    return ("VALUE", "#ffb703", "#3d2b00")


def fmt_value(delta: float, rounds: float) -> str:
    return f"{delta:+.0f} ({rounds:+.1f} rd)"


def render_player_row(row, key_prefix: str, depletion_lookup: dict, my_starter_byes: set) -> None:
    """One player row: tier/depletion, pos/team/flags, bye, value, survival, Draft button.

    Shared by the "Draft a player" list and the "Biggest Fallers" leaderboard
    -- key_prefix keeps their Streamlit widget keys from colliding when the
    same player shows up in both.
    """
    with st.container(key=f"{key_prefix}_{row.mfl_id}"):
        # Columns [1, 5, 1, 1, 1, 1] out of 10 -- first column is exactly 10%,
        # matching the row_background() split so the position label lands
        # inside its own solid-color zone instead of spilling into the tier tint.
        c = st.columns([1, 5, 1, 1, 1, 1])
        c[0].markdown(
            f'<div style="color:#ffffff;font-weight:800;font-size:0.85rem;line-height:1.1;">{row.pos}</div>'
            f'<div style="color:#ffffff;font-size:0.62rem;opacity:0.9;">#{int(row.adp_rank)}</div>',
            unsafe_allow_html=True,
        )

        remaining, total = depletion_lookup.get((row.pos, int(row.tier)), (0, 0))
        tier_badge = _badge(f"T{int(row.tier)} · {remaining}/{total}", depletion_color(remaining, total))
        badges = tier_badge + _badge(row.team, "#212529")
        if row.off_flag in OFF_FLAG_STYLE:
            bg, fg, label = OFF_FLAG_STYLE[row.off_flag]
            badges += _badge(label, bg, fg)
        if row.pos in ("RB", "QB"):
            if row.team in OLINE_TOP5:
                badges += _badge("TOP5 OL", "#d4af37", "#2b1d00")
            elif row.team in OLINE_BOTTOM:
                badges += _badge("BOT6 OL", "#ef476f", "#ffffff")
        if row.is_rookie:
            badges += _badge("ROOKIE", "#00b4d8")
        signal = value_signal(row.value_delta, row.survival_prob)
        if signal:
            label, bg, fg = signal
            badges += _badge(label, bg, fg)
        if fills_need(row.pos):
            badges += _badge("NEED", "#118ab2")
        c[1].markdown(f"**{row.player}**  {badges}", unsafe_allow_html=True)

        if row.bye_week == row.bye_week:
            wk = int(row.bye_week)
            bye_bg = "#ef476f" if wk in my_starter_byes else "#6c757d"
            c[2].markdown(_badge(f"BYE {wk}", bye_bg), unsafe_allow_html=True)
        else:
            c[2].write("")
        c[3].write(fmt_value(row.value_delta, row.value_delta_rounds))
        survive_badge = _badge(
            f"{row.survival_prob:.0%} @ your next" if row.survival_prob == row.survival_prob else "--",
            survival_color(row.survival_prob),
        )
        c[4].markdown(survive_badge, unsafe_allow_html=True)
        if c[5].button("Draft", key=f"{key_prefix}_btn_{row.mfl_id}"):
            draft_state.record_pick(row.mfl_id, row.player, row.pos)
            st.rerun()


session = draft_state.load_session()
my_slot = session["my_slot"]
picks = session["picks"]

roster = draft_state.my_roster(picks, my_slot=my_slot)
bye_lookup = live_board.bye_week_lookup()
my_starter_byes = {
    bye_lookup[p["mfl_id"]]
    for players in roster["starters"].values()
    for p in players
    if p["mfl_id"] in bye_lookup
}
TOTAL_DRAFT_PICKS = TEAMS * draft_state.total_roster_picks()
draft_complete = len(picks) >= TOTAL_DRAFT_PICKS
roster_full = draft_state.is_roster_full(roster)

with st.sidebar:
    st.subheader("Settings")
    new_slot = st.number_input("My draft slot", min_value=1, max_value=TEAMS, value=my_slot, step=1)
    if new_slot != my_slot:
        draft_state.set_my_slot(int(new_slot))
        st.rerun()

    st.subheader("Start Over")
    confirm_reset = st.checkbox("Yes, clear this draft")
    if st.button("Start New Draft", disabled=not confirm_reset):
        draft_state.reset_session()
        st.rerun()

    st.subheader("Custom ADP Source")
    uploaded = st.file_uploader(
        "Add your own ranking CSV",
        type="csv",
        help="Needs a 'player' column and an ADP-like column (adp / consensus / "
        "average / avg) -- 'position' and 'team' recommended too, for reliable "
        "matching. Saved to reference/custom_sources/; run `python main.py` "
        "afterward to rebuild the board with it blended in.",
    )
    if uploaded is not None:
        upload_key = (uploaded.name, uploaded.size)
        if st.session_state.get("_custom_upload_key") != upload_key:
            st.session_state["_custom_upload_key"] = upload_key
            try:
                tag, n = reference_data.save_custom_source(uploaded.name, uploaded.getvalue())
                st.session_state["_custom_upload_result"] = (
                    "success", f"Saved as source `{tag}` ({n} players). Run `python main.py` to rebuild the board."
                )
            except ValueError as e:
                st.session_state["_custom_upload_result"] = ("error", str(e))
        kind, msg = st.session_state.get("_custom_upload_result", (None, None))
        if kind == "success":
            st.success(msg)
        elif kind == "error":
            st.error(msg)

    existing_sources = sorted(CUSTOM_SOURCES.glob("*.csv")) if CUSTOM_SOURCES.exists() else []
    if existing_sources:
        st.caption("Active custom sources:")
        for f in existing_sources:
            st.caption(f"- {f.name}")

    st.subheader("My Roster")

    def _with_bye(p: dict) -> str:
        wk = bye_lookup.get(p["mfl_id"])
        return f"{p['player']} (Wk {wk})" if wk is not None else p["player"]

    st.markdown("**Starters**")
    for pos in list(ROSTER_SLOTS.keys()):
        if pos == "BN":
            continue
        filled = roster["starters"].get(pos, [])
        names = ", ".join(_with_bye(p) for p in filled) or "--"
        open_n = roster["open"].get(pos, 0)
        suffix = f"  _(needs {open_n})_" if open_n else ""
        st.markdown(f"- **{pos}**: {names}{suffix}")

    st.markdown("**Bench**")
    if roster["bench"]:
        for p in roster["bench"]:
            st.markdown(f"- {_with_bye(p)} ({p['pos']})")
    else:
        st.markdown("--")

    for c in draft_state.bye_collisions(roster["starters"], bye_lookup):
        st.warning(f"Bye-week collision -- {c}")

    st.subheader("My Draft Value")
    adp_rank_lookup = live_board.adp_rank_lookup()
    value_summary = draft_state.my_value_summary(picks, my_slot=my_slot, adp_rank_by_id=adp_rank_lookup)
    if value_summary["n"] == 0:
        st.markdown("No picks yet.")
    else:
        avg = value_summary["avg"]
        st.metric("Avg value / pick", f"{avg:+.1f} ({avg / TEAMS:+.2f} rd)")
        b, w = value_summary["best"], value_summary["worst"]
        st.markdown(f"Best value: **{b['player']}** ({b['pos']}) at pick {b['pick_no']} — {b['value']:+d}")
        st.markdown(f"Biggest reach: **{w['player']}** ({w['pos']}) at pick {w['pick_no']} — {w['value']:+d}")

pick_no = len(picks) + 1
on_clock = draft_state.on_the_clock(pick_no, my_slot=my_slot)
until_mine = draft_state.picks_until_my_turn(picks, my_slot=my_slot)

st.title(f"{SEASON} Draft Tracker")

header = st.columns(3)
header[0].metric("Pick #", pick_no)
header[1].metric("On the clock", f"Slot {on_clock}" + (" (You)" if on_clock == my_slot else ""))
header[2].metric("Picks until your turn", until_mine if until_mine > 0 else "You're up")

if draft_complete:
    st.success("🏁 Draft complete — every roster spot across the league has been filled.")
elif roster_full:
    st.info("Your roster is full.")
    if st.button("Auto-finish draft with CPU picks"):
        finish_board = live_board.build(picks, my_slot=my_slot)
        safety = 0
        while not finish_board.empty and len(picks) < TOTAL_DRAFT_PICKS and safety < TEAMS * 30:
            cpu_row = mock_draft.pick_for_cpu(finish_board)
            picks = draft_state.record_pick(cpu_row["mfl_id"], cpu_row["player"], cpu_row["pos"])
            finish_board = finish_board[finish_board["mfl_id"] != cpu_row["mfl_id"]]
            safety += 1
        st.rerun()

board = live_board.build(picks, my_slot=my_slot)
depletion = live_board.tier_depletion(picks)
depletion_lookup = {
    (r.pos, int(r.tier)): (int(r.remaining), int(r.total)) for r in depletion.itertuples()
}


def fills_need(pos: str, roster: dict = roster) -> bool:
    """True if drafting this position fills one of your still-open starter
    slots (including FLEX for RB/WR/TE) -- not a bench-filler count, since
    almost everyone "needs" bench eventually and that's not a useful signal."""
    open_slots = roster["open"]
    if open_slots.get(pos, 0) > 0:
        return True
    return pos in draft_state.FLEX_ELIGIBLE and open_slots.get("FLEX", 0) > 0


board["fills_need"] = board["pos"].map(fills_need)


if not draft_complete:
    with st.form("quick_draft", clear_on_submit=True):
        qcol1, qcol2 = st.columns([5, 1])
        quick_name = qcol1.text_input(
            "Quick draft", placeholder="Type a name, press Enter to draft the top match",
            label_visibility="collapsed",
        )
        quick_submitted = qcol2.form_submit_button("Draft top match", use_container_width=True)
    if quick_submitted and quick_name:
        quick_matches = board[board["player"].str.contains(quick_name, case=False, na=False)]
        quick_matches = quick_matches.sort_values("adp_rank")
        if quick_matches.empty:
            st.warning(f"No undrafted player matches \"{quick_name}\".")
        else:
            top = quick_matches.iloc[0]
            draft_state.record_pick(top["mfl_id"], top["player"], top["pos"])
            st.rerun()

RECENT_N = 15
if picks:
    trail = "".join(
        f'<span title="{p["player"]}" style="background:{POS_COLORS.get(p["pos"], "#6c757d")};'
        f'color:#ffffff;padding:2px 8px;border-radius:5px;font-size:0.78rem;font-weight:700;'
        f'margin-right:4px;white-space:nowrap;">{p["pos"]}</span>'
        for p in picks[-RECENT_N:]
    )
    st.markdown(f"**Recent picks** (oldest → newest, hover for name)  \n{trail}", unsafe_allow_html=True)

run = live_board.positional_run(picks)
if run:
    st.warning(run)

if picks:
    last = picks[-1]
    if st.button(f"Undo last pick ({last['player']})"):
        draft_state.undo_last_pick()
        st.rerun()

if not draft_complete:
    mock_cols = st.columns(2)
    its_your_turn = on_clock == my_slot
    if mock_cols[0].button("Simulate 1 CPU pick", disabled=its_your_turn):
        cpu_row = mock_draft.pick_for_cpu(board)
        draft_state.record_pick(cpu_row["mfl_id"], cpu_row["player"], cpu_row["pos"])
        st.rerun()

    if mock_cols[1].button("Simulate to my next pick", disabled=its_your_turn):
        sim_board = board.copy()
        next_no = pick_no
        safety = 0
        while (
            draft_state.on_the_clock(next_no, my_slot=my_slot) != my_slot
            and not sim_board.empty
            and safety < TEAMS * 20
        ):
            cpu_row = mock_draft.pick_for_cpu(sim_board)
            draft_state.record_pick(cpu_row["mfl_id"], cpu_row["player"], cpu_row["pos"])
            sim_board = sim_board[sim_board["mfl_id"] != cpu_row["mfl_id"]]
            next_no += 1
            safety += 1
        st.rerun()

    st.subheader("Biggest Fallers")
    st.caption(
        "Ranked by value_delta, weighted for how depleted each player's tier is -- "
        "falling in a nearly-drafted-out tier counts for more than falling in a deep one."
    )
    fallers = board[board["value_delta"] >= VALUE_FALL_THRESHOLD].sort_values("scarcity_value", ascending=False)
    faller_rows = list(fallers.head(FALLERS_SHOWN).itertuples())
    if faller_rows:
        st.markdown(
            "<style>" + "\n".join(
                f'.st-key-fallrow_{r.mfl_id} {{ background: {row_background(r.pos, r.tier)}; '
                f'border-radius: 6px; padding: 4px 8px; margin-bottom: 2px; }}'
                for r in faller_rows
            ) + "</style>",
            unsafe_allow_html=True,
        )
        for row in faller_rows:
            render_player_row(row, "fallrow", depletion_lookup, my_starter_byes)
    else:
        st.caption("Nobody's fallen meaningfully past consensus yet.")

    st.subheader("Draft a player")
    search = st.text_input("Search", placeholder="Type a name to filter, or leave blank for the top of the board...")
    board_sorted = board.sort_values("adp_rank")
    candidates = board_sorted
    if search:
        candidates = candidates[candidates["player"].str.contains(search, case=False, na=False)]

    SHOW = 25
    visible_rows = list(candidates.head(SHOW).itertuples())

    st.markdown(
        "<style>" + "\n".join(
            f'.st-key-draftrow_{r.mfl_id} {{ background: {row_background(r.pos, r.tier)}; '
            f'border-radius: 6px; padding: 4px 8px; margin-bottom: 2px; }}'
            for r in visible_rows
        ) + "</style>",
        unsafe_allow_html=True,
    )

    for row in visible_rows:
        render_player_row(row, "draftrow", depletion_lookup, my_starter_byes)

    if len(candidates) > SHOW:
        st.caption(f"{len(candidates) - SHOW} more match -- narrow your search to see them")
    elif len(candidates) == 0:
        st.caption("No undrafted players match that search.")

st.subheader("Board")
pos_filter = st.multiselect("Position", sorted(board["pos"].dropna().unique()))
view = board if not pos_filter else board[board["pos"].isin(pos_filter)]
st.dataframe(
    view[
        [
            "adp_rank", "tier", "player", "pos", "team", "fills_need", "bye_week",
            "value_delta", "value_delta_rounds", "scarcity_value", "survival_prob",
            "off_flag", "adp_master", "adp_spread",
        ]
    ].style.format({
        "survival_prob": "{:.0%}", "adp_master": "{:.1f}", "adp_spread": "{:.1f}",
        "value_delta_rounds": "{:+.1f}", "scarcity_value": "{:+.1f}",
    }),
    hide_index=True,
    use_container_width=True,
    height=600,
)
