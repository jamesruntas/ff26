"""Build the master ADP CSV.

    python main.py                 # normal run (uses today's cache if present)
    python main.py --no-cache      # force fresh pulls
    python main.py --templates     # write blank reference CSVs and exit
    python main.py --out board.csv

Sources: Fantasy Football Calculator (mock drafts), MyFantasyLeague (real
home leagues), ESPN (ESPN-platform drafts). All three are single-platform --
none of them aggregates the others -- so blending them is not double counting.
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

FINAL_COLUMNS = [
    "adp_rank", "adp_slot", "adp_master", "player", "pos", "team",
    "off_rank", "off_flag", "bye_week",
    "adp_ffc", "adp_ffc_stdev", "adp_mfl", "adp_espn", "sources_n", "adp_spread",
    "mfl_id",
]


def collect(use_cache: bool = True) -> pd.DataFrame:
    xwalk = ids.load_crosswalk()
    print(f"crosswalk: {len(xwalk):,} players")

    # DynastyProcess's crosswalk has zero team-defense rows, so DST identity
    # is resolved by team code instead (see ids.attach_dst_mfl_id).
    dst_xwalk = mfl_src.fetch_dst_ids()
    print(f"dst xwalk: {len(dst_xwalk)} team defenses")

    # --- FFC: name-matched, DST matched by team -----------------------------
    ffc = ffc_src.fetch()
    ffc["pct_ffc"] = ffc_src.draft_pct(ffc)
    ffc_dst = ids.attach_dst_mfl_id(ffc[ffc["position"] == "DST"], dst_xwalk)
    ffc_m_rest, ffc_u = ids.attach_mfl_id_by_name(ffc[ffc["position"] != "DST"], xwalk)
    ffc_u = pd.concat([ffc_u, ffc_dst[ffc_dst["mfl_id"].isna()]], ignore_index=True)
    ffc_m = pd.concat([ffc_m_rest, ffc_dst[ffc_dst["mfl_id"].notna()]], ignore_index=True)
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
    mfl = mfl_src.fetch()
    print(f"mfl:  {len(mfl):>4} players")

    # --- ESPN: espn_id -> mfl_id via crosswalk, DST matched by team ---------
    espn = espn_src.fetch()
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

    # --- merge on mfl_id ---------------------------------------------------
    merged = ffc_m.merge(mfl, on="mfl_id", how="outer").merge(
        espn_m, on="mfl_id", how="outer", suffixes=("", "_espn")
    )

    # Identity: prefer FFC's spelling, fall back to ESPN, then the crosswalk.
    merged["player"] = merged["name"].fillna(merged.get("name_espn"))
    merged["pos"] = merged["position"].fillna(merged.get("position_espn"))
    merged["team"] = merged["team"].fillna(merged.get("team_espn"))

    fill = xwalk.set_index("mfl_id")[["name", "position", "team"]]
    for col, src in (("player", "name"), ("pos", "position"), ("team", "team")):
        gap = merged[col].isna()
        if gap.any():
            merged.loc[gap, col] = merged.loc[gap, "mfl_id"].map(fill[src])

    merged["team"] = merged["team"].map(norm_team)
    merged["pos"] = merged["pos"].fillna("").str.upper().replace({"PK": "K", "DEF": "DST"})
    return merged


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    offense = reference_data.load_offense()
    byeweeks = reference_data.load_byeweeks()
    out = df.merge(offense, on="team", how="left").merge(byeweeks, on="team", how="left")
    out["off_flag"] = out["off_flag"].fillna("")
    return out


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
    merged = collect(use_cache=not args.no_cache)

    merged = aggregate.apply_sample_floor(
        merged, {"adp_ffc": "pct_ffc", "adp_mfl": "pct_mfl", "adp_espn": "pct_espn"}
    )
    master = aggregate.build_master(merged)
    print(f"\nmaster: {len(master)} players in >= {aggregate.MIN_SOURCES} sources")
    print("\nsource agreement (spearman):")
    print(aggregate.source_agreement(merged).to_string())

    master = enrich(master)

    for col in FINAL_COLUMNS:
        if col not in master.columns:
            master[col] = pd.NA
    master = master[FINAL_COLUMNS]

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
