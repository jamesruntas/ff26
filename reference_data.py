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

import io
import re
from pathlib import Path

import pandas as pd

from config import CUSTOM_SOURCES, NFL_TEAMS, REFERENCE, TOP_N_FLAG, norm_team

OFFENSE_CSV = REFERENCE / "offense.csv"
BYEWEEKS_CSV = REFERENCE / "byeweeks.csv"

# Column names accepted as "the ADP value", in preference order -- exports
# from ranking sites rarely call it literally "adp". FantasyPros-style
# multi-site exports (Sleeper/ESPN/Yahoo/.../Consensus) use "Consensus" for
# the blended column, which is exactly the number we want.
_ADP_COLUMN_CANDIDATES = ["adp", "consensus", "average", "avg"]

# Same idea for the position column: "POS" is at least as common as
# "Position" in these exports, and getting it wrong is expensive -- an empty
# position downgrades every row from a name+position match to a name-only
# one, and routes team defenses away from the team-code path entirely.
_POSITION_COLUMN_CANDIDATES = ["position", "pos"]

# Ranking exports write the position with its positional rank glued on
# ("RB1", "TE15", "K18"), and every source spells team defense differently.
_POSITION_ALIASES = {"DEF": "DST", "D/ST": "DST", "DEFENSE": "DST", "PK": "K"}


def _normalise_position(col: pd.Series) -> pd.Series:
    """'RB1' -> 'RB', 'DEF' -> 'DST'. Trailing digits are a positional rank,
    not part of the position, and stripping them is what lets a FantasyPros
    style export match on name+position at all."""
    out = col.fillna("").astype(str).str.upper().str.strip().str.rstrip("0123456789")
    return out.replace(_POSITION_ALIASES)


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


def _slugify_tag(name: str) -> str:
    """Filename -> safe source tag / column-name suffix. 'Fantasy Football
    ADP' becomes 'fantasy_football_adp' (adp_fantasy_football_adp column)."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "source"


def _parse_custom_source(raw: pd.DataFrame, tag: str, source_label: str) -> pd.DataFrame:
    """Shared validation for both auto-discovered and uploaded custom sources
    -- an upload that would blow up the next `python main.py` run is rejected
    right here, before it's ever saved to disk."""
    cols = {c.strip().lower(): c for c in raw.columns}
    if "player" not in cols:
        raise ValueError(f"{source_label}: needs a 'player' column, got {list(raw.columns)}.")

    pos_source_col = next((cols[c] for c in _POSITION_COLUMN_CANDIDATES if c in cols), None)

    adp_source_col = next((cols[c] for c in _ADP_COLUMN_CANDIDATES if c in cols), None)
    if adp_source_col is None:
        raise ValueError(
            f"{source_label}: needs an ADP-like column -- one of {_ADP_COLUMN_CANDIDATES} "
            f"-- got {list(raw.columns)}."
        )

    adp_col = f"adp_{tag}"
    out = pd.DataFrame({
        "name": raw[cols["player"]],
        "position": _normalise_position(raw[pos_source_col]) if pos_source_col else "",
        "team": raw[cols["team"]] if "team" in cols else pd.NA,
        adp_col: pd.to_numeric(raw[adp_source_col], errors="coerce"),
    })
    out = out.dropna(subset=[adp_col])
    if out.empty:
        raise ValueError(f"{source_label}: no rows with a valid numeric ADP value.")

    return out.reset_index(drop=True)


def load_custom_sources() -> dict[str, pd.DataFrame]:
    """Auto-discover ADP sources: one more feed per CSV in reference/custom_sources/.

    No code to write, no API to match. Drop a CSV with a `player` column and
    an ADP-like column (`adp`, `consensus`, `average`, or `avg` -- whichever
    the export calls it; `position` and `team` recommended, they're what
    makes name matching reliable) and it becomes source adp_<filename>,
    blended in alongside FFC/MFL/ESPN exactly like a fourth feed. Tag =
    slugified filename, so "Fantasy Football ADP.csv" becomes
    adp_fantasy_football_adp.

    Unlike the API-fetched sources, there's no sample-size signal on a
    hand-typed or exported list, so these never go through
    apply_sample_floor -- see main.collect().
    """
    sources: dict[str, pd.DataFrame] = {}
    if not CUSTOM_SOURCES.exists():
        return sources

    tags_seen: dict[str, Path] = {}
    for path in sorted(CUSTOM_SOURCES.glob("*.csv")):
        tag = _slugify_tag(path.stem)
        if tag in tags_seen:
            raise ValueError(
                f"{path.name} and {tags_seen[tag].name} both reduce to source tag "
                f"'{tag}' -- rename one of them so they don't collide."
            )
        tags_seen[tag] = path
        sources[tag] = _parse_custom_source(pd.read_csv(path), tag, path.name)

    return sources


def save_custom_source(filename: str, raw_bytes: bytes) -> tuple[str, int]:
    """Validate and save an uploaded custom-source CSV. Returns (tag, player count).

    Runs the exact same validation load_custom_sources() applies to every
    file already on disk -- raises ValueError (never saves) if the upload
    doesn't parse, instead of writing a file that breaks the next `python
    main.py` run.
    """
    raw = pd.read_csv(io.BytesIO(raw_bytes))
    stem = Path(filename).stem  # Path.stem/.name drop any directory component -- no path traversal
    tag = _slugify_tag(stem)
    parsed = _parse_custom_source(raw, tag, filename)

    safe_stem = re.sub(r"[^A-Za-z0-9 _.-]", "_", stem).strip() or "custom_source"
    (CUSTOM_SOURCES / f"{safe_stem}.csv").write_bytes(raw_bytes)
    return tag, len(parsed)
