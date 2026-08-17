"""Build the master ADP CSV.

    python main.py                 # normal run (uses today's cache if present)
    python main.py --no-cache      # force fresh pulls
    python main.py --templates     # write blank reference CSVs and exit
    python main.py --out board.csv

Sources: Fantasy Football Calculator (mock drafts), MyFantasyLeague (real
home leagues), ESPN (ESPN-platform drafts), plus any CSVs dropped in
reference/custom_sources/ (see reference_data.load_custom_sources). None of
them aggregate each other, so blending them is not double counting.
ADP data courtesy of Fantasy Football Calculator, MyFantasyLeague and ESPN.
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

import aggregate
import ids
import reference_data
from config import SCORING, SEASON, TEAMS, master_csv_path, norm_team
from sources import espn as espn_src
from sources import ffc as ffc_src
from sources import mfl as mfl_src


def _prep_source(df: pd.DataFrame, tag: str) -> pd.DataFrame:
    """Tag a matched source's identity columns (name/position/team) with its
    own suffix before merging, so any number of sources can merge on mfl_id
    without column collisions -- adding a 4th, 5th, ... source is just one
    more frame in the list, nothing here assumes exactly three."""
    rename = {c: f"{c}_{tag}" for c in ("name", "position", "team") if c in df.columns}
    return df.rename(columns=rename)


def _match_by_name_and_dst(
    df: pd.DataFrame, xwalk: pd.DataFrame, dst_xwalk: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Shared matching path for any name-keyed source (FFC, custom CSVs):
    team defenses go through the team-code crosswalk, everyone else through
    name+position matching. Returns (matched, unmatched)."""
    dst_rows = ids.attach_dst_mfl_id(df[df["position"] == "DST"], dst_xwalk)
    rest_matched, rest_unmatched = ids.attach_mfl_id_by_name(df[df["position"] != "DST"], xwalk)
    unmatched = pd.concat([rest_unmatched, dst_rows[dst_rows["mfl_id"].isna()]], ignore_index=True)
    matched = pd.concat([rest_matched, dst_rows[dst_rows["mfl_id"].notna()]], ignore_index=True)
    return matched, unmatched


