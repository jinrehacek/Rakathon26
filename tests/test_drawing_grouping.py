import json

import cv2 as cv
import numpy as np

from drawing_pipeline import grouping, llm
from drawing_pipeline.models import Group, Mark, PatientSide, Sector, SectorShare
from drawing_pipeline.orientation import apply_sides, orient_views


def mark(mark_id, side=None, levels=(), box=(10, 10, 60, 60), **kwargs):
    view = mark_id.split(".")[0]
    m = Mark(id=mark_id, view=view, kind="closed outline", runs_found=3, box_ref=list(box),
             sectors_named=[Sector(zone="prostate" if view == "coronal" else "pzpm", level=l, image_side="left") for l in levels],
             **kwargs)
    if side:
        m.patient_side = PatientSide(value=side)
    return m


def group(gid, members, bilateral=False):
    return Group(id=gid, members=members, proposed_finding_kind="tumour", reason="r", bilateral=bilateral)


def kinds(signals):
    return [s.kind for s in signals]


def test_sides_must_agree_unless_bilateral():
    marks = [mark("base.m1", "right"), mark("mid.m1", "left"), mark("apex.m1", "unknown"), mark("apex.m2", "midline")]
    assert kinds(grouping.check_groups([group("g1", ["base.m1", "apex.m1", "apex.m2"])], marks)) == []
    assert kinds(grouping.check_groups([group("g1", ["base.m1", "mid.m1"])], marks)) == ["group_check_failed"]
    assert kinds(grouping.check_groups([group("g1", ["base.m1", "mid.m1"], bilateral=True)], marks)) == []


def test_only_coronal_breaking_is_coronal_maybe_mirrored():
    marks = [mark("coronal.m1", "left"), mark("base.m1", "right"), mark("mid.m1", "right")]
    signals = grouping.check_groups([group("g1", ["coronal.m1", "base.m1", "mid.m1"])], marks)
    assert kinds(signals) == ["coronal_maybe_mirrored"] and "coronal.orientation" in signals[0].observations
    marks = [mark("coronal.m1", "left"), mark("base.m1", "right"), mark("mid.m1", "left")]
    assert kinds(grouping.check_groups([group("g1", ["coronal.m1", "base.m1", "mid.m1"])], marks)) == ["group_check_failed"]


def test_axial_levels_match_longitudinal_bands():
    marks = [mark("coronal.m1", "right", ["base", "mid"]), mark("sagittal.m1", "right", ["base", "mid"]),
             mark("base.m1", "right"), mark("mid.m1", "right"), mark("apex.m1", "right")]
    assert kinds(grouping.check_groups([group("g1", ["coronal.m1", "sagittal.m1", "base.m1", "mid.m1"])], marks)) == []
    signals = grouping.check_groups([group("g1", ["coronal.m1", "sagittal.m1", "base.m1", "mid.m1", "apex.m1"])], marks)
    assert kinds(signals) == ["group_check_failed"] * 2 and "apex" in signals[0].reason
    # without a sagittal member the level check does not run
    assert kinds(grouping.check_groups([group("g1", ["coronal.m1", "base.m1", "apex.m1"])], marks)) == []


def test_bands_fall_back_to_polygon_shares_above_floor():
    coronal = mark("coronal.m1", "right")
    coronal.sectors_polygon = [SectorShare(zone="prostate", level="base", image_side="left", px=90, share=0.9),
                               SectorShare(zone="prostate", level="apex", image_side="left", px=2, share=0.02)]
    assert grouping._bands([coronal]) == {"base"}


def test_mark_in_two_groups():
    marks = [mark("base.m1", "right"), mark("mid.m1", "right"), mark("apex.m1", "right")]
    signals = grouping.check_groups([group("g1", ["base.m1", "mid.m1"]), group("g2", ["base.m1", "apex.m1"])], marks)
    assert kinds(signals) == ["group_check_failed"] and signals[0].observations == ["g1", "g2", "base.m1"]


def case_dir(tmp_path):
    folder = tmp_path / "preprocess"
    folder.mkdir()
    sheet = np.full((reference_h, reference_w, 3), 255, np.uint8)
    cv.imwrite(str(folder / "aligned.png"), sheet)
    cv.imwrite(str(folder / "cleaned.png"), sheet)
    return tmp_path


