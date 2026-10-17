import json
import threading

import cv2 as cv
import httpx
import numpy as np
import pytest
from pydantic import ValidationError

from drawing_pipeline import gemini, llm
from drawing_pipeline.reference import VIEWS


def mark(**update):
    value = {"id": "m1", "kind": "closed outline", "polygon": [[100, 100], [300, 100], [300, 300], [100, 300]],
             "box_2d": [100, 100, 300, 300], "text": None,
             "sectors": [{"zone": "PZpl", "level": "base", "image_side": "left"}]}
    return value | update


def response(marks):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({"marks": marks})}]}}]}


def test_schema_enums_follow_the_view():
    gemini.reading_schema("base").model_validate({"marks": [mark()]})
    with pytest.raises(ValidationError):
        gemini.reading_schema("base").model_validate({"marks": [mark(sectors=[
            {"zone": "prostate", "level": "base", "image_side": "left"}])]})
    gemini.reading_schema("coronal").model_validate({"marks": [mark(sectors=[
        {"zone": "prostate", "level": "apex", "image_side": "right"}])]})
    gemini.reading_schema("sagittal").model_validate({"marks": [mark(sectors=[
        {"zone": "posterior", "level": "mid", "image_side": "none"}])]})
    gemini.reading_schema("seminal_vesicles").model_validate({"marks": [mark(sectors=[
        {"zone": "SV", "level": "seminal vesicles", "image_side": "right"}])]})
    gemini.reading_schema("urethra").model_validate({"marks": [mark(sectors=[
        {"zone": "urethra", "level": "urethra", "image_side": "midline"}])]})


@pytest.mark.parametrize("bad", [
    {"box_2d": [300, 100, 100, 300]},                       # inverted
    {"box_2d": [100, 100, 300, 1001]},                      # out of range
    {"polygon": [[1, 1], [2, 2]]},                          # closed kind with two points
    {"kind": "open arc", "polygon": [[1, 1]]},
    {"kind": "lesion"},
    {"certainty": "high"},                                  # no self-reported certainty
])
def test_schema_rejects_bad_marks(bad):
    with pytest.raises(ValidationError):
        gemini.reading_schema("base").model_validate({"marks": [mark(**bad)]})


def test_schema_accepts_flat_box_and_empty_polygon():
    letter = mark(kind="side letter", polygon=[], box_2d=[50, 40, 50, 60], text="P", sectors=[])
    gemini.reading_schema("base").model_validate({"marks": [letter]})
    with pytest.raises(ValidationError):
        gemini.reading_schema("base").model_validate({"marks": [letter, letter]})
    assert "minItems" not in json.dumps(llm.api_schema(gemini.reading_schema("base")))


def test_map_image():
    h, w = VIEWS["base"].shape
    base = np.full((h, w, 3), 230, np.uint8)
    assert np.array_equal(gemini.map_image(base, "base"), base)
    h, w = VIEWS["coronal"].shape
    gray = np.full((h, w), 230, np.uint8)
    drawn = gemini.map_image(gray, "coronal")
    assert drawn.shape == (h, w, 3)
    assert np.any(np.all(drawn == gemini.MAP_COLOUR, axis=2))


def write_case(tmp_path, view):
    h, w = VIEWS[view].shape
    folder = tmp_path / "preprocess/views" / view
    folder.mkdir(parents=True)
    cv.imwrite(str(folder / "original.png"), np.full((h, w, 3), 200, np.uint8))
    cv.imwrite(str(folder / "cleaned.png"), np.full((h, w, 3), 240, np.uint8))


def test_read_view_live_and_replay(tmp_path):
    write_case(tmp_path, "base")
    marks = [mark(), mark(id="m2", kind="side letter", polygon=[], box_2d=[10, 20, 40, 50], text="L", sectors=[])]
    calls, lock, bodies = [0], threading.Lock(), []

    def handler(request):
        with lock:
            calls[0] += 1
            n = calls[0]
        bodies.append(json.loads(request.content))
        if n == 3:
            return httpx.Response(400, json={"error": {"message": "bad"}})
        return httpx.Response(200, json=response(marks))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        runs = gemini.read_view(tmp_path, "base", client=client, key="test")

    assert sum(run is None for run in runs) == 1 and len(runs) == 3
    parts = bodies[0]["contents"][0]["parts"]
    assert [("text" in p, "inlineData" in p) for p in parts] == [(True, False), (True, False), (False, True),
                                                                   (True, False), (False, True)]
    assert parts[1]["text"] == "Image 1: original colour crop"
    assert bodies[0]["generationConfig"]["temperature"] == 1.0
    assert (tmp_path / "gemini/base/map.png").exists()

    run = next(run for run in runs if run is not None)
    h, w = VIEWS["base"].shape
    outline, letter = run
    assert outline.closed and outline.polygon_crop[1] == pytest.approx([300 * w / 1000, 100 * h / 1000])
    assert outline.sectors[0].zone == "pzpl"
    assert letter.polygon_crop is None and letter.box_crop == pytest.approx([20 * w / 1000, 10 * h / 1000,
                                                                             50 * w / 1000, 40 * h / 1000])
    assert letter.text == "L" and not letter.closed

    replayed = gemini.read_view(tmp_path, "base", client=None, key=None, replay=True)
    assert [r is None for r in replayed] == [r is None for r in runs]
    assert [r for r in replayed if r] == [r for r in runs if r]


def test_prompt_hash_is_stable():
    assert gemini.prompt_sha256() == gemini.prompt_sha256() and len(gemini.prompt_sha256()) == 64
