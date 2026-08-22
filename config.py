"""Central configuration. Change SEASON here each year and nowhere else."""
from pathlib import Path

SEASON = 2026
TEAMS = 12
SCORING = "ppr"          # ffc path segment: standard | ppr | half-ppr | 2qb | dynasty
IS_PPR = 1               # mfl flag
ESPN_LEAGUE_DEFAULT = 3  # 3 = ESPN's default PPR league; 1 = standard

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
REFERENCE = ROOT / "reference"
CUSTOM_SOURCES = REFERENCE / "custom_sources"  # drop a CSV here to add your own ADP source
OUTPUT = ROOT / "output"
SESSION = ROOT / "draft"
for _d in (CACHE, REFERENCE, CUSTOM_SOURCES, OUTPUT, SESSION):
    _d.mkdir(exist_ok=True)


def master_csv_path() -> Path:
    return OUTPUT / f"adp_master_{SEASON}_{SCORING}_{TEAMS}tm.csv"

USER_AGENT = "adp-master/1.0 (personal fantasy football tool)"

# --- inclusion thresholds -------------------------------------------------
MIN_SOURCES = 2        # player must appear in at least this many feeds
MIN_DRAFT_PCT = 5.0    # and be drafted in at least this % of drafts, per source
TOP_N_FLAG = 5         # top/bottom N offences to flag

# --- primary source -------------------------------------------------------
# Name a source tag here and that feed becomes the sole author of adp_master.
# Not "weighted more" -- the only one: a player it does not list gets no price
# and does not reach the board, rather than being quietly backfilled with a
# blend of the other feeds.
#
# That is the right call for a feed which has already done the aggregating --
# an export whose AVG column averages Sleeper/ESPN/Yahoo/Underdog/CBS/FFPC and
# an expert consensus. Median-ing that against three single-pool feeds throws
# away the aggregation it already did, and double counts the pools it already
# contains. It also covers the full player universe including kickers and team
# defenses, which is what makes "nowhere else" viable with no gaps to fill.
#
# The other feeds stay loaded as context, not as prices: they populate
# adp_spread and carry FFC's per-player stdev for the survival model.
#
# Tag = slugified custom-source filename. Set to None for a median-of-all blend.
PRIMARY_SOURCE = "ppr_overall_7d_08222026"

# --- live draft tracker -----------------------------------------------------
MY_DRAFT_SLOT = 1      # your 1-indexed slot in the snake order -- set this before draft day

ROSTER_SLOTS = {       # 12-team PPR starting lineup + bench; edit per league
    "QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1, "BN": 6,
}

# Within-position adp_rank gap that starts a new tier. Rank, not raw pick
# number, for the same scale-safety reason aggregate.py uses rank for ordering.
TIER_GAP_RANK = {"QB": 4, "RB": 3, "WR": 3, "TE": 4, "K": 6, "DST": 6}

RUN_WINDOW = 6         # positional-run detector: look at the last N picks league-wide
RUN_THRESHOLD = 3      # ...and flag a position if it's >= this many of them

# O-line context for RB/QB rows (gold/red badge in the tracker). Hand-classified,
# same reasoning as offense.csv/byeweeks.csv -- no free O-line ranking API exists.
OLINE_TOP5 = {"DEN", "PHI", "TB", "BUF", "CHI"}
OLINE_BOTTOM = {"CLE", "TEN", "HOU", "WSH", "ARI", "JAX"}

# --- mock draft (auto-fill other teams' picks) -----------------------------
MOCK_POOL_SIZE = 5     # CPU picks draw from the top N available players by adp_rank
MOCK_DECAY = 0.55      # geometric weight decay across that pool -- top player likeliest, not guaranteed

# --- value_delta insights ---------------------------------------------------
VALUE_FALL_THRESHOLD = 5    # picks past adp_rank before it counts as a real value signal, not noise
ACT_NOW_SURVIVAL = 0.3      # falling + survival_prob below this -> urgent, likely gone by your next pick
SAFE_VALUE_SURVIVAL = 0.5   # falling + survival_prob above this -> value, but safe to wait on
FALLERS_SHOWN = 8           # rows in the "Biggest Fallers" leaderboard

# --- crosswalk ------------------------------------------------------------
PLAYERIDS_URL = (
    "https://raw.githubusercontent.com/dynastyprocess/data/master/"
    "files/db_playerids.csv"
)

# --- team code normalisation ---------------------------------------------
# Every feed spells a few of these differently. Canonical = the 32 values on
# the right-hand side; anything not listed passes through unchanged.
TEAM_ALIASES = {
    "JAC": "JAX", "JAG": "JAX",
    "WAS": "WSH", "WFT": "WSH",
    "LA": "LAR", "STL": "LAR", "SL": "LAR",
    "OAK": "LV", "LVR": "LV",
    "SD": "LAC", "SDG": "LAC",
    "ARZ": "ARI", "BLT": "BAL", "HST": "HOU", "CLV": "CLE",
    "GNB": "GB", "KAN": "KC", "NWE": "NE", "NOR": "NO",
    "SFO": "SF", "TAM": "TB", "NOS": "NO",
    "GBP": "GB", "KCC": "KC", "NEP": "NE", "TBB": "TB",
}

NFL_TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WSH",
]


def norm_team(code) -> str:
    if code is None:
        return "FA"
    code = str(code).strip().upper()
    return TEAM_ALIASES.get(code, code)
