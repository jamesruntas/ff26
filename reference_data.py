"""The hand-maintained inputs: projected offence rank, bye weeks, and any
custom ADP sources you drop in.

Neither offense nor byeweeks has a free API worth trusting -- sportsbooks
price win totals, not "offence rankings", and bye weeks are schedule trivia
nobody bothers to publish as a clean feed. Transcribing them by hand once and
re-checking offense.csv after cuts is the correct answer here, not a
workaround.

Both files are validated hard on load: all 32 teams present, no blanks. A
half-filled reference table that silently produces a plausible-looking CSV is
worse than a crash.
"""
from __future__ import annotations

import pandas as pd

from config import CUSTOM_SOURCES, NFL_TEAMS, REFERENCE, TOP_N_FLAG, norm_team

OFFENSE_CSV = REFERENCE / "offense.csv"
BYEWEEKS_CSV = REFERENCE / "byeweeks.csv"


def _check_teams(df: pd.DataFrame, col: str, path) -> pd.DataFrame:
    """Shared shape check: all 32 teams present, none unrecognised, none blank."""
    df = df.copy()
    df["team"] = df["team"].map(norm_team)

    missing = set(NFL_TEAMS) - set(df["team"])
    extra = set(df["team"]) - set(NFL_TEAMS)
    if missing:
        raise ValueError(f"{path.name}: missing teams {sorted(missing)}")
    if extra:
        raise ValueError(f"{path.name}: unrecognised teams {sorted(extra)}")

    blank = df[df[col].isna()]["team"].tolist()
    if blank:
        raise ValueError(
            f"{path.name}: {col} is empty for {sorted(blank)}. "
            "Fill the template before running -- this file has no automated source."
        )
    return df


def _validate_offense(df: pd.DataFrame, rank_col: str, path) -> pd.DataFrame:
    df = _check_teams(df, rank_col, path)
    df[rank_col] = pd.to_numeric(df[rank_col], errors="coerce").astype("Int64")
    ranks = sorted(df[rank_col].dropna().tolist())
    if ranks != list(range(1, 33)):
        dupes = df[df[rank_col].duplicated(keep=False)]["team"].tolist()
        raise ValueError(
            f"{path.name}: {rank_col} must be exactly 1..32 with no gaps or ties. "
            f"Duplicated on {sorted(dupes)}." if dupes
            else f"{path.name}: {rank_col} must be exactly 1..32 with no gaps."
        )
    return df


def _validate_byeweeks(df: pd.DataFrame, path) -> pd.DataFrame:
    df = _check_teams(df, "bye_week", path)
    df["bye_week"] = pd.to_numeric(df["bye_week"], errors="coerce").astype("Int64")
    bad = df[(df["bye_week"] < 4) | (df["bye_week"] > 14)]["team"].tolist()
    if bad:
        raise ValueError(f"{path.name}: implausible bye_week (expected 4-14) for {sorted(bad)}.")
    return df


def load_offense() -> pd.DataFrame:
    if not OFFENSE_CSV.exists():
        write_templates()
        raise FileNotFoundError(f"Created template at {OFFENSE_CSV}. Fill it in and re-run.")

    df = _validate_offense(pd.read_csv(OFFENSE_CSV), "off_rank", OFFENSE_CSV)
    df["off_flag"] = ""
    df.loc[df["off_rank"] <= TOP_N_FLAG, "off_flag"] = "TOP5"
    df.loc[df["off_rank"] > 32 - TOP_N_FLAG, "off_flag"] = "BOT5"
    return df[["team", "off_rank", "off_flag"]]


def load_byeweeks() -> pd.DataFrame:
    if not BYEWEEKS_CSV.exists():
        write_templates()
        raise FileNotFoundError(f"Created template at {BYEWEEKS_CSV}. Fill it in and re-run.")

    df = _validate_byeweeks(pd.read_csv(BYEWEEKS_CSV), BYEWEEKS_CSV)
    return df[["team", "bye_week"]]


def write_templates(overwrite: bool = False) -> None:
    """Emit blank 32-row templates. Ranks/weeks are left empty on purpose."""
    if overwrite or not OFFENSE_CSV.exists():
        pd.DataFrame({"team": NFL_TEAMS, "off_rank": ""}).to_csv(OFFENSE_CSV, index=False)
    if overwrite or not BYEWEEKS_CSV.exists():
        pd.DataFrame({"team": NFL_TEAMS, "bye_week": ""}).to_csv(BYEWEEKS_CSV, index=False)


def load_custom_sources() -> dict[str, pd.DataFrame]:
    """Auto-discover ADP sources: one more feed per CSV in reference/custom_sources/.

    No code to write, no API to match. Drop a CSV with `player` and `adp`
    columns (`position` and `team` recommended -- they're what makes name
    matching reliable) and it becomes source adp_<filename>, blended in
    alongside FFC/MFL/ESPN exactly like a fourth feed. Tag = filename minus
    extension, so friends_mock.csv becomes adp_friends_mock.

    Unlike the API-fetched sources, there's no sample-size signal on a
    hand-typed list, so these never go through apply_sample_floor -- see
    main.collect().
    """
    sources: dict[str, pd.DataFrame] = {}
    if not CUSTOM_SOURCES.exists():
        return sources

    for path in sorted(CUSTOM_SOURCES.glob("*.csv")):
        tag = path.stem
        raw = pd.read_csv(path)
        cols = {c.strip().lower(): c for c in raw.columns}
        missing = {"player", "adp"} - cols.keys()
        if missing:
            raise ValueError(
                f"{path.name}: custom source needs at least 'player' and 'adp' columns "
                f"(recommend 'position' and 'team' too), missing {sorted(missing)}."
            )

        adp_col = f"adp_{tag}"
        out = pd.DataFrame({
            "name": raw[cols["player"]],
            "position": raw[cols["position"]].astype(str).str.upper().str.strip() if "position" in cols else "",
            "team": raw[cols["team"]] if "team" in cols else pd.NA,
            adp_col: pd.to_numeric(raw[cols["adp"]], errors="coerce"),
        })
        out = out.dropna(subset=[adp_col])
        if out.empty:
            raise ValueError(f"{path.name}: no rows with a valid numeric 'adp' value.")

        sources[tag] = out.reset_index(drop=True)

    return sources
