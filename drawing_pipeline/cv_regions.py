"""CV regions from the ink mask of one view: sector source (c).

Ported from scripts/sector_regions.py and generalised to every view. Code only:
no model, no report, no mark kinds, no patient side.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2 as cv
import numpy as np

from .models import THRESHOLDS, CVRegion, SectorShare
from .reference import VIEWS, sector_shares

PARAMETERS = {
    # Loose stroke ends closer than each gap are joined, smallest gap first.
    "grow_radii_px": [0, 3, 6, THRESHOLDS["gap_close_px"]],
    "gap_marker_px": 2.5,           # interior boundary farther than this from ink is drawn as a bridged gap
    "minimum_hole_px": 80,          # smaller enclosed holes are letters or specks
    "stroke_reach_px": 8,           # ink this close to an interior counts as that region's outline
    "open_stroke_minimum_px": 30,   # smaller leftover ink is a speck, not a stroke
    "shading_minimum_px": 1500, "shading_minimum_thickness_px": 8, "shading_close_radius_px": 6,
}


@dataclass
class CVFound:
    region: CVRegion
    mask: np.ndarray                 # crop-sized bool: interior + outline for loops, ink for strokes and shading
    bridge: np.ndarray | None = None  # bridged gap pixels, for the overlay


def disk(radius: int) -> np.ndarray:
    return cv.getStructuringElement(cv.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def enclosed(foreground: np.ndarray) -> np.ndarray:
    """Background pixels that cannot reach the crop border."""
    background = (foreground == 0).astype(np.uint8)
    count, labels = cv.connectedComponents(background, connectivity=4)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    return background.astype(bool) & ~np.isin(labels, border)


def _found(view: str, kind: str, mask: np.ndarray, bridge: np.ndarray | None = None) -> CVFound:
    ys, xs = np.nonzero(mask)
    x0, y0 = VIEWS[view].origin
    region = CVRegion(id="", view=view, kind=kind, px=int(mask.sum()),
                      box_ref=[int(xs.min()) + x0, int(ys.min()) + y0, int(xs.max()) + x0, int(ys.max()) + y0],
                      bridged_px=int(bridge.sum()) if bridge is not None else 0,
                      sectors=[SectorShare(**share) for share in sector_shares(mask, view)])
    return CVFound(region, mask, bridge)


def analyse_view(mask: np.ndarray, view: str) -> list[CVFound]:
    """Loops (closed or bridged), shading and open strokes in one view's ink mask."""
    ink = mask.astype(bool)
    away_from_ink = cv.distanceTransform((~ink).astype(np.uint8), cv.DIST_L2, 3) > PARAMETERS["gap_marker_px"]
    found, claimed, used_ink = [], np.zeros_like(ink), np.zeros_like(ink)
    for radius in PARAMETERS["grow_radii_px"]:
        # Growing the ink by r closes gaps up to about 2r; shrinking the hole back by r restores the interior.
        grown = ink if radius == 0 else cv.dilate(ink.astype(np.uint8), disk(radius)).astype(bool)
        count, labels, stats, _ = cv.connectedComponentsWithStats(grown.astype(np.uint8), connectivity=8)
        for i in range(1, count):
            x, y, w, h, _ = stats[i]
            box = np.s_[max(0, y - 1):y + h + 1, max(0, x - 1):x + w + 1]
            hole = np.zeros_like(ink)
            hole[box] = enclosed((labels[box] == i).astype(np.uint8))
            if not hole.any():
                continue
            interior = (cv.dilate(hole.astype(np.uint8), disk(radius)).astype(bool) if radius else hole) & ~ink
            area = int(np.count_nonzero(interior))
            if area < PARAMETERS["minimum_hole_px"] or np.count_nonzero(interior & claimed) > .5 * area:
                continue
            outline = ink & cv.dilate(interior.astype(np.uint8), disk(PARAMETERS["stroke_reach_px"] + radius)).astype(bool)
            edge = interior & ~cv.erode(interior.astype(np.uint8), disk(1)).astype(bool)
            gap = edge & away_from_ink if radius else np.zeros_like(ink)
            claimed |= interior
            used_ink |= outline
            found.append(_found(view, "bridged outline" if gap.any() else "closed outline", interior | outline, gap))
    # Dense ink with no loop, such as pencil shading. Only its ink is counted, never the closed blob.
    r = PARAMETERS["shading_close_radius_px"]
    blob = cv.morphologyEx((ink & ~used_ink).astype(np.uint8), cv.MORPH_CLOSE, disk(r))
    count, labels, stats, _ = cv.connectedComponentsWithStats(blob, connectivity=8)
    for i in range(1, count):
        if stats[i, cv.CC_STAT_AREA] < PARAMETERS["shading_minimum_px"]:
            continue
        part = labels == i
        if cv.distanceTransform(part.astype(np.uint8), cv.DIST_L2, 3).max() < PARAMETERS["shading_minimum_thickness_px"]:
            continue
        if (part & ink & ~used_ink).any():
            found.append(_found(view, "shading", part & ink & ~used_ink))
            used_ink |= part & ink
    # Ink that belongs to no loop or shading.
    count, labels, stats, _ = cv.connectedComponentsWithStats((ink & ~used_ink).astype(np.uint8), connectivity=8)
    for i in range(1, count):
        if stats[i, cv.CC_STAT_AREA] >= PARAMETERS["open_stroke_minimum_px"]:
            found.append(_found(view, "open stroke", labels == i))
    for n, item in enumerate(found, 1):
        item.region.id = f"{view}.cv{n}"
    return found


def overlay(cleaned: np.ndarray, found: list[CVFound]) -> np.ndarray:
    """Cleaned crop with loop and shading fills tinted, bridges red, strokes orange and IDs drawn."""
    base = cv.addWeighted(cleaned, .55, np.full_like(cleaned, 255), .45, 0)
    base[np.all(cleaned == 0, axis=2)] = 0
    colours = [(230, 120, 0), (0, 160, 0), (200, 0, 200), (0, 140, 255), (160, 90, 0), (0, 0, 200), (120, 0, 120), (0, 120, 120)]
    out = base.copy()
    for n, item in enumerate(f for f in found if f.region.kind != "open stroke"):
        tint = out.copy()
        tint[item.mask] = colours[n % len(colours)]
        out = cv.addWeighted(tint, .45, out, .55, 0)
    for item in found:
        if item.region.kind == "open stroke":
            out[item.mask] = (0, 165, 255)
        elif item.bridge is not None and item.bridge.any():
            out[cv.dilate(item.bridge.astype(np.uint8), disk(1)).astype(bool)] = (0, 0, 255)
    x0, y0 = VIEWS[found[0].region.view].origin if found else (0, 0)
    for item in found:
        label = item.region.id.split(".")[-1]
        at = (item.region.box_ref[0] - x0, max(14, item.region.box_ref[1] - y0 - 3))
        cv.putText(out, label, at, cv.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 3, cv.LINE_AA)
        cv.putText(out, label, at, cv.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1, cv.LINE_AA)
    return out
