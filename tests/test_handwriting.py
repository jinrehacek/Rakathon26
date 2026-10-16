import importlib.util
from pathlib import Path

import cv2 as cv
import numpy as np

spec = importlib.util.spec_from_file_location("handwriting", Path(__file__).resolve().parents[1] / "scripts/extract_handwriting.py")
handwriting = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handwriting)


def template():
    reference = np.full((240, 300, 3), 245, np.uint8)
    cv.line(reference, (150, 15), (150, 225), (15, 15, 15), 2)
    return reference, cv.cvtColor(reference, cv.COLOR_BGR2GRAY)


def test_blank_template_does_not_become_handwriting():
    reference, gray = template()
    result = handwriting.isolate(reference.copy(), reference, gray)
    assert not np.any(result["mask"])
    assert np.array_equal(result["modified"], reference)


def test_faint_yellow_and_colour_crossing_printed_line_are_retained():
    reference, gray = template()
    source = reference.copy()
    cv.line(source, (30, 40), (110, 40), (233, 247, 247), 3)
    cv.line(source, (100, 110), (200, 110), (180, 150, 225), 3)
    result = handwriting.isolate(source, reference, gray)
    assert result["mask"][40, 70] == 255
    assert result["mask"][110, 150] == 255
    assert not result["mask"][70, 150]  # Unmarked printed line stays background.


def test_broad_neutral_pencil_shading_is_not_normalized_away():
    reference, gray = template()
    source = reference.copy()
    source[65:175, 25:100] = 155
    result = handwriting.isolate(source, reference, gray)
    assert np.mean(result["mask"][80:160, 40:85] == 255) > .98


def test_open_arc_stays_open_and_display_uses_exact_mask_geometry():
    reference, gray = template()
    source = reference.copy()
    cv.ellipse(source, (70, 140), (30, 40), 0, 35, 320, (190, 130, 220), 3)
    result = handwriting.isolate(source, reference, gray)
    mask = result["mask"] > 0
    assert not mask[140, 100]  # Gap at the rightmost point.
    assert not mask[140, 70]  # Interior is never filled.
    assert np.array_equal(result["black"][:, :, 3], result["mask"])
    assert not np.any(result["black"][:, :, :3])
    assert np.array_equal(result["color_ink"][:, :, :3], source)
    assert np.array_equal(result["modified"][~mask], reference[~mask])
    assert not np.any(result["modified"][mask])


def test_blank_page_is_rejected_by_alignment():
    reference, gray = template()
    try:
        handwriting.align(np.full_like(reference, 255), gray)
    except ValueError as error:
        assert "Alignment failed" in str(error)
    else:
        raise AssertionError("Blank page was accepted")
