"""Reference template data: views, symmetry axes, sector maps and REDCap lookup.

Everything is in reference pixels of the 1342 x 1737 template that every scan
is aligned to. Origin top-left, x right, y down.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import cv2 as cv
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / "Other/reference"
SECTOR_MAP = REFERENCE_DIR / "pirads_v2.1_sector_map.png"
GRAY_REFERENCE = REFERENCE_DIR / "pirads_v2.1_grayscale.png"
SECTORS_JSON = REFERENCE_DIR / "sectors.json"
LONGITUDINAL_JSON = REFERENCE_DIR / "longitudinal_regions.json"
CROSSWALK = ROOT / "Other/redcap/sector_crosswalk.csv"
WIDTH, HEIGHT = 1342, 1737


@dataclass(frozen=True)
class View:
    name: str
    bounds: tuple[int, int, int, int]  # x, y, width, height in reference px
    view_type: str                     # STRUCTURE.md: cross-sectional, longitudinal, schematic
    level: str
    axis_x: int | None                 # symmetry axis in reference px; None for sagittal
    axial_block: bool                  # SV, base, mid and apex share one lettered orientation

    @property
    def origin(self) -> tuple[int, int]:
        return self.bounds[0], self.bounds[1]

    @property
    def shape(self) -> tuple[int, int]:
        return self.bounds[3], self.bounds[2]


# Crop bounds come from the ink-extraction probes. Axes were set once by hand:
# axial and SV from the midpoints of mirrored ctsit sector pairs, coronal from the
# midpoints of the two printed dashed lines. They are constants, never detected per sheet.
VIEWS: dict[str, View] = {view.name: view for view in (
    View("coronal", (0, 140, 650, 950), "longitudinal", "unspecified", 327, False),
    View("sagittal", (70, 890, 650, 820), "longitudinal", "unspecified", None, False),
    View("seminal_vesicles", (770, 140, 570, 240), "cross-sectional", "seminal vesicles", 1054, True),
    View("base", (750, 330, 590, 460), "cross-sectional", "base", 1061, True),
    View("mid", (740, 770, 590, 470), "cross-sectional", "mid", 1059, True),
    View("apex", (800, 1200, 510, 380), "cross-sectional", "apex", 1059, True),
    View("urethra", (980, 1560, 170, 170), "schematic", "apex to base", 1061, False),
)}
AXIAL_BLOCK = tuple(name for name, view in VIEWS.items() if view.axial_block)

# Printed zone labels (what Gemini reads on the map) to the crosswalk zone codes.
PRINTED_ZONES = {"AFS": "as", "PZa": "pza", "PZpl": "pzpl", "PZpm": "pzpm", "TZa": "tza", "TZp": "tzp",
                 "CZ": "cz", "SV": "sv", "urethra": "urethra"}
# Longitudinal pseudo-zones: the whole gland in coronal, front/back in sagittal.
LONGITUDINAL_ZONES = ("prostate", "anterior", "posterior")
ZONES = tuple(PRINTED_ZONES.values()) + LONGITUDINAL_ZONES


def normalize_zone(zone: str) -> str:
    """Accept printed labels (PZpl) or codes (pzpl); return the code."""
    if zone in PRINTED_ZONES:
        return PRINTED_ZONES[zone]
    code = zone.strip().lower()
    if code == "afs":
        return "as"
    if code not in ZONES:
        raise ValueError(f"Unknown zone {zone!r}")
    return code


@dataclass(frozen=True)
class Region:
    """One sector polygon on the reference, in one view."""
    key: str                      # "ctsit_<n>" or a longitudinal key such as "coronal_base_left"
    view: str
    zone: str
    level: str                    # base, mid, apex, seminal vesicles or urethra
    image_side: str               # left, right, midline (urethra) or none (sagittal)
    polygon: np.ndarray           # (n, 2) int32, reference px
    ctsit_key: int | None = None


def _view_for_ctsit(level: str, zone: str) -> str:
    if zone == "urethra":
        return "urethra"
    if zone == "sv":
        return "seminal_vesicles"
    return level


@cache
def crosswalk_rows() -> tuple[dict, ...]:
    return tuple(csv.DictReader(CROSSWALK.open(encoding="utf-8")))


@cache
def regions() -> tuple[Region, ...]:
    rows = {int(row["ctsit_key"]): row for row in crosswalk_rows()}
    found = []
    for sector in json.loads(SECTORS_JSON.read_text())["sectors"]:
        row = rows[sector["key"]]
        zone = row["zone"]
        level = "urethra" if zone == "urethra" else ("seminal vesicles" if zone == "sv" else row["level"])
        view = VIEWS[_view_for_ctsit(row["level"], zone)]
        polygon = np.round(np.array(sector["reference_coordinates_px"])).astype(np.int32)
        if zone == "urethra":
            side = "midline"
        else:
            # Side from geometry against the view's axis; the crosswalk must agree.
            side = "left" if polygon[:, 0].mean() < view.axis_x else "right"
            if side != row["drawn_on_viewer"]:
                raise ValueError(f"ctsit {sector['key']}: centroid side {side} disagrees with crosswalk")
        found.append(Region(f"ctsit_{sector['key']}", view.name, zone, level, side, polygon, sector["key"]))
    for region in json.loads(LONGITUDINAL_JSON.read_text())["regions"]:
        found.append(Region(region["key"], region["view"], region["zone"], region["level"], region["image_side"],
                            np.array(region["reference_coordinates_px"], np.int32)))
    return tuple(found)


def regions_for(view: str) -> tuple[Region, ...]:
    return tuple(region for region in regions() if region.view == view)


@cache
def label_image(view: str) -> np.ndarray:
    """Crop-sized int16 map: 0 = no sector, i + 1 = regions_for(view)[i]."""
    v = VIEWS[view]
    labels = np.zeros(v.shape, np.int16)
    for index, region in enumerate(regions_for(view), 1):
        cv.fillPoly(labels, [region.polygon - np.array(v.origin)], index)
    labels.setflags(write=False)
    return labels


def sector_shares(mask: np.ndarray, view: str) -> list[dict]:
    """Pixels of a crop-sized boolean mask per sector of the view.

    Share is the fraction of the mask's in-sector pixels, so shares sum to 1
    when any pixel lands in a sector. Both the Gemini polygon (source b) and the
    CV fill (source c) go through this one function so they stay comparable.
    Returns dicts with zone, level, image_side, px, share; largest first.
    """
    labels = label_image(view)
    if mask.shape != labels.shape:
        raise ValueError(f"Mask shape {mask.shape} does not match view {view} {labels.shape}")
    counts = np.bincount(labels[mask.astype(bool)].ravel(), minlength=len(regions_for(view)) + 1)
    inside = int(counts[1:].sum())
    shares = []
    for index, region in enumerate(regions_for(view), 1):
        if counts[index]:
            shares.append({"zone": region.zone, "level": region.level, "image_side": region.image_side,
                           "px": int(counts[index]), "share": round(float(counts[index] / inside), 4)})
    return sorted(shares, key=lambda s: -s["px"])


def redcap_code(zone: str, level: str, patient_side: str | None) -> str | None:
    """REDCap sur_prostate_regions code from zone + level + patient side.

    Never derived from the template's drawn_on_viewer column. Urethra has one
    code with no side. Longitudinal pseudo-zones and unknown sides have none.
    """
    zone = normalize_zone(zone)
    if zone == "urethra":
        return "urethra"
    if zone in LONGITUDINAL_ZONES or patient_side not in ("left", "right"):
        return None
    lookup_level = "base" if zone == "sv" else level
    for row in crosswalk_rows():
        if row["zone"] == zone and row["level"] == lookup_level and row["patient_side"] == patient_side:
            return row["redcap_code"]
    return None


def coordinate_convention(view: str) -> dict:
    """STRUCTURE.md Diagram view coordinate convention: origin on the symmetry axis."""
    v = VIEWS[view]
    if v.axis_x is None:
        return {"origin": "crop top-left", "x": "towards anterior is not fixed; see sagittal regions",
                "y": "down", "units": "reference px", "crop_origin_ref": list(v.origin),
                "note": "Sagittal has no left/right. Anterior and posterior come from the sagittal regions."}
    return {"origin": "symmetry axis", "axis_x_ref": v.axis_x, "x": "viewer right", "y": "down",
            "units": "reference px"}