def collect(use_cache: bool = True) -> tuple[pd.DataFrame, list[str], dict[str, str]]:
    """Fetch and merge every source. Returns (merged, adp_cols, pct_cols) --
    adp_cols is the full list of per-source ADP columns actually present
    (three built-in feeds plus whatever custom CSVs were found), and pct_cols
    maps the subset of those that have a real sample-size column."""
    xwalk = ids.load_crosswalk()
    print(f"crosswalk: {len(xwalk):,} players")

    # DynastyProcess's crosswalk has zero team-defense rows, so DST identity
    # is resolved by team code instead (see ids.attach_dst_mfl_id).
    dst_xwalk = mfl_src.fetch_dst_ids(use_cache=use_cache)
    print(f"dst xwalk: {len(dst_xwalk)} team defenses")

    # --- FFC: name-matched, DST matched by team -----------------------------
    ffc = ffc_src.fetch(use_cache=use_cache)
    ffc["pct_ffc"] = ffc_src.draft_pct(ffc)
    ffc_m, ffc_u = _match_by_name_and_dst(ffc, xwalk, dst_xwalk)
    print(f"ffc:  {len(ffc):>4} players, {len(ffc_u)} unmatched")
    if len(ffc_u):
        top_missed = ffc_u.nsmallest(min(10, len(ffc_u)), "adp_ffc")[["name", "position", "adp_ffc"]]
        print("      unmatched (lowest ADP first) -- add to ids.MANUAL_MFL_IDS if these matter:")
        for _, r in top_missed.iterrows():
            print(f"        {r['adp_ffc']:>6.1f}  {r['name']} ({r['position']})")
    ffc_m = ffc_m.rename(columns={"stdev": "adp_ffc_stdev"})
    ffc_m = ffc_m[["mfl_id", "name", "position", "team", "adp_ffc", "adp_ffc_stdev", "pct_ffc"]]
    ffc_m = ffc_m.drop_duplicates("mfl_id")

    # --- MFL: native mfl_id (already covers DST) ----------------------------
    mfl = mfl_src.fetch(use_cache=use_cache)
    print(f"mfl:  {len(mfl):>4} players")

    # --- ESPN: espn_id -> mfl_id via crosswalk, DST matched by team ---------
    espn = espn_src.fetch(use_cache=use_cache)
    corr = espn_src.espn_adp_vs_rank_corr(espn)
    print(f"espn: {len(espn):>4} players, ADP-vs-editorial-rank rho = {corr:.3f}")
    if corr > 0.98:
        print("      NOTE: near-perfect correlation with ESPN's own rankings. Autodraft is")
        print("      likely leaking in, meaning this feed partly restates ESPN's list.")

    espn_dst = ids.attach_dst_mfl_id(espn[espn["position"] == "DST"], dst_xwalk)
    espn_x = espn[espn["position"] != "DST"].merge(
        xwalk[["mfl_id", "espn_id"]].dropna(subset=["espn_id"]), on="espn_id", how="left"
    )
    espn_named, _ = ids.attach_mfl_id_by_name(
        espn_x[espn_x["mfl_id"].isna()].drop(columns=["mfl_id"]), xwalk
    )
    espn_m = pd.concat(
        [espn_x[espn_x["mfl_id"].notna()], espn_named, espn_dst], ignore_index=True
    )
    espn_m = espn_m[["mfl_id", "name", "position", "team", "adp_espn", "pct_espn"]]
    espn_m = espn_m.dropna(subset=["mfl_id"]).drop_duplicates("mfl_id")

    # --- custom: any CSV dropped in reference/custom_sources/ ---------------
    custom = reference_data.load_custom_sources()
    custom_matched: list[pd.DataFrame] = []
    pct_cols = {"adp_ffc": "pct_ffc", "adp_mfl": "pct_mfl", "adp_espn": "pct_espn"}
    for tag, csrc in custom.items():
        c_m, c_u = _match_by_name_and_dst(csrc, xwalk, dst_xwalk)
        print(f"{tag}: {len(csrc):>4} players, {len(c_u)} unmatched")
        c_m = c_m[["mfl_id", "name", "position", "team", f"adp_{tag}"]]
        c_m = c_m.dropna(subset=["mfl_id"]).drop_duplicates("mfl_id")
        custom_matched.append(c_m)

    # --- merge every source on mfl_id ---------------------------------------
    sources = [_prep_source(ffc_m, "ffc"), mfl, _prep_source(espn_m, "espn")]
    sources += [_prep_source(c_m, tag) for tag, c_m in zip(custom, custom_matched)]

    merged = sources[0]
    for src in sources[1:]:
        merged = merged.merge(src, on="mfl_id", how="outer")

    # Identity: prefer FFC's spelling, then ESPN's, then whichever custom
    # source has it -- first non-null wins, in the order sources were merged.
    for out_col, prefix in (("player", "name"), ("pos", "position"), ("team", "team")):
        tagged = [c for c in merged.columns if c.startswith(f"{prefix}_")]
        merged[out_col] = merged[tagged].bfill(axis=1).iloc[:, 0] if tagged else pd.NA

    fill = xwalk.set_index("mfl_id")[["name", "position", "team"]]
    for col, src in (("player", "name"), ("pos", "position"), ("team", "team")):
        gap = merged[col].isna()
        if gap.any():
            merged.loc[gap, col] = merged.loc[gap, "mfl_id"].map(fill[src])

    merged["team"] = merged["team"].map(norm_team)
    merged["pos"] = merged["pos"].fillna("").str.upper().replace({"PK": "K", "DEF": "DST"})

    adp_cols = ["adp_ffc", "adp_mfl", "adp_espn"] + [f"adp_{tag}" for tag in custom]
    return merged, adp_cols, pct_cols


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    offense = reference_data.load_offense()
    byeweeks = reference_data.load_byeweeks()
    out = df.merge(offense, on="team", how="left").merge(byeweeks, on="team", how="left")
    out["off_flag"] = out["off_flag"].fillna("")
    return out


def final_columns(adp_cols: list[str]) -> list[str]:
    cols = ["adp_rank", "adp_slot", "adp_master", "player", "pos", "team", "off_rank", "off_flag", "bye_week"]
    for col in adp_cols:
        cols.append(col)
        if col == "adp_ffc":
            cols.append("adp_ffc_stdev")
    cols += ["sources_n", "adp_spread", "mfl_id"]
    return cols


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true", help="force fresh HTTP pulls")
    ap.add_argument("--templates", action="store_true", help="write blank reference CSVs and exit")
    ap.add_argument("--out", default=None, help="output path")
    args = ap.parse_args()

    if args.templates:
        reference_data.write_templates(overwrite=True)
        print(f"Wrote blank templates to {reference_data.REFERENCE}")
        return 0

    print(f"=== {SEASON} {SCORING.upper()} {TEAMS}-team ===")
    merged, adp_cols, pct_cols = collect(use_cache=not args.no_cache)

    merged = aggregate.apply_sample_floor(merged, pct_cols)
    master = aggregate.build_master(merged, adp_cols)
    print(f"\nmaster: {len(master)} players in >= {aggregate.MIN_SOURCES} sources")
    print("\nsource agreement (spearman):")
    print(aggregate.source_agreement(merged, adp_cols).to_string())

    master = enrich(master)

    cols = final_columns(adp_cols)
    for col in cols:
        if col not in master.columns:
            master[col] = pd.NA
    master = master[cols]

    out_path = args.out or master_csv_path()
    master.to_csv(out_path, index=False)
    print(f"\nwrote {out_path}")

    flagged = master[master["off_flag"] != ""]
    print(f"\ntop-30 board, offence-flagged players marked:")
    print(
        master.head(30)[["adp_rank", "adp_slot", "player", "pos", "team", "off_flag", "adp_spread"]]
        .to_string(index=False)
    )
    print(f"\n{len(flagged)} players on flagged offences overall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
