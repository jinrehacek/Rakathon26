#!/usr/bin/env python3
"""Derive the 12 coronal and sagittal level regions from the printed reference.

Coronal: base, mid and apex bands split by the two printed dashed lines, times
image left and right of the symmetry axis. Sagittal: the same three levels split
by the two slanted dashed lines, times anterior and posterior of the long dashed
line. The organ outline comes from the coloured zones of the sector map.

Writes longitudinal_regions.json and longitudinal_regions_preview.png. Run once;
the output is checked in. Regions are for Gemini and code only, not the doctor UI.
"""

import hashlib
import json
from pathlib import Path

import cv2 as cv
import numpy as np

HERE = Path(__file__).resolve().parent
MAP = HERE / "pirads_v2.1_sector_map.png"
JSON_OUT = HERE / "longitudinal_regions.json"
PREVIEW_OUT = HERE / "longitudinal_regions_preview.png"

CORONAL_BOUNDS = (0, 140, 650, 950)
SAGITTAL_BOUNDS = (70, 890, 650, 820)
CORONAL_AXIS_X = 327
# Approximate dashed-line endpoints read off a 50 px grid, in crop pixels.
# Only used to select dash pixels; the line itself is fitted.
SAGITTAL_LINES = {
    "anterior_posterior": [(325, 185), (160, 670)],
    "base_mid": [(115, 297), (430, 402)],
    "mid_apex": [(80, 475), (365, 570)],
}


def organ_mask(image, bounds, convex=False):
    """Coloured zone pixels, closed, hole-filled, minus thin urethra tails.

    The coronal gland is two lobes split by the white urethra, so it takes the
    convex hull of both lobes. The sagittal gland is concave at the top, so it
    keeps the outline.
    """
    x, y, w, h = bounds
    hsv = cv.cvtColor(image[y:y + h, x:x + w], cv.COLOR_BGR2HSV)
    colour = (hsv[:, :, 1] > 25).astype(np.uint8)
    colour = cv.morphologyEx(colour, cv.MORPH_CLOSE, cv.getStructuringElement(cv.MORPH_ELLIPSE, (15, 15)))
    # Opening removes the urethra stripe that runs out of the gland; the gland stays.
    colour = cv.morphologyEx(colour, cv.MORPH_OPEN, cv.getStructuringElement(cv.MORPH_ELLIPSE, (41, 41)))
    count, labels, stats, _ = cv.connectedComponentsWithStats(colour)
    areas = stats[1:, cv.CC_STAT_AREA]
    organ = np.isin(labels, 1 + np.nonzero(areas > .2 * areas.max())[0]).astype(np.uint8)
    contours, _ = cv.findContours(organ, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_NONE)
    if convex:
        contours = [cv.convexHull(np.concatenate(contours))]
    filled = np.zeros_like(organ)
    cv.drawContours(filled, contours, -1, 1, cv.FILLED)
    return filled.astype(bool)


def coronal_cuts(image, bounds):
    """Rows of the two horizontal dashed lines, in crop pixels."""
    x, y, w, h = bounds
    gray = cv.cvtColor(image[y:y + h, x:x + w], cv.COLOR_BGR2GRAY)
    dark_per_row = ((gray > 70) & (gray < 135)).sum(axis=1)
    rows = np.argsort(dark_per_row)[::-1]
    picked = []
    for row in rows:
        if all(abs(row - p) > 20 for p in picked):
            picked.append(int(row))
        if len(picked) == 2:
            break
    return sorted(picked)


def fit_sagittal_lines(image, bounds):
    x, y, w, h = bounds
    hsv = cv.cvtColor(image[y:y + h, x:x + w], cv.COLOR_BGR2HSV)
    gray = cv.cvtColor(image[y:y + h, x:x + w], cv.COLOR_BGR2GRAY)
    dash = (gray > 70) & (gray < 135) & (hsv[:, :, 1] < 25)
    ys, xs = np.nonzero(dash)
    points = np.c_[xs, ys].astype(np.float32)
    lines = {}
    for name, (a, b) in SAGITTAL_LINES.items():
        a, b = np.float32(a), np.float32(b)
        direction = (b - a) / np.linalg.norm(b - a)
        normal = np.float32([-direction[1], direction[0]])
        along = (points - a) @ direction
        selected = points[(np.abs((points - a) @ normal) < 10) & (along > -20) & (along < np.linalg.norm(b - a) + 20)]
        vx, vy, cx, cy = cv.fitLine(selected, cv.DIST_HUBER, 0, .01, .01).ravel()
        lines[name] = {"point": [float(cx), float(cy)], "direction": [float(vx), float(vy)], "dash_pixels": int(len(selected))}
    return lines


