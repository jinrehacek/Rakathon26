import cv2 as cv
import numpy as np
import pytest

from drawing_pipeline import grading, reference
from drawing_pipeline.models import CVRegion, DrawingOutput, Extraction, Group, Mark, SectorShare, signal
from drawing_pipeline.orientation import apply_sides, orient_views
from drawing_pipeline.output import build_output, view_out


def make_output():
    marks = [Mark(id="base.m1", view="base", kind="closed outline", runs_found=3,
                  polygon_ref=[[800, 450], [900, 450], [900, 550], [800, 550]], closed=True,
                  sectors_polygon=[SectorShare(zone="pzpm", level="base", image_side="left", px=50, share=0.7),
                                   SectorShare(zone="cz", level="base", image_side="left", px=20, share=0.3)]),
             Mark(id="base.m2", view="base", kind="text", runs_found=3, text="zánět|x", box_ref=[900, 600, 950, 620]),
             Mark(id="mid.m1", view="mid", kind="open arc", runs_found=1, box_ref=[800, 900, 900, 950])]
    orientations, letters, _ = orient_views(marks)
    apply_sides(marks, orientations)
    views = [view_out(name, orientations[name], letters[name]) for name in reference.VIEWS]
    extraction = Extraction(case_id="case1", source_path="x", source_sha256="0" * 64, timestamp_utc="t", git_sha=None,
                            model="m", prompt_sha256={}, thresholds={}, alignment={})
    regions = [CVRegion(id="base.cv1", view="base", kind="closed outline", px=100, box_ref=[800, 450, 900, 550])]
    return build_output(extraction, views, marks, regions, [Group(id="g1", members=["base.m1", "mid.m1"], proposed_finding_kind="tumour", reason="r")],
                        [], [], [signal("single_source", ["mid.m1"], "no cv pair")])


def write_crops(case):
    for name, view in reference.VIEWS.items():
        folder = case / "preprocess/views" / name
        folder.mkdir(parents=True)
        for filename in ("original", "cleaned"):
            cv.imwrite(str(folder / f"{filename}.png"), np.full((*view.shape, 3), 200, np.uint8))


def test_make_sheets(tmp_path):
    write_crops(tmp_path)
    output = make_output()
    index = grading.make_sheets(tmp_path, output)
    page = index.read_text(encoding="utf-8")
    assert index == tmp_path / "grading/index.html"
    for name in reference.VIEWS:
        image = cv.imread(str(tmp_path / f"grading/{name}.png"))
        assert image.shape[1] > 3 * reference.VIEWS[name].shape[1]
    assert "base.m1" in page and "pzpm base left, patient right 70%" in page and "single_source" in page
    assert "zánět|x" in page
    # provided overlay is used instead of boxes
    overlay = np.zeros((*reference.VIEWS["base"].shape, 3), np.uint8)
    grading.make_sheets(tmp_path, output, {"base": overlay})
    assert cv.imread(str(tmp_path / "grading/base.png"))[24:, -overlay.shape[1] - 6:-6].max() == 0


def test_missing_crop_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        grading.make_sheets(tmp_path, make_output())


def test_template_and_no_overwrite(tmp_path):
    output = make_output()
    text = grading.grading_template([output], 1)
    assert "## Case case1" in text and "### base" in text
    rows = [line for line in text.splitlines() if line.startswith("| base.m1 |")]
    assert [r.split("|")[2].strip() for r in rows] == ["(a) named", "(b) polygon", "(c) cv", "mark"]
    assert all(r.endswith("| |") for r in rows)
    assert "| g1 | base.m1, mid.m1 | tumour | |" in text
    assert "base.m2" not in text.split("### mid")[0].split("| bubble |")[1]
    path = grading.write_template([output], 1, root=tmp_path)
    assert path == tmp_path / "round-1.md" and path.read_text(encoding="utf-8") == text
    path.write_text("graded")
    with pytest.raises(FileExistsError):
        grading.write_template([output], 1, root=tmp_path)
    assert path.read_text() == "graded"
