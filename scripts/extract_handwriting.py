#!/usr/bin/env python3
"""Local OpenCV handwriting candidates. No OCR, lesion inference or outline filling."""

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2 as cv
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "Other/reference"
VIEWS = {
    "base": (750, 330, 590, 460),
    "mid": (740, 770, 590, 470),
    "apex": (800, 1200, 510, 380),
    "coronal": (0, 140, 650, 950),
    "sagittal": (70, 890, 650, 820),
    "seminal_vesicles": (770, 140, 570, 240),
    "urethra": (980, 1560, 170, 170),
}
PARAMETERS = {
    "chroma_floor": 3.0, "chroma_local_peak_fraction": 0.3,
    "neutral_threshold": 20.0, "neutral_threshold_near_reference_edge": 75.0,
    "registration_tolerance_px": 3, "minimum_component_pixels": 3,
    "acquisition_footer_bounds_xywh": [80, 1685, 450, 50],
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_image(path, image):
    if not cv.imwrite(str(path), image):
        raise OSError(f"Could not write {path}")


def align(image, gray_reference):
    h, w = gray_reference.shape
    scale = w / image.shape[1]
    small = cv.resize(image, (w, round(image.shape[0] * scale)))
    detector = cv.ORB_create(nfeatures=10000, fastThreshold=8)
    kr, dr = detector.detectAndCompute(gray_reference, None)
    ks, ds = detector.detectAndCompute(cv.cvtColor(small, cv.COLOR_BGR2GRAY), None)
    if dr is None or ds is None:
        raise ValueError("Alignment failed: no descriptors")
    pairs = cv.BFMatcher(cv.NORM_HAMMING).knnMatch(ds, dr, k=2)
    matches = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < .72 * pair[1].distance]
    if len(matches) < 30:
        raise ValueError("Alignment failed: fewer than 30 candidate matches")
    src = np.float32([ks[m.queryIdx].pt for m in matches])
    dst = np.float32([kr[m.trainIdx].pt for m in matches])
    cv.setRNGSeed(20261016)
    transform, inliers = cv.findHomography(src, dst, cv.RANSAC, 3)
    if transform is None:
        raise ValueError("Alignment failed: no homography")
    used = inliers.ravel().astype(bool)
    residual = np.linalg.norm(cv.perspectiveTransform(src[:, None], transform)[:, 0] - dst, axis=1)
    spread = np.ptp(dst[used], axis=0) / [w, h]
    page_transform = transform @ np.diag([scale, scale, 1.])
    corners = cv.perspectiveTransform(np.float32([[[0, 0]], [[w, 0]], [[w, small.shape[0]]], [[0, small.shape[0]]]]), transform)
    upright = corners[1, 0, 0] > corners[0, 0, 0] and corners[3, 0, 1] > corners[0, 0, 1]
    if (used.sum() < 50 or used.mean() < .25 or np.any(spread < [.6, .65])
            or np.percentile(residual[used], 95) > 4 or not upright
            or not cv.isContourConvex(corners) or cv.contourArea(corners, oriented=True) <= 0):
        raise ValueError("Alignment failed: insufficient spread, residual error or implausible transform")
    local = {}
    for name, (x, y, vw, vh) in VIEWS.items():
        selected = used & (dst[:, 0] >= x) & (dst[:, 0] < x + vw) & (dst[:, 1] >= y) & (dst[:, 1] < y + vh)
        local[name] = {"inliers": int(selected.sum()), "median_px": float(np.median(residual[selected])) if selected.any() else None}
    metadata = {"method": "ORB + RANSAC", "matches": len(matches), "inliers": int(used.sum()),
                "median_px": float(np.median(residual[used])), "p95_px": float(np.percentile(residual[used], 95)),
                "spread_fraction_xy": spread.tolist(), "panels": local,
                "original_to_reference": page_transform.tolist(), "reference_to_original": np.linalg.inv(page_transform).tolist()}
    return cv.warpPerspective(image, page_transform, (w, h), borderValue=(255, 255, 255)), metadata


