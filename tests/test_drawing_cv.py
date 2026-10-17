import cv2 as cv
import numpy as np

from drawing_pipeline.cv_regions import analyse_view, overlay
from drawing_pipeline.reference import VIEWS, label_image, regions_for

VIEW = "base"


def inside(zone, side):
    """A point deep inside one sector of the view, crop px."""
    index = next(i for i, r in enumerate(regions_for(VIEW), 1) if r.zone == zone and r.image_side == side)
    region = (label_image(VIEW) == index).astype(np.uint8)
    y, x = np.unravel_index(np.argmax(cv.distanceTransform(region, cv.DIST_L2, 3)), region.shape)
    return int(x), int(y)


def blank():
    return np.zeros(VIEWS[VIEW].shape, np.uint8)


def test_closed_loop_filled_and_counted_in_sector():
    mask = blank()
    cv.circle(mask, inside("pzpl", "left"), 10, 1, 2)
    found = analyse_view(mask, VIEW)
    loops = [f for f in found if f.region.kind == "closed outline"]
    assert len(loops) == 1
    loop = loops[0]
    assert loop.region.id == "base.cv1" and loop.region.bridged_px == 0
    assert loop.mask.sum() > mask.sum()          # interior counted, not just ink
    assert loop.region.sectors[0].zone == "pzpl" and loop.region.sectors[0].image_side == "left"
    x0, y0 = VIEWS[VIEW].origin
    ys, xs = np.nonzero(loop.mask)
    assert loop.region.box_ref == [xs.min() + x0, ys.min() + y0, xs.max() + x0, ys.max() + y0]


def test_gappy_loop_bridged():
    mask = blank()
    cv.ellipse(mask, (300, 200), (40, 40), 0, 20, 360, 1, 2)   # about 14 px gap
    found = analyse_view(mask, VIEW)
    assert [f.region.kind for f in found] == ["bridged outline"]
    assert found[0].region.bridged_px > 0 and found[0].bridge.any()


def test_open_stroke_not_filled():
    mask = blank()
    cv.line(mask, (100, 100), (200, 140), 1, 2)
    found = analyse_view(mask, VIEW)
    assert [f.region.kind for f in found] == ["open stroke"]
    assert found[0].region.px == np.count_nonzero(mask)


def test_shading_counts_ink_only():
    mask = blank()
    for y in range(150, 250, 4):
        cv.line(mask, (250, y), (350, y + 10), 1, 1)
    found = analyse_view(mask, VIEW)
    shading = [f for f in found if f.region.kind == "shading"]
    assert shading and all(not (f.mask & ~mask.astype(bool)).any() for f in shading)


def test_overlay_shape():
    mask = blank()
    cv.circle(mask, (300, 200), 30, 1, 2)
    cleaned = np.full((*mask.shape, 3), 255, np.uint8)
    assert overlay(cleaned, analyse_view(mask, VIEW)).shape == cleaned.shape
