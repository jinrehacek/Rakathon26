"""Compare merged Gemini marks with CV regions for one view: pairing, sector agreement, unknown ink.

Runs after both machines finish. Neither saw the other's output.
"""

from __future__ import annotations

import cv2 as cv
import numpy as np

from .cv_regions import CVFound
from .geometry import grow, raster, ref_to_crop
from .models import BUBBLE_KINDS, THRESHOLDS, Basis, Mark, SectorShare, Signal, signal
from .preprocess import PARAMETERS
from .reference import VIEWS, sector_shares

LOOP_KINDS = ("closed outline", "bridged outline")


def mark_raster(mark: Mark) -> np.ndarray | None:
    """The mark in the view's crop frame: polygon filled if closed, stroke if open, else its box."""
    view = VIEWS[mark.view]
    if mark.polygon_ref:
        return raster(view.shape, ref_to_crop(mark.polygon_ref, mark.view), mark.closed)
    if mark.box_ref:
        return raster(view.shape, box=ref_to_crop(np.reshape(mark.box_ref, (2, 2)), mark.view).ravel())
    return None


def _shares(mask: np.ndarray, view: str) -> list[SectorShare]:
    return [SectorShare(**share) for share in sector_shares(mask, view)]


def _key(share) -> tuple[str, str, str]:
    return share.zone, share.level, share.image_side


def compare_view(view: str, marks: list[Mark], found: list[CVFound], ink_mask: np.ndarray) -> tuple[list[Mark], list[Signal]]:
    """Spec Compare steps 1-5 for one view. Returns updated marks plus unknown-ink marks, and the signals.

    Sets CVRegion.paired_with on `found` in place. Review status and explanations are
    left to output.build_output, which applies every signal once.
    """
    marks = [mark.model_copy(deep=True) for mark in marks]
    ink = ink_mask.astype(bool)
    rasters = {mark.id: mark_raster(mark) for mark in marks}
    bubbles = [mark for mark in marks if mark.kind in BUBBLE_KINDS]
    signals = []

    # 1. Pairing: each CV region goes to the bubble holding the largest fraction of its pixels, if >= 50%.
    paired: dict[str, list[CVFound]] = {mark.id: [] for mark in bubbles}
    for item in found:
        item.region.paired_with = None
        px = np.count_nonzero(item.mask)
        best, best_fraction = None, THRESHOLDS["pair_inside_fraction"]
        for mark in bubbles:
            if rasters[mark.id] is None:
                continue
            fraction = np.count_nonzero(item.mask & rasters[mark.id]) / px if px else 0.0
            if fraction >= best_fraction and (best is None or fraction > best_fraction):
                best, best_fraction = mark, fraction
        if best is not None:
            item.region.paired_with = best.id
            paired[best.id].append(item)
    for mark in bubbles:
        mark.cv_regions = [item.region.id for item in paired[mark.id]]
        mark.sectors_cv = (_shares(np.logical_or.reduce([item.mask for item in paired[mark.id]]), view)
                           if paired[mark.id] else [])

    for mark in bubbles:
        loops = [item for item in paired[mark.id] if item.region.kind in LOOP_KINDS]
        if not loops:
            # 3. Single source: no closed or bridged CV loop backs this bubble.
            signals.append(signal("single_source", [mark.id], "no closed or bridged CV region pairs with this bubble"))
            continue
        # 2. Sector agreement: polygon shares (b) against the paired loops' shares (c).
        polygon = {_key(share): share.share for share in mark.sectors_polygon}
        cv_loops = {_key(share): share.share for share in _shares(np.logical_or.reduce([item.mask for item in loops]), view)}
        differ = []
        for key in sorted(set(polygon) | set(cv_loops)):
            b, c = polygon.get(key, 0.0), cv_loops.get(key, 0.0)
            if round(abs(b - c), 4) >= THRESHOLDS["sources_disagree_points"]:
                differ.append(f"{' '.join(key)}: polygon {b:.2f}, CV {c:.2f}")
        if differ:
            ids = [mark.id] + [item.region.id for item in loops]
            signals.append(signal("sources_disagree", ids, "; ".join(differ)))

    # 4. Unknown ink: ink components mostly outside every Gemini mark grown by 10 px.
    covered = np.zeros_like(ink)
    for mask in rasters.values():
        if mask is not None:
            covered |= mask
    covered = grow(covered, THRESHOLDS["unknown_ink_grow_px"])
    x0, y0 = VIEWS[view].origin
    count, labels, stats, _ = cv.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    unknown = []
    for i in range(1, count):
        px = int(stats[i, cv.CC_STAT_AREA])
        if px < max(PARAMETERS["minimum_component_pixels"], THRESHOLDS["unknown_ink_minimum_px"]):
            continue
        part = labels == i
        inside = np.count_nonzero(part & covered) / px
        if inside >= THRESHOLDS["unknown_ink_inside_fraction"]:
            continue
        contours, _ = cv.findContours(part.astype(np.uint8), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        contour = max(contours, key=cv.contourArea).reshape(-1, 2)
        x, y, w, h = stats[i, :4]
        mark = Mark(id=f"{view}.u{len(unknown) + 1}", view=view, kind="unknown ink", runs_found=0, basis=Basis.CALCULATED,
                    polygon_ref=(contour + [x0, y0]).tolist(), closed=True,
                    box_ref=[int(x) + x0, int(y) + y0, int(x + w - 1) + x0, int(y + h - 1) + y0],
                    sectors_cv=_shares(part, view))
        rasters[mark.id] = mark_raster(mark)
        signals.append(signal("unknown_ink", [mark.id], f"{px} ink px, {inside:.0%} inside any Gemini mark"))
        unknown.append(mark)
    marks += unknown

    # 5. Not in ink, and the ink count under every mark with geometry.
    for mark in marks:
        if rasters[mark.id] is None:
            continue
        mark.ink_px_under_polygon = int(np.count_nonzero(ink & rasters[mark.id]))
        if mark.kind in BUBBLE_KINDS and mark.ink_px_under_polygon == 0:
            signals.append(signal("not_in_ink", [mark.id], "no ink-mask pixels under the bubble"))
    return marks, signals
