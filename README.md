# ADP Master: 2026, PPR, 12-team

Blends three independent ADP feeds into one master board, then layers a live
draft-day assistant on top.

## Quickstart

```
pip install -r requirements.txt
python main.py                          # builds the ADP board
python -m streamlit run draft_gui.py    # live draft tracker, at localhost:8501
```

Reference data (offense and bye-week rankings) is already filled in for
2026, nothing to configure to try it. Re-run `python main.py` any time for
fresher ADP numbers; board writes to `output/adp_master_2026_ppr_12tm.csv`.

## Sources

| Feed | Population | Auth | Notes |
|---|---|---|---|
| Fantasy Football Calculator | Mock drafts on FFC's site, computer picks stripped | none | Free for personal + commercial use, attribution requested, updates once daily |
| MyFantasyLeague | Real home-league drafts run on MFL | none | No imported drafts accepted, so genuinely independent. Cache, don't retry on failure, watch for 429 |
| ESPN (undocumented v3) | Drafts on ESPN's platform | none | `X-Fantasy-Filter` header mandatory or you get 50 players. Schema can change without notice |

None of the three aggregates the others, so blending them isn't double
counting. They *are* correlated (same news cycle, same rankings sites), which
is expected and fine.

### Adding your own source

Drop a CSV into `reference/custom_sources/` with `player` and `adp` columns
(`position` and `team` too, recommended, they're what makes matching
reliable) and it's automatically blended in as one more feed, no code to
write. The filename becomes the source tag, so `friends_mock.csv` shows up as
column `adp_friends_mock`, folded into `adp_master`/`adp_rank` and the source
agreement table right alongside FFC/MFL/ESPN. Team defenses in a custom file
are matched by team code same as the built-in feeds; everyone else by name.

Unlike the three fetched feeds, a custom source has no sample-size concept,
so it never gets filtered by `MIN_DRAFT_PCT`, a hand-typed list is trusted at
face value.

