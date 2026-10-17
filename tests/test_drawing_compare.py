import cv2 as cv
import numpy as np

from drawing_pipeline.compare import compare_view
from drawing_pipeline.cv_regions import analyse_view
from drawing_pipeline.geometry import raster
from drawing_pipeline.models import Mark, SectorShare
from drawing_pipeline.reference import VIEWS, sector_shares

VIEW = "base"
X0, Y0 = VIEWS[VIEW].origin


def circle_polygon(cx, cy, r, n=48):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return [[int(round(cx + r * np.cos(a))) + X0, int(round(cy + r * np.sin(a))) + Y0] for a in t]


def bubble(id, polygon, shares=None, kind="closed outline", closed=True):
    if shares is None:
        crop = np.array(polygon) - [X0, Y0]
        shares = sector_shares(raster(VIEWS[VIEW].shape, crop, closed), VIEW)
    return Mark(id=id, view=VIEW, kind=kind, runs_found=3, polygon_ref=polygon, closed=closed,
                sectors_polygon=[SectorShare(**s) for s in shares])


def ink_circle(cx, cy, r):
    mask = np.zeros(VIEWS[VIEW].shape, np.uint8)
    cv.circle(mask, (cx, cy), r, 1, 2)
    return mask.astype(bool)


def kinds(signals):
    return sorted(s.kind for s in signals)


def test_pairing_and_agreement():
    ink = ink_circle(250, 330, 25)
    found = analyse_view(ink, VIEW)
    marks, signals = compare_view(VIEW, [bubble("base.m1", circle_polygon(250, 330, 27))], found, ink)
    assert signals == []
    assert marks[0].cv_regions == ["base.cv1"] and found[0].region.paired_with == "base.m1"
    assert marks[0].sectors_cv and marks[0].ink_px_under_polygon == ink.sum()


def test_sources_disagree():
    ink = ink_circle(250, 330, 25)
    found = analyse_view(ink, VIEW)
    real = sector_shares(raster(VIEWS[VIEW].shape, np.array(circle_polygon(250, 330, 27)) - [X0, Y0]), VIEW)
    wrong = [{**real[0], "zone": "as"}]       # all area claimed in a sector the CV loop does not touch
    marks, signals = compare_view(VIEW, [bubble("base.m1", circle_polygon(250, 330, 27), wrong)], found, ink)
    assert kinds(signals) == ["sources_disagree"]
    assert "as base left: polygon" in signals[0].reason and signals[0].observations == ["base.m1", "base.cv1"]


def test_share_difference_exactly_at_threshold_signals():
    ink = ink_circle(250, 330, 25)
    found = analyse_view(ink, VIEW)
    cv_shares = found[0].region.sectors
    shifted = [{**s.model_dump(), "share": s.share} for s in cv_shares]
    shifted[0]["share"] = round(shifted[0]["share"] - 0.15, 4)
    marks, signals = compare_view(VIEW, [bubble("base.m1", circle_polygon(250, 330, 27), shifted)], found, ink)
    assert "sources_disagree" in kinds(signals)
    shifted[0]["share"] = round(cv_shares[0].share - 0.149, 4)
    marks, signals = compare_view(VIEW, [bubble("base.m1", circle_polygon(250, 330, 27), shifted)], found, ink)
    assert "sources_disagree" not in kinds(signals)


def test_single_source_for_open_stroke_bubble():
    ink = np.zeros(VIEWS[VIEW].shape, np.uint8)
    cv.line(ink, (100, 100), (200, 140), 1, 2)
    ink = ink.astype(bool)
    found = analyse_view(ink, VIEW)
    arc = bubble("base.m1", [[100 + X0, 100 + Y0], [200 + X0, 140 + Y0]], [], kind="open arc", closed=False)
    marks, signals = compare_view(VIEW, [arc], found, ink)
    assert kinds(signals) == ["single_source"] and signals[0].suggestion == "info only"
    assert marks[0].cv_regions == ["base.cv1"]


def test_not_in_ink_and_unknown_ink():
    ink = ink_circle(450, 100, 20)
    found = analyse_view(ink, VIEW)
    text = Mark(id="base.m2", view=VIEW, kind="text", runs_found=3, box_ref=[X0 + 10, Y0 + 10, X0 + 30, Y0 + 30])
    marks, signals = compare_view(VIEW, [bubble("base.m1", circle_polygon(150, 300, 20)), text], found, ink)
    assert kinds(signals) == ["not_in_ink", "single_source", "unknown_ink"]
    unknown = marks[-1]
    assert unknown.id == "base.u1" and unknown.kind == "unknown ink" and unknown.runs_found == 0
    assert unknown.basis == "calculated" and unknown.polygon_ref and unknown.ink_px_under_polygon == ink.sum()
    assert marks[0].ink_px_under_polygon == 0 and marks[1].ink_px_under_polygon == 0
    assert found[0].region.paired_with is None


def test_ink_near_any_mark_is_not_unknown():
    ink = ink_circle(450, 100, 20)
    text = Mark(id="base.m1", view=VIEW, kind="text", runs_found=3,
                box_ref=[X0 + 440, Y0 + 60, X0 + 475, Y0 + 125])   # covers most of the circle once grown 10 px
    marks, signals = compare_view(VIEW, [text], [], ink)
    assert signals == [] and len(marks) == 1


def test_split_loop_pairs_both_regions():
    ink = ink_circle(200, 200, 15) | ink_circle(260, 200, 15)
    found = analyse_view(ink, VIEW)
    polygon = [[170 + X0, 175 + Y0], [290 + X0, 175 + Y0], [290 + X0, 225 + Y0], [170 + X0, 225 + Y0]]
    marks, _ = compare_view(VIEW, [bubble("base.m1", polygon)], found, ink)
    assert marks[0].cv_regions == ["base.cv1", "base.cv2"]


def test_bubble_without_geometry_is_single_source():
    ink = np.zeros(VIEWS[VIEW].shape, bool)
    marks, signals = compare_view(VIEW, [Mark(id="base.m1", view=VIEW, kind="shading", runs_found=1)], [], ink)
    assert kinds(signals) == ["single_source"] and marks[0].ink_px_under_polygon is None


def test_speck_below_the_unknown_ink_floor_is_ignored():
    ink = np.zeros(VIEWS[VIEW].shape, bool)
    ink[100:108, 450:458] = True   # one 64 px printer dot
    marks, signals = compare_view(VIEW, [], analyse_view(ink, VIEW), ink)
    assert marks == [] and signals == []
