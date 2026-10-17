import json

import cv2 as cv
import numpy as np

from drawing_pipeline import preprocess
from drawing_pipeline.preprocess import ink_mask, load_manifest, load_view


def score_image():
    score = np.zeros((300, 400), np.float32)
    score[50, 40:60] = 2.0      # strong dash
    score[50, 60:100] = 0.7     # faint continuation
    score[50, 100:120] = 2.0    # strong dash
    score[200, 40:80] = 0.7     # faint stroke with no seed
    return score


def test_no_hysteresis_is_plain_threshold():
    mask = ink_mask(score_image(), hysteresis=False) > 0
    assert mask[50, 40:60].all() and mask[50, 100:120].all()
    assert not mask[50, 60:100].any() and not mask[200].any()


def test_hysteresis_joins_weak_pixels_connected_to_seeds():
    mask = ink_mask(score_image(), hysteresis=True) > 0
    assert mask[50, 40:120].all()
    assert not mask[200].any()


def test_hysteresis_keeps_minimum_component_filter():
    score = np.zeros((50, 50), np.float32)
    score[10, 10] = 2.0
    score[10, 11] = 0.7
    assert not ink_mask(score, hysteresis=True).any()


def test_scanner_border_band_removed_with_hysteresis():
    score = np.zeros((300, 400), np.float32)
    score[20:280, 390:398] = 0.7
    for y in range(20, 280, 40):
        score[y:y + 20, 393] = 2.0
    assert ink_mask(score, hysteresis=False).any()        # short dashes pass the old rule
    assert not ink_mask(score, hysteresis=True).any()     # the joined band is a border


def test_load_manifest(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(
        {"cases": {"abc": {"drawing": "abc/drawing.jpg", "report": "abc/report.jpg"}}}))
    assert load_manifest(tmp_path / "manifest.json") == {"abc": tmp_path.resolve() / "abc/drawing.jpg"}


def test_load_view(tmp_path):
    folder = tmp_path / "preprocess/views/base"
    folder.mkdir(parents=True)
    image = np.full((4, 5, 3), 200, np.uint8)
    mask = np.zeros((4, 5), np.uint8)
    mask[1, 2] = 255
    cv.imwrite(str(folder / "original.png"), image)
    cv.imwrite(str(folder / "cleaned.png"), image)
    cv.imwrite(str(folder / "mask.png"), mask)
    original, cleaned, loaded = load_view(tmp_path, "base")
    assert original.shape == (4, 5, 3) and loaded.dtype == bool and loaded.sum() == 1 and loaded[1, 2]


def test_prepare_writes_failure_metadata(tmp_path):
    blank = tmp_path / "blank.png"
    cv.imwrite(str(blank), np.full((200, 150, 3), 255, np.uint8))
    try:
        preprocess.prepare(blank, tmp_path / "out")
    except ValueError:
        pass
    else:
        raise AssertionError("alignment of a blank page should fail")
    metadata = json.loads((tmp_path / "out/preprocess/metadata.json").read_text())
    assert "failure" in metadata and metadata["hysteresis"] is True