Adding a genuinely new *live* source (another site's API, not a static list)
means writing a `sources/yourname.py` with a `fetch()` following the pattern
in `sources/ffc.py`, then wiring it into `main.py`'s `collect()` the same way
FFC is. `aggregate.py` doesn't hardcode a source count, so nothing else needs
to change.

## Columns

`adp_rank` `adp_slot` `adp_master` `player` `pos` `team` `off_rank` `off_flag`
`bye_week` `adp_ffc` `adp_ffc_stdev` `adp_mfl` `adp_espn` `sources_n`
`adp_spread` `mfl_id`

- **adp_master**: median of the raw ADPs. Read this as "where he goes".
- **adp_rank**: median of within-source *ranks*, re-ranked. Use for ordering;
  ranks are the scale-safe comparison across feeds with different depth.
- **adp_spread**: max minus min across feeds. Big spreads mean platform
  format is driving the price, not consensus.
- **off_flag**: `TOP5` / `BOT5` from your `offense.csv`.
- **adp_ffc_stdev**: FFC's per-player ADP standard deviation, used by the
  live draft tracker's survival-probability calc.

## The hand-maintained files

`reference/offense.csv` (`team`, `off_rank`) and `reference/byeweeks.csv`
(`team`, `bye_week`). Neither has a free API worth trusting. 32 rows each,
validated hard on load (offense ranks exactly 1-32, byeweeks just needs every
team present). A half-filled table crashes rather than quietly producing a
plausible-looking board. Re-check offense.csv after final cuts.

Starting a new season from scratch: `python main.py --templates` writes blank
versions of both, ready to fill in.

## Live draft tracker

`python -m streamlit run draft_gui.py` (see Quickstart above), a local,
manual-entry app, no ESPN integration, no network, that you run
alongside your real draft and update pick by pick. You only enter *who* got
picked, with one click: search narrows the "Draft a player" list, click
**Draft** on a row. Or use the **quick draft** box at the top: type a name and
press Enter (or click "Draft top match") to draft the best-ranked undrafted
match immediately, no scrolling. Whether it was *your* pick is derived
automatically from the pick count and your draft slot (standard snake order).
Only your own roster is tracked, not the other 11.

Your draft slot is set live in the sidebar (**My draft slot**), no restart
needed. Ownership of each recorded pick is recomputed from the current slot
on every load, so correcting your slot mid-draft re-attributes your roster
instead of leaving stale picks behind. `ROSTER_SLOTS` (starting lineup +
bench, currently QB1 RB2 WR2 TE1 FLEX1 K1 DST1 BN6) lives in `config.py`.

On top of the static board:
- **tier**: within-position groups; a new tier starts when the `adp_rank` gap
  to the previous player exceeds `config.TIER_GAP_RANK`. Resets per
  position, so a WR tier 2 isn't the RB tier 2. Fixed against the full
  pre-draft board so it can't fracture as players come off it.
- **value_delta**: pick number minus `adp_rank`, also shown in fractional
  rounds. Positive means falling past consensus.
- **survival_prob**: modeled probability the player lasts to your next pick,
  using FFC's real per-player stdev where available, `adp_spread / 4` as a
  rough fallback otherwise.
- **Recent picks**: a position-colored trail of the last 15 picks
  league-wide, hover for the name.
- **positional-run banner**: flags a position at 3+ of the last 6 picks.
- **tier depletion**: each row's tier badge shows "X/Y left", color-coded by
  urgency, counted against that player's fixed tier group.
- **My Roster** (sidebar): starters filled before bench, in draft order, plus
  a warning when 2+ starters share a bye week.
- **NEED badge**: flags a player whose position fills one of your still-open
  starter slots (including FLEX for RB/WR/TE). Bench needs don't count,
  since almost every remaining player "needs" bench eventually and that's
  not a useful signal. Also a `fills_need` column in the "Board" table.

### Digging into value_delta

- **Biggest Fallers**: leaderboard of players falling most past consensus,
  ranked by `scarcity_value` (below), only once past
  `config.VALUE_FALL_THRESHOLD` (default 5 picks).
- **scarcity_value**: `value_delta` multiplied by how depleted that player's
  tier is (1x untouched, up to 2x nearly gone).
- **ACT NOW / VALUE, SAFE badges**: combines `value_delta` with
  `survival_prob`. Falling and unlikely to survive
  (`config.ACT_NOW_SURVIVAL`, default 30%) flags red; falling but safe to
  wait (`config.SAFE_VALUE_SURVIVAL`, default 50%) flags green.
- **My Draft Value** (sidebar): running self-scorecard across your own
  picks, average value, best pick, biggest reach. No opponent comparison.

### Mock draft mode

**Simulate 1 CPU pick** / **Simulate to my next pick** auto-fill other teams'
picks so you can rehearse a full draft without recording all 11 opponents.
Both disabled on your own turn.

Once your roster is completely full, an **"Auto-finish draft with CPU
picks"** button appears to fill the remaining rounds in one click. It's a
button, not automatic: this app also tracks real drafts, and auto-firing CPU
picks the instant your roster fills would silently overwrite real opponents'
picks you're still recording. Once the whole draft
(`TEAMS x sum(ROSTER_SLOTS)` picks) is done, a "Draft complete" banner
replaces the pick-entry sections; roster, value scorecard, and the final
board stay visible.

**Start Over** (sidebar) clears the pick log for a new draft. Gated behind a
"Yes, clear this draft" checkbox since it's destructive. Keeps your draft
slot; only the picks reset.

CPU picks are stateless on purpose, no roster-need modeling for opponents,
just a weighted random draw from the top `config.MOCK_POOL_SIZE` available
players by `adp_rank` (geometric decay via `config.MOCK_DECAY`). Mostly the
consensus top player, occasionally a slight reach or fall.

State lives in `draft/session_{SEASON}.json`. Delete it, or use Start Over,
for a fresh session.

## Future ideas

Noted but not built, mostly because the data isn't free the way ADP is:
- **Real value-based drafting (VBD)**: needs actual point projections, not
  just ADP.
- **Handcuff / depth-chart awareness**: needs a depth-chart feed we don't
  have.
- **Opponent-need-aware pick suggestions**: blend value, tier, open roster
  slots, and bye fit into one "best pick right now" score.
- **Day-over-day ADP drift**: `cache/` already stores dated JSON snapshots;
  diffing them would show risers/fallers over the preseason for free.

## Tuning

In `config.py`:
- `MIN_SOURCES = 2`: appear in at least 2 of 3 feeds
- `MIN_DRAFT_PCT = 5.0`: per-source floor; a player taken in 3% of drafts has
  an ADP, but it's the price three people paid, not a market
- `TOP_N_FLAG = 5`

## Known failure modes

1. **Name matching.** FFC has no shared player id, so it goes through
   normalised name + position. Rookies and suffix changes break first. The
   run prints unmatched players lowest-ADP-first; add them to
   `ids.MANUAL_MFL_IDS` rather than loosening the matcher. Team defenses are
   handled separately: DynastyProcess's crosswalk has zero DST rows, so
   they're matched by team code instead, via `sources.mfl.fetch_dst_ids()`
   and `ids.attach_dst_mfl_id`.
2. **MFL early preseason.** The filtered pool (`IS_MOCK=0`, `IS_KEEPER=0`)
   can be genuinely empty in July. Try `PERIOD=ALL` or a lower `CUTOFF`.
3. **ESPN autodraft.** ESPN doesn't say whether autodrafted picks are
   excluded. The run prints the Spearman between ESPN ADP and ESPN's own
   editorial rank; above ~0.98 means the feed is partly restating ESPN's
   list, and you should think about down-weighting it.

## Attribution

ADP data courtesy of Fantasy Football Calculator, MyFantasyLeague and ESPN.
Player ID crosswalk from DynastyProcess.
