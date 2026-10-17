"""Versioned central interpretation rules; no drawing thresholds are consulted."""
from pathlib import Path

RULES_VERSION = "rules-1"
SECTOR_SHARE_MIN = 0.15
SIDE_AGREE = 3.0
SIDE_CONFLICT = -3.0
LEVEL_AGREE = 1.0
LEVEL_MISSING = -1.0
LOCATION_AGREE = 1.0
LOCATION_CONFLICT = -1.0
SIZE_RANK_BONUS = 0.5
EXTRA_STANDALONE_PENALTY = -1.0
HIGH_MARGIN = 3.0
MEDIUM_MARGIN = 1.0
SIZE_TOLERANCE_MM = 2.0
DEFAULT_CROSSWALK = Path(__file__).resolve().parents[1] / "Other/redcap/sector_crosswalk.csv"
ZONE_TABLE = {
    "pza": ("pz", "anterior"), "pzpl": ("pz", "posterior"),
    "pzpm": ("pz", "posterior"), "tza": ("tz", "anterior"),
    "tzp": ("tz", "posterior"), "cz": ("cz", "posterior"),
    "as": ("as", "anterior"), "sv": ("sv", None),
}
SEVERE_SIGNALS = frozenset({"sources_disagree", "named_vs_polygon", "group_check_failed"})