def isolate(image, color_reference, gray_reference):
    gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY).astype(np.float32)
    ref = gray_reference.astype(np.float32)
    lab = cv.cvtColor(image, cv.COLOR_BGR2LAB).astype(np.float32)
    median = cv.medianBlur(lab.astype(np.uint8), 31).astype(np.float32)
    # Paper tint tends toward neutral at darker printed pixels.
    baseline = (median[:, :, 1:] - 128) * np.minimum(1., lab[:, :, 0] / np.maximum(median[:, :, 0], 1))[:, :, None]
    chroma = np.linalg.norm(lab[:, :, 1:] - 128 - baseline, axis=2)
    # This max filter sets a threshold; it never expands the output mask.
    peak = cv.dilate(chroma, np.ones((15, 15), np.uint8))
    color_threshold = np.maximum(PARAMETERS["chroma_floor"], peak * PARAMETERS["chroma_local_peak_fraction"])

    # Estimate each printed shade from unmarked pixels of the same reference colour.
    # Whole-page medians preserve broad pencil shading instead of treating it as paper.
    ref_bg_color = cv.medianBlur(color_reference, 31)
    ref_bg = cv.cvtColor(ref_bg_color, cv.COLOR_BGR2GRAY).astype(np.float32)
    quantized = ref_bg_color.astype(np.int32) // 32
    classes = quantized[:, :, 0] * 64 + quantized[:, :, 1] * 8 + quantized[:, :, 2]
    background = np.empty_like(gray)
    for key in np.unique(classes):
        region = classes == key
        safe = region & (chroma < 3) & (np.abs(ref - ref_bg) < 3)
        background[region] = np.median(gray[safe]) if safe.sum() > 50 else np.median(gray[region])
    expected = background * np.clip(ref / np.maximum(ref_bg, 1), 0, 1) ** 1.6
    # Correct small exposure variation using pixels compatible with the background.
    delta = gray - expected
    compatible = ((np.abs(delta) < 20) & (chroma < 3)).astype(np.float32)
    offset = cv.GaussianBlur(delta * compatible, (0, 0), 25) / np.maximum(cv.GaussianBlur(compatible, (0, 0), 25), .01)
    expected = np.clip(expected + offset, 0, 255)
    tolerant = cv.erode(expected, np.ones((7, 7), np.uint8))
    dark = np.maximum(0, tolerant - gray)
    reference_edges = (cv.morphologyEx(ref, cv.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 8).astype(np.uint8)
    near_edge = cv.dilate(reference_edges, np.ones((9, 9), np.uint8)).astype(bool)
    neutral_threshold = np.where(near_edge, PARAMETERS["neutral_threshold_near_reference_edge"], PARAMETERS["neutral_threshold"])
    score = np.maximum(chroma / color_threshold, dark / neutral_threshold)
    candidate = (score > 1).astype(np.uint8)
    count, labels, stats, _ = cv.connectedComponentsWithStats(candidate)
    keep = stats[:, cv.CC_STAT_AREA] >= PARAMETERS["minimum_component_pixels"]
    keep[0] = False
    # A long, thin scanner border is not handwriting. Keep removed pixels as uncertain.
    for i in range(1, count):
        x, y, width, height, area = stats[i]
        if width <= 5 and height > 80 and (x < 25 or x > image.shape[1] * .96):
            keep[i] = False
    mask = keep[labels].astype(np.uint8) * 255
    # The added printed Rakathon identifier is absent from the anatomical reference.
    x, y, width, height = PARAMETERS["acquisition_footer_bounds_xywh"]
    mask[y:y + height, x:x + width] = 0
    uncertain = (((score > .65) | ((dark > PARAMETERS["neutral_threshold"]) & near_edge)) & (mask == 0)).astype(np.uint8) * 255
    black = np.zeros((*mask.shape, 4), np.uint8)
    black[:, :, 3] = mask
    original_color = np.dstack([image, mask])
    modified = color_reference.copy()
    modified[mask > 0] = 0
    return {"mask": mask, "uncertain": uncertain, "black": black, "color_ink": original_color,
            "modified": modified, "expected": np.uint8(expected),
            "difference": np.uint8(np.clip(dark * 4, 0, 255)),
            "chroma": np.uint8(np.clip(chroma * 10, 0, 255))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scans", nargs="+", type=int, default=[1, 3, 7, 13, 14, 17, 27, 33])
    parser.add_argument("--output", type=Path, default=ROOT / "Other/output/handwriting")
    args = parser.parse_args()
    ignored = ROOT / "Other/output"
    if not args.output.resolve().is_relative_to(ignored.resolve()):
        parser.error("Use an output directory under the git-ignored Other/output folder")
    cv.setNumThreads(2)
    reference = cv.imread(str(REFERENCE / "pirads_v2.1_sector_map.png"))
    gray_reference = cv.imread(str(REFERENCE / "pirads_v2.1_grayscale.png"), 0)
    if reference is None or gray_reference is None:
        parser.error("Run reference preparation first")
    args.output.mkdir(parents=True, exist_ok=True)
    for number in args.scans:
        start = time.perf_counter()
        source = ROOT / f"Other/data/schema/Schema_{number:04}.jpg"
        image = cv.imread(str(source))
        if image is None:
            raise FileNotFoundError(source)
        out = args.output / f"scan_{number:04}"
        out.mkdir(exist_ok=True)
        metadata = {"source": str(source.relative_to(ROOT)), "source_sha256": digest(source),
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "software_sha256": digest(Path(__file__)), "opencv": cv.__version__, "numpy": np.__version__,
                    "reference_sha256": digest(REFERENCE / "pirads_v2.1_sector_map.png"), "parameters": PARAMETERS,
                    "coordinate_frame": "reference pixels; top-left origin; x right; y down", "review_status": "needs review"}
        try:
            aligned, registration = align(image, gray_reference)
        except ValueError as error:
            metadata["failure"] = str(error)
            (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
            print(f"scan {number}: {error}")
            continue
        products = isolate(aligned, reference, gray_reference)
        write_image(out / "aligned.png", aligned)
        for name, product in products.items():
            write_image(out / f"{name}.png", product)
        views = {}
        for name, (x, y, width, height) in VIEWS.items():
            crop = out / name
            crop.mkdir(exist_ok=True)
            extent = np.s_[y:y + height, x:x + width]
            for filename, pixels in {"original": aligned, "modified": products["modified"], "mask": products["mask"]}.items():
                write_image(crop / f"{filename}.png", pixels[extent])
            local_to_page = np.array([[1., 0., x], [0., 1., y], [0., 0., 1.]])
            edge = products["mask"][extent]
            views[name] = {"bounds_xywh": [x, y, edge.shape[1], edge.shape[0]],
                           "crop_to_original": (np.array(registration["reference_to_original"]) @ local_to_page).tolist(),
                           "candidate_reaches_crop_edge": bool(np.any(edge[:2]) or np.any(edge[-2:]) or np.any(edge[:, :2]) or np.any(edge[:, -2:]))}
        metadata.update({"alignment": registration, "views": views, "candidate_pixels": int(np.count_nonzero(products["mask"])),
                         "seconds": round(time.perf_counter() - start, 2),
                         "issues": ["Candidate mask requires visual review; black ink coincident with printed lines can be inseparable.",
                                    "Broad pencil shading can be incomplete, especially around printed labels and boundaries.",
                                    "Narrow peripheral scanner-border components and the printed Rakathon footer are excluded; suppressed residuals remain uncertain.",
                                    "Weak strokes, scanner noise and reference remnants can remain in the uncertainty mask.",
                                    "Crop edge contacts require checking the full page before later reading."]})
        assert digest(source) == metadata["source_sha256"]
        (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"scan {number}: {metadata['candidate_pixels']} candidate pixels, {metadata['seconds']}s, alignment median {registration['median_px']:.2f}px")


if __name__ == "__main__":
    main()
