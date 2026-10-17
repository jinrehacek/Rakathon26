"""Coordinate conversion and rasterisation shared by every stage."""

from __future__ import annotations

import cv2 as cv
import numpy as np

from .reference import VIEWS

# Open strokes and marks without a polygon are rasterised this thick, so that
# IoU between runs and pairing with CV work on something with area.
STROKE_PX = 6


def normalized_to_crop(points, view: str) -> np.ndarray:
    """Gemini [x, y] in 0..1000 of the whole crop -> crop px (float)."""
    h, w = VIEWS[view].shape
    return np.asarray(points, np.float64).reshape(-1, 2) * [w / 1000, h / 1000]


def normalized_box_to_crop(box_2d, view: str) -> np.ndarray:
    """Gemini box_2d [ymin, xmin, ymax, xmax] in 0..1000 -> [x0, y0, x1, y1] crop px."""
    h, w = VIEWS[view].shape
    y0, x0, y1, x1 = box_2d
    return np.array([x0 * w / 1000, y0 * h / 1000, x1 * w / 1000, y1 * h / 1000])


def crop_to_ref(points, view: str) -> np.ndarray:
    return np.asarray(points, np.float64).reshape(-1, 2) + VIEWS[view].origin


def ref_to_crop(points, view: str) -> np.ndarray:
    return np.asarray(points, np.float64).reshape(-1, 2) - VIEWS[view].origin


def raster(shape, polygon=None, closed=True, box=None, stroke_px=STROKE_PX) -> np.ndarray:
    """Boolean mask of a mark in one pixel frame.

    Closed polygon: filled. Open polyline: stroke of stroke_px. No polygon: the box
    filled. Coordinates must already be in the mask's frame.
    """
    mask = np.zeros(shape, np.uint8)
    if polygon is not None and len(polygon) >= 2:
        points = np.round(np.asarray(polygon)).astype(np.int32).reshape(-1, 1, 2)
        if closed and len(polygon) >= 3:
            cv.fillPoly(mask, [points], 1)
            cv.polylines(mask, [points], True, 1, 1)
        else:
            cv.polylines(mask, [points], False, 1, stroke_px)
    elif box is not None:
        x0, y0, x1, y1 = np.round(box).astype(int)
        cv.rectangle(mask, (x0, y0), (x1, y1), 1, cv.FILLED)
    return mask.astype(bool)


def grow(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask.astype(bool)
    kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (2 * px + 1, 2 * px + 1))
    return cv.dilate(mask.astype(np.uint8), kernel).astype(bool)


def iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.count_nonzero(a | b)
    return np.count_nonzero(a & b) / union if union else 0.0


def centre(mask: np.ndarray) -> tuple[float, float] | None:
    ys, xs = np.nonzero(mask)
    return (float(xs.mean()), float(ys.mean())) if len(xs) else None
