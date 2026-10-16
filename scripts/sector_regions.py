#!/usr/bin/env python3
"""Calculated sector contacts from the CV ink mask. Code only: no model, no report, no patient side."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import cv2 as cv
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SECTORS = ROOT / "Other/reference/sectors.json"
CROSSWALK = ROOT / "Other/redcap/sector_crosswalk.csv"
AXIAL = ("base", "mid", "apex")
PARAMETERS = {
    # Loose stroke ends closer than each gap are joined, smallest gap first.
    "grow_radii_px": [0, 3, 6, 10],  # a loop first enclosed at radius r had gaps up to about 2r px
    "gap_marker_px": 2.5,                # interior boundary farther than this from ink is drawn as a bridged gap
    "minimum_hole_px": 80,          # H: smaller enclosed holes are letters or specks
    "small_contact_px": 30,         # S: contacts below this become questions, not deletions
    "stroke_reach_px": 8,           # ink this close to an interior counts as that region's outline
    "annotation_inside_fraction": .15,  # regions with less of their area inside the organ are notes or letters
    "open_stroke_minimum_px": 30,   # smaller unenclosed ink inside the organ is listed as specks
    "shading_minimum_px": 1500, "shading_minimum_thickness_px": 8, "shading_close_radius_px": 6,
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def disk(radius):
    return cv.getStructuringElement(cv.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def enclosed(foreground):
    """Background pixels that cannot reach the crop border."""
    background = (foreground == 0).astype(np.uint8)
    count, labels = cv.connectedComponents(background, connectivity=4)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    return background.astype(bool) & ~np.isin(labels, border)


def load_sectors(bounds):
    x, y, w, h = bounds
    rows = {int(r["ctsit_key"]): r for r in csv.DictReader(CROSSWALK.open())}
    sectors = {}
    for sector in json.loads(SECTORS.read_text())["sectors"]:
        polygon = np.round(np.array(sector["reference_coordinates_px"])).astype(np.int32)
        full = cv.contourArea(polygon.reshape(-1, 1, 2).astype(np.float32))
        local = np.zeros((h, w), np.uint8)
        cv.fillPoly(local, [polygon - [x, y]], 1)
        if local.any():
            row = rows[sector["key"]]
            sectors[sector["key"]] = {"mask": local.astype(bool), "area_px": float(full), "redcap_code": row["redcap_code"],
                                      "zone": row["zone"], "level": row["level"], "image_side": row["drawn_on_viewer"]}
    return sectors


def contacts(extent, interior, sectors):
    found = []
    for key, s in sectors.items():
        px = int(np.count_nonzero(extent & s["mask"]))
        if not px:
            continue
        inside = int(np.count_nonzero(interior & s["mask"])) if interior is not None else 0
        found.append({"ctsit_key": key, "zone": s["zone"], "level": s["level"], "image_side": s["image_side"],
                      "redcap_if_standard_orientation": s["redcap_code"], "px": px, "interior_px": inside,
                      "sector_fraction": round(px / max(s["area_px"], 1), 3),
                      "contact": "interior" if inside >= PARAMETERS["small_contact_px"] else "edge",
                      "small": px < PARAMETERS["small_contact_px"]})
    return sorted(found, key=lambda c: -c["px"])


def analyse(mask, sectors):
    ink = mask > 0
    union = np.zeros_like(ink)
    for s in sectors.values():
        union |= s["mask"]
    organ = cv.morphologyEx(union.astype(np.uint8), cv.MORPH_CLOSE, disk(4)).astype(bool)
    organ |= enclosed(organ.astype(np.uint8))
    away_from_ink = cv.distanceTransform((~ink).astype(np.uint8), cv.DIST_L2, 3) > PARAMETERS["gap_marker_px"]
    regions, claimed, used_ink = [], np.zeros_like(ink), np.zeros_like(ink)
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
            extent = interior | outline
            edge = interior & ~cv.erode(interior.astype(np.uint8), disk(1)).astype(bool)
            gap = edge & away_from_ink if radius else np.zeros_like(ink)
            claimed |= interior
            used_ink |= outline
            regions.append({"kind": "bridged_outline" if gap.any() else "closed_outline", "grow_radius_px": radius,
                            "gap_boundary_px": int(np.count_nonzero(gap)),
                            "inside_organ_fraction": round(float(np.count_nonzero(interior & organ) / area), 2),
                            "interior_px": area, "_interior": interior, "_extent": extent, "_bridge": gap})
    # Dense ink with no loop, such as pencil shading.
    r = PARAMETERS["shading_close_radius_px"]
    blob = cv.morphologyEx((ink & ~used_ink).astype(np.uint8), cv.MORPH_CLOSE, disk(r))
    count, labels, stats, _ = cv.connectedComponentsWithStats(blob, connectivity=8)
    for i in range(1, count):
        part = labels == i
        if stats[i, cv.CC_STAT_AREA] < PARAMETERS["shading_minimum_px"]:
            continue
        thickness = cv.distanceTransform(part.astype(np.uint8), cv.DIST_L2, 3).max()
        if thickness < PARAMETERS["shading_minimum_thickness_px"]:
            continue
        used_ink |= part & ink
        regions.append({"kind": "shading", "grow_radius_px": r, "gap_boundary_px": 0,
                        "inside_organ_fraction": round(float(np.count_nonzero(part & organ) / part.sum()), 2),
                        "interior_px": int(part.sum()), "_interior": part, "_extent": part, "_bridge": np.zeros_like(part)})
    for n, region in enumerate(regions, 1):
        region["id"] = f"R{n}"
        region["annotation_outside_organ"] = region["inside_organ_fraction"] < PARAMETERS["annotation_inside_fraction"]
        ys, xs = np.nonzero(region["_extent"])
        region["box_xyxy"] = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        region["unassigned_px"] = int(np.count_nonzero(region["_extent"] & organ & ~union))
        region["sectors"] = [] if region["annotation_outside_organ"] else contacts(region["_extent"], region["_interior"], sectors)
        region["questions"] = questions(region)
    # Ink that belongs to no region.
    count, labels, stats, _ = cv.connectedComponentsWithStats((ink & ~used_ink).astype(np.uint8), connectivity=8)
    strokes, specks, annotations = [], 0, 0
    for i in range(1, count):
        part = labels == i
        if np.count_nonzero(part & organ) < .5 * part.sum():
            annotations += 1
        elif stats[i, cv.CC_STAT_AREA] < PARAMETERS["open_stroke_minimum_px"]:
            specks += 1
        else:
            x, y, w, h, area = stats[i]
            strokes.append({"id": f"S{len(strokes) + 1}", "px": int(area), "box_xyxy": [int(x), int(y), int(x + w), int(y + h)],
                            "sectors_crossed": contacts(part, None, sectors), "_extent": part})
    return regions, strokes, {"specks_inside_organ": specks, "components_outside_organ": annotations}, organ


def questions(region):
    asked = []
    if region["kind"] == "bridged_outline":
        asked.append(f"Loop closes only across gaps of up to about {2 * region['grow_radius_px']} px (red). Is it one closed outline?")
    if region["kind"] == "shading":
        asked.append("Dense ink with no loop. Is this a shaded area, text or noise?")
    small = [c["redcap_if_standard_orientation"] for c in region["sectors"] if c["small"]]
    if small:
        asked.append("Small contact with " + ", ".join(small) + ". Include?")
    if region["unassigned_px"] > PARAMETERS["small_contact_px"]:
        asked.append(f"{region['unassigned_px']} px fall between sector polygons.")
    return asked


def overlay(modified, regions, strokes):
    base = cv.addWeighted(modified, .55, np.full_like(modified, 255), .45, 0)
    base[np.all(modified == 0, axis=2)] = 0
    colours = [(230, 120, 0), (0, 160, 0), (200, 0, 200), (0, 140, 255), (160, 90, 0), (0, 0, 200), (120, 0, 120), (0, 120, 120)]
    out = base.copy()
    for n, region in enumerate(regions):
        colour = (150, 150, 150) if region["annotation_outside_organ"] else colours[n % len(colours)]
        tint = out.copy()
        tint[region["_interior"]] = colour
        out = cv.addWeighted(tint, .45, out, .55, 0)
    for region in regions:
        if region["kind"] == "bridged_outline":
            out[cv.dilate(region["_bridge"].astype(np.uint8), disk(1)).astype(bool)] = (0, 0, 255)
    for stroke in strokes:
        out[stroke["_extent"]] = (0, 165, 255)
    for region in regions:
        x0, y0, x1, y1 = region["box_xyxy"]
        label = region["id"]
        cv.putText(out, label, (x0, max(14, y0 - 3)), cv.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 3, cv.LINE_AA)
        cv.putText(out, label, (x0, max(14, y0 - 3)), cv.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1, cv.LINE_AA)
    for stroke in strokes:
        x0, y0 = stroke["box_xyxy"][:2]
        cv.putText(out, stroke["id"], (x0, max(14, y0 - 3)), cv.FONT_HERSHEY_SIMPLEX, .45, (0, 110, 200), 1, cv.LINE_AA)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=ROOT / "Other/output/handwriting")
    parser.add_argument("--output", type=Path, default=ROOT / "Other/output/sectors")
    parser.add_argument("--views", nargs="+", default=list(AXIAL))
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to((ROOT / "Other/output").resolve()):
        parser.error("Use an output directory under the git-ignored Other/output folder")
    for scan in sorted(args.input_root.glob("scan_*")):
        metadata = json.loads((scan / "metadata.json").read_text())
        if "failure" in metadata:
            print(f"{scan.name}: skipped, alignment failed")
            continue
        for view in args.views:
            bounds = metadata["views"][view]["bounds_xywh"]
            mask = cv.imread(str(scan / view / "mask.png"), 0)
            regions, strokes, counts, _ = analyse(mask, load_sectors(bounds))
            out = args.output / scan.name / view
            out.mkdir(parents=True, exist_ok=True)
            cv.imwrite(str(out / "overlay.png"), overlay(cv.imread(str(scan / view / "modified.png")), regions, strokes))
            result = {"scan": scan.name, "view": view, "basis": "calculated", "review_status": "needs review",
                      "coordinate_frame": "crop pixels; add bounds_xywh[0:2] for reference pixels",
                      "bounds_xywh": bounds, "mask_sha256": digest(scan / view / "mask.png"),
                      "software_sha256": digest(__file__), "parameters": PARAMETERS,
                      "side_assumption": "image_side and redcap_if_standard_orientation assume axial viewer-left = patient right; the report decides side",
                      "regions": [{k: v for k, v in r.items() if not k.startswith("_")} for r in regions],
                      "open_strokes": [{k: v for k, v in s.items() if not k.startswith("_")} for s in strokes], **counts}
            (out / "regions.json").write_text(json.dumps(result, indent=2) + "\n")
        print(f"{scan.name}: done")


if __name__ == "__main__":
    main()
