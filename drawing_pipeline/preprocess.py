"""Align a scan to the reference, subtract the template and extract the ink mask.

Ported from scripts/extract_handwriting.py with behaviour unchanged, plus an
optional hysteresis threshold for faint pencil that breaks into dashes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import cv2 as cv
import numpy as np

from .reference import GRAY_REFERENCE, ROOT, SECTOR_MAP, VIEWS

PARAMETERS = {
    "chroma_floor": 3.0, "chroma_local_peak_fraction": 0.3,
    "neutral_threshold": 20.0, "neutral_threshold_near_reference_edge": 75.0,
    "registration_tolerance_px": 3, "minimum_component_pixels": 3,
    "acquisition_footer_bounds_xywh": [80, 1685, 450, 50],
    "hysteresis_weak_score": 0.5,  # weak pixels join the mask only when 8-connected to a score > 1 seed
}


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv.imwrite(str(path), image):
        raise OSError(f"Could not write {path}")


def load_manifest(path: Path) -> dict[str, Path]:
    """Preprocess batch manifest -> case id -> absolute drawing path."""
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {case: path.parent / entry["drawing"] for case, entry in data.get("cases", data).items()}


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
    for name, view in VIEWS.items():
        x, y, vw, vh = view.bounds
        selected = used & (dst[:, 0] >= x) & (dst[:, 0] < x + vw) & (dst[:, 1] >= y) & (dst[:, 1] < y + vh)
        local[name] = {"inliers": int(selected.sum()), "median_px": float(np.median(residual[selected])) if selected.any() else None}
    metadata = {"method": "ORB + RANSAC", "matches": len(matches), "inliers": int(used.sum()),
                "median_px": float(np.median(residual[used])), "p95_px": float(np.percentile(residual[used], 95)),
                "spread_fraction_xy": spread.tolist(), "panels": local,
                "original_to_reference": page_transform.tolist(), "reference_to_original": np.linalg.inv(page_transform).tolist()}
    return cv.warpPerspective(image, page_transform, (w, h), borderValue=(255, 255, 255)), metadata


def ink_mask(score: np.ndarray, hysteresis: bool = True) -> np.ndarray:
    """Threshold the ink score and drop specks, scanner borders and the footer. uint8 0/255."""
    candidate = (score > 1).astype(np.uint8)
    if hysteresis:
        weak = (score > PARAMETERS["hysteresis_weak_score"]).astype(np.uint8)
        count, labels = cv.connectedComponents(weak, connectivity=8)
        seeded = np.zeros(count, bool)
        seeded[np.unique(labels[candidate > 0])] = True
        seeded[0] = False
        candidate = seeded[labels].astype(np.uint8)
    count, labels, stats, _ = cv.connectedComponentsWithStats(candidate)
    keep = stats[:, cv.CC_STAT_AREA] >= PARAMETERS["minimum_component_pixels"]
    keep[0] = False
    # A long, thin scanner border is not handwriting. Keep removed pixels as uncertain.
    # Hysteresis joins border dashes and the scan shadow into a band wider than 5 px,
    # so with it any tall component lying wholly in an edge strip counts as border.
    edge = score.shape[1] * .96
    for i in range(1, count):
        x, y, width, height, area = stats[i]
        in_strip = x + width <= 25 or x > edge
        if height > 80 and (x < 25 or x > edge) and (width <= 5 or (hysteresis and in_strip)):
            keep[i] = False
    mask = keep[labels].astype(np.uint8) * 255
    # The added printed Rakathon identifier is absent from the anatomical reference.
    x, y, width, height = PARAMETERS["acquisition_footer_bounds_xywh"]
    mask[y:y + height, x:x + width] = 0
    return mask


def isolate(image, color_reference, gray_reference, hysteresis: bool = True) -> dict[str, np.ndarray]:
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
    mask = ink_mask(score, hysteresis)
    uncertain = (((score > .65) | ((dark > PARAMETERS["neutral_threshold"]) & near_edge)) & (mask == 0)).astype(np.uint8) * 255
    cleaned = color_reference.copy()
    cleaned[mask > 0] = 0
    return {"mask": mask, "uncertain": uncertain, "cleaned": cleaned}


def _source_name(path: Path) -> str:
    path = path.resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def prepare(drawing: Path, out: Path, hysteresis: bool = True) -> dict:
    """Align and clean one drawing; write images and metadata.json to out/preprocess/."""
    drawing, folder = Path(drawing), Path(out) / "preprocess"
    folder.mkdir(parents=True, exist_ok=True)
    image = cv.imread(str(drawing))
    if image is None:
        raise FileNotFoundError(drawing)
    reference = cv.imread(str(SECTOR_MAP))
    gray_reference = cv.imread(str(GRAY_REFERENCE), 0)
    metadata = {"source": _source_name(drawing), "source_sha256": digest(drawing),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "reference_sha256": digest(SECTOR_MAP), "parameters": PARAMETERS, "hysteresis": hysteresis,
                "coordinate_frame": "reference pixels; top-left origin; x right; y down"}
    try:
        aligned, alignment = align(image, gray_reference)
    except ValueError as error:
        metadata["failure"] = str(error)
        (folder / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        raise
    products = isolate(aligned, reference, gray_reference, hysteresis)
    write_image(folder / "aligned.png", aligned)
    for name in ("cleaned", "mask", "uncertain"):
        write_image(folder / f"{name}.png", products[name])
    for name, view in VIEWS.items():
        x, y, width, height = view.bounds
        extent = np.s_[y:y + height, x:x + width]
        for filename, pixels in {"original": aligned, "cleaned": products["cleaned"], "mask": products["mask"]}.items():
            write_image(folder / "views" / name / f"{filename}.png", pixels[extent])
    metadata.update({"alignment": alignment, "ink_pixels": int(np.count_nonzero(products["mask"])),
                     "views": {name: {"bounds_xywh": list(view.bounds)} for name, view in VIEWS.items()}})
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def load_view(out: Path, view: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(original BGR, cleaned BGR, mask bool) crops written by prepare."""
    folder = Path(out) / "preprocess" / "views" / view
    images = []
    for name, flag in (("original", cv.IMREAD_COLOR), ("cleaned", cv.IMREAD_COLOR), ("mask", cv.IMREAD_GRAYSCALE)):
        image = cv.imread(str(folder / f"{name}.png"), flag)
        if image is None:
            raise FileNotFoundError(folder / f"{name}.png")
        images.append(image)
    return images[0], images[1], images[2] > 0