def side_of(line, shape):
    """Signed distance of every crop pixel from a fitted line."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    (cx, cy), (vx, vy) = line["point"], line["direction"]
    return (xx - cx) * vy - (yy - cy) * vx


def polygon(mask, offset):
    contours, _ = cv.findContours(mask.astype(np.uint8), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    contour = max(contours, key=cv.contourArea)
    contour = cv.approxPolyDP(contour, 1.0, True)
    return (contour[:, 0] + offset).astype(int).tolist()


def main():
    image = cv.imread(str(MAP))
    regions = []

    x, y, w, h = CORONAL_BOUNDS
    organ = organ_mask(image, CORONAL_BOUNDS, convex=True)
    upper, lower = coronal_cuts(image, CORONAL_BOUNDS)
    rows = np.arange(h)[:, None]
    cols = np.arange(w)[None, :]
    bands = {"base": rows < upper, "mid": (rows >= upper) & (rows < lower), "apex": rows >= lower}
    sides = {"left": cols < CORONAL_AXIS_X, "right": cols >= CORONAL_AXIS_X}
    for level, band in bands.items():
        for side, half in sides.items():
            regions.append({"key": f"coronal_{level}_{side}", "view": "coronal", "zone": "prostate", "level": level,
                            "image_side": side, "reference_coordinates_px": polygon(organ & band & half, [x, y])})
    coronal = {"dashed_line_rows_ref": [upper + y, lower + y], "axis_x_ref": CORONAL_AXIS_X + x}

    x, y, w, h = SAGITTAL_BOUNDS
    organ = organ_mask(image, SAGITTAL_BOUNDS)
    lines = fit_sagittal_lines(image, SAGITTAL_BOUNDS)
    # Sign conventions checked on the preview: base is above base_mid, apex below mid_apex,
    # anterior (towards the printed AFS, viewer-left) is left of the long line.
    above_base_mid = side_of(lines["base_mid"], (h, w))
    above_mid_apex = side_of(lines["mid_apex"], (h, w))
    left_of_ap = side_of(lines["anterior_posterior"], (h, w))
    base_sign = np.sign(above_base_mid[0, w // 2])
    apex_sign = -np.sign(above_mid_apex[0, w // 2])
    anterior_sign = np.sign(left_of_ap[h // 2, 0])
    bands = {"base": np.sign(above_base_mid) == base_sign,
             "mid": (np.sign(above_base_mid) != base_sign) & (np.sign(above_mid_apex) != apex_sign),
             "apex": np.sign(above_mid_apex) == apex_sign}
    halves = {"anterior": np.sign(left_of_ap) == anterior_sign, "posterior": np.sign(left_of_ap) != anterior_sign}
    for level, band in bands.items():
        for zone, half in halves.items():
            regions.append({"key": f"sagittal_{level}_{zone}", "view": "sagittal", "zone": zone, "level": level,
                            "image_side": "none", "reference_coordinates_px": polygon(organ & band & half, [x, y])})
    sagittal = {"lines_ref": {name: {"point": [line["point"][0] + x, line["point"][1] + y], "direction": line["direction"],
                                     "dash_pixels": line["dash_pixels"]} for name, line in lines.items()}}

    JSON_OUT.write_text(json.dumps({
        "source": {"path": MAP.name, "sha256": hashlib.sha256(MAP.read_bytes()).hexdigest(),
                   "script": Path(__file__).name},
        "coordinates": "reference pixels; origin top-left; x right; y down",
        "use": "Gemini map and code only. Not shown in the doctor UI. No REDCap codes.",
        "coronal": coronal, "sagittal": sagittal, "regions": regions}, indent=1) + "\n")

    preview = image.copy()
    colours = {"base": (0, 140, 255), "mid": (0, 170, 0), "apex": (200, 0, 160)}
    for region in regions:
        points = np.array(region["reference_coordinates_px"], np.int32)
        tint = preview.copy()
        cv.fillPoly(tint, [points], colours[region["level"]])
        alpha = .35 if region["image_side"] == "left" or region["zone"] == "anterior" else .2
        preview = cv.addWeighted(tint, alpha, preview, 1 - alpha, 0)
        cv.polylines(preview, [points], True, (0, 0, 0), 2)
        cx, cy = points.mean(axis=0).astype(int)
        label = f"{region['level']} {region['image_side'] if region['view'] == 'coronal' else region['zone']}"
        cv.putText(preview, label, (cx - 40, cy), cv.FONT_HERSHEY_SIMPLEX, .55, (0, 0, 0), 2, cv.LINE_AA)
    cv.imwrite(str(PREVIEW_OUT), preview[100:1737, 0:760])
    print(f"{len(regions)} regions; coronal cuts at {coronal['dashed_line_rows_ref']}")


if __name__ == "__main__":
    main()