reference_h, reference_w = 1737, 1342


class FakeClient:
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    def post(self, url, headers, json):
        self.calls.append(json)
        payload = self.payload

        class Response:
            status_code = 200

            def json(self_):
                return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": __import__("json").dumps(payload)}]}}]}
        return Response()


def all_marks():
    return [mark("base.m1", "right", box=(800, 400, 900, 480)), mark("mid.m1", "right", box=(800, 900, 900, 980)),
            mark("apex.m1", "right", box=(850, 1300, 900, 1350)), mark("coronal.m1", "right", box=(100, 600, 200, 700)),
            mark("base.m2", "right", box=(1000, 400, 1050, 450))]


RESPONSE = {
    "groups": [{"id": "g1", "members": ["base.m1", "mid.m1", "ghost.m1", "g.m9"], "proposed_finding_kind": "tumour",
                "reason": "same", "bilateral": False},
               {"id": "g2", "members": ["apex.m1", "coronal.m1"], "proposed_finding_kind": "other", "reason": "zánět", "bilateral": False},
               {"id": "g3", "members": ["base.m2", "ghost.m2"], "proposed_finding_kind": "unresolved", "reason": "unsure", "bilateral": False}],
    "standalone": [{"mark": "ghost.m3", "reason": "x"}], "not_lesion": [],
}


def test_run_grouping_cleans_response_and_saves_files(tmp_path):
    case = case_dir(tmp_path)
    marks = all_marks()
    client = FakeClient(RESPONSE)
    fixed = [group("g1", ["apex.m1", "coronal.m1"])]
    groups, standalone, not_lesion, signals = grouping.run_grouping(case, marks, orient_views(marks)[0], client=client, key="k",
                                                                     fixed_groups=fixed)
    assert len(client.calls) == 1
    body = json.dumps(client.calls[0])
    assert "fixed_groups" in body and "zánět" in open(grouping.PROMPT, encoding="utf-8").read()
    assert (case / "grouping/annotated.png").exists() and (case / "grouping/request.json").exists()
    # fixed group first and unchanged; g1 collides and is renamed; its members minus fixed ones leave 2 of 4 valid
    assert groups[0].id == "g1" and groups[0].fixed and groups[0].members == ["apex.m1", "coronal.m1"]
    assert [g.members for g in groups[1:]] == [["base.m1", "mid.m1"]] and groups[1].id != "g1"
    # g2 lost its fixed members (empty), g3 left with one member goes to standalone
    assert [(r.mark) for r in standalone] == ["base.m2"] and not_lesion == []
    assert signals == []


def test_replay_needs_no_client(tmp_path):
    case = case_dir(tmp_path)
    marks = all_marks()
    orientations = orient_views(marks)[0]
    grouping.run_grouping(case, marks, orientations, client=FakeClient(RESPONSE), key="k")
    client = FakeClient({})
    groups, *_ = grouping.run_grouping(case, marks, orientations, client=client, key="k", replay=True)
    assert client.calls == [] and groups[0].id == "g1"


def test_annotated_sheet_draws_and_does_not_touch_input():
    cleaned = np.full((reference_h, reference_w, 3), 255, np.uint8)
    marks = [mark("base.m1", box=(800, 400, 900, 480)),
             Mark(id="mid.m1", view="mid", kind="open arc", runs_found=1, polygon_ref=[[800, 900], [850, 950], [900, 900]])]
    image = grouping.annotated_sheet(cleaned, marks)
    assert cleaned.min() == 255 and image.min() < 255 and image.shape == cleaned.shape
    gray = grouping.annotated_sheet(cleaned[:, :, 0], marks)
    assert gray.shape == cleaned.shape


def test_prompt_hash_and_marks_json():
    assert len(grouping.prompt_sha256()) == 64
    marks = [mark("base.m1", levels=["base"])]
    marks[0].linked_to = None
    orientations, _, _ = orient_views(marks)
    apply_sides(marks, orientations)
    payload = grouping.marks_json(marks, orientations)
    assert payload["marks"][0]["sectors"][0]["patient_side"] == "right"
    assert payload["orientation"]["base"] == "patient right at x<0" and payload["orientation"]["sagittal"] == "not applicable"
