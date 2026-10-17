#!/usr/bin/env python3
"""Map ctsit PI-RADS polygons onto the project's clean reference image."""

import hashlib
import json
import re
from pathlib import Path

import cv2
import numpy as np


HERE = Path(__file__).resolve().parent
SOURCE_IMAGE = HERE / "pirads_v2.1.png"
SOURCE_MAP = HERE / "pirads_v2.1.html"
REFERENCE = HERE / "pirads_v2.1_sector_map.png"
GRAY_OUT = HERE / "pirads_v2.1_grayscale.png"
OVERLAY_OUT = HERE / "pirads_v2.1_sectors_numbered.png"
JSON_OUT = HERE / "sectors.json"
REVISION = "0bf201d6cb95c7eaedb5449b36e4fa1d9cd9907f"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_sectors():
    html = SOURCE_MAP.read_text(encoding="utf-8")
    sectors = []
    for tag in re.findall(r"<area\b[^>]*>", html, flags=re.IGNORECASE):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', tag))
        if "data-key" not in attrs:
            continue
        raw = [int(value) for value in attrs["coords"].split(",")]
        sectors.append({
            "key": int(attrs["data-key"]),
            "name": attrs.get("title", ""),
            "source_coordinates_px": [raw[i:i + 2] for i in range(0, len(raw), 2)],
        })
    if [s["key"] for s in sectors] != list(range(1, 42)):
        raise ValueError("Expected source polygon keys 1 through 41")
    return sectors


def main():
    source = cv2.imread(str(SOURCE_IMAGE), cv2.IMREAD_GRAYSCALE)
    reference_color = cv2.imread(str(REFERENCE), cv2.IMREAD_COLOR)
    if source is None or reference_color is None:
        raise FileNotFoundError("Could not read the source or existing reference image")
    target = cv2.cvtColor(reference_color, cv2.COLOR_BGR2GRAY)

    sift = cv2.SIFT_create(nfeatures=12000, contrastThreshold=0.01, edgeThreshold=12)
    source_kp, source_desc = sift.detectAndCompute(source, None)
    target_kp, target_desc = sift.detectAndCompute(target, None)
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(source_desc, target_desc, k=2)
    matches = [a for a, b in pairs if a.distance < 0.72 * b.distance]
    source_points = np.float32([source_kp[m.queryIdx].pt for m in matches])
    target_points = np.float32([target_kp[m.trainIdx].pt for m in matches])

    cv2.setRNGSeed(20261016)
    transform, inlier_mask = cv2.findHomography(
        source_points, target_points, cv2.RANSAC, 4.0, maxIters=10000, confidence=0.999
    )
    if transform is None:
        raise RuntimeError("OpenCV could not estimate the reference mapping")
    inliers = inlier_mask.ravel().astype(bool)
    projected = cv2.perspectiveTransform(source_points.reshape(-1, 1, 2), transform)[:, 0]
    errors = np.linalg.norm(projected - target_points, axis=1)[inliers]

    sectors = read_sectors()
    overlay = reference_color.copy()
    for sector in sectors:
        original = np.float32(sector["source_coordinates_px"]).reshape(-1, 1, 2)
        mapped = cv2.perspectiveTransform(original, transform)[:, 0]
        sector["reference_coordinates_px"] = np.round(mapped, 3).tolist()
        contour = np.round(mapped).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(overlay, [contour], True, (0, 45, 255), 2, cv2.LINE_AA)
        moments = cv2.moments(contour)
        center = (int(moments["m10"] / moments["m00"]), int(moments["m01"] / moments["m00"]))
        label = str(sector["key"])
        size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
        origin = (center[0] - size[0] // 2, center[1] + size[1] // 2)
        cv2.putText(overlay, label, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(overlay, label, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    cv2.imwrite(str(GRAY_OUT), target)
    cv2.imwrite(str(OVERLAY_OUT), overlay)
    payload = {
        "upstream": {
            "repository": "https://github.com/ctsit/imagemap",
            "revision": REVISION,
            "map_html": {
                "url": f"https://github.com/ctsit/imagemap/blob/{REVISION}/maps/pirads_v2.1.html",
                "sha256": sha256(SOURCE_MAP),
            },
            "image": {
                "url": f"https://github.com/ctsit/imagemap/blob/{REVISION}/img/pirads_v2.1.png",
                "sha256": sha256(SOURCE_IMAGE),
            },
            "license_file": {
                "path": "LICENSE.imagemap",
                "url": f"https://github.com/ctsit/imagemap/blob/{REVISION}/LICENSE",
                "sha256": sha256(HERE / "LICENSE.imagemap"),
            },
            "module_license": "Apache-2.0",
            "artwork_terms": "Unverified; the repository license does not establish separate artwork rights.",
        },
        "target_reference": {
            "path": REFERENCE.name,
            "sha256": sha256(REFERENCE),
            "width": int(reference_color.shape[1]),
            "height": int(reference_color.shape[0]),
            "coordinates": "pixel x,y; origin top-left; x right; y down",
        },
        "source_coordinate_frame": {
            "path": SOURCE_IMAGE.name,
            "width": int(source.shape[1]),
            "height": int(source.shape[0]),
            "coordinates": "pixel x,y; origin top-left; x right; y down",
        },
        "mapping": {
            "method": "SIFT matches, 0.72 Lowe ratio, OpenCV homography with RANSAC",
            "homography_source_to_reference": transform.tolist(),
            "ransac_threshold_px": 4.0,
            "good_matches": len(matches),
            "inliers": int(inliers.sum()),
            "inlier_ratio": float(inliers.mean()),
            "inlier_reprojection_error_px": {
                "median": float(np.median(errors)),
                "p90": float(np.percentile(errors, 90)),
                "max": float(errors.max()),
            },
        },
        "redcap_code_mapping": "Unverified and not included; source keys are not assumed to be REDCap choice codes.",
        "sectors": sectors,
    }
    JSON_OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {GRAY_OUT.name}, {OVERLAY_OUT.name}, {JSON_OUT.name}")
    print(f"matches={len(matches)} inliers={int(inliers.sum())} median={np.median(errors):.3f}px p90={np.percentile(errors, 90):.3f}px")


if __name__ == "__main__":
    main()
