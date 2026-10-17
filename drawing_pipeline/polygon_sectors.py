"""Sector source (b): the merged Gemini polygon counted on the sector label image."""

from __future__ import annotations

from .geometry import raster, ref_to_crop
from .models import BUBBLE_KINDS, THRESHOLDS, Mark, SectorShare, Signal, signal
from .reference import VIEWS, sector_shares


def _key(sector) -> tuple[str, str, str]:
    return sector.zone, sector.level, sector.image_side


def polygon_sectors(mark: Mark) -> tuple[list[SectorShare], list[Signal]]:
    if not mark.polygon_ref:
        return [], []
    mask = raster(VIEWS[mark.view].shape, ref_to_crop(mark.polygon_ref, mark.view), mark.closed)
    shares = [SectorShare(**share) for share in sector_shares(mask, mark.view)]
    if mark.kind not in BUBBLE_KINDS:
        return shares, []
    named = {_key(s) for s in mark.sectors_named}
    touched = {_key(s) for s in shares}
    extra = [" ".join(key) for key in dict.fromkeys(_key(s) for s in mark.sectors_named) if key not in touched]
    # Threshold on the share of the whole polygon, not of its in-sector part: bubbles often run past the gland.
    area = int(mask.sum())
    missing = [f"{' '.join(_key(s))} ({s.px / area:.0%} of the polygon)" for s in shares
               if _key(s) not in named and s.px / area >= THRESHOLDS["named_vs_polygon_share"]]
    if not extra and not missing:
        return shares, []
    reason = "; ".join(part for part in (
        extra and "named but not under the polygon: " + ", ".join(extra),
        missing and "under the polygon but not named: " + ", ".join(missing)) if part)
    return shares, [signal("named_vs_polygon", [f"{mark.id}.sectors_named", f"{mark.id}.sectors_polygon"], reason)]


def apply(marks: list[Mark]) -> list[Signal]:
    signals = []
    for mark in marks:
        mark.sectors_polygon, found = polygon_sectors(mark)
        signals += found
    return signals
