import pytest

from drawing_pipeline.models import (CVRegion, Extraction, Group, Mark, MarkReason, Observation, ReviewStatus, signal)
from drawing_pipeline.orientation import orient_views
from drawing_pipeline.output import build_output, load, view_out, write
from drawing_pipeline import reference


def extraction():
    return Extraction(case_id="case1", source_path="x.png", source_sha256="0" * 64, timestamp_utc="2026-10-17T00:00:00Z",
                      git_sha=None, model="m", prompt_sha256={}, thresholds={}, alignment={})


def views():
    orientations, letters, _ = orient_views([])
    return [view_out(name, orientations[name], letters[name]) for name in reference.VIEWS]


def marks():
    return [Mark(id="base.m1", view="base", kind="closed outline", runs_found=2, box_ref=[1, 2, 3, 4]),
            Mark(id="mid.m1", view="mid", kind="closed outline", runs_found=3, box_ref=[1, 2, 3, 4])]


def test_view_out_uses_reference():
    v = view_out("base", Observation(status="recorded", value="patient right at x<0"), ["base.m5"])
    assert v.panel_region_ref == [750, 330, 590, 460] and v.coordinate_convention["axis_x_ref"] == 1061
    assert v.letters == ["base.m5"] and v.view_type == "cross-sectional"
    assert view_out("sagittal", Observation(status="not applicable"), []).coordinate_convention["origin"] == "crop top-left"


def test_signals_flag_marks_groups_and_orientation(tmp_path):
    group = Group(id="g1", members=["base.m1", "mid.m1"], proposed_finding_kind="tumour", reason="r")
    signals = [signal("run_instability", ["base.m1"], "found in 2 of 3 runs"),
               signal("group_check_failed", ["g1"], "levels differ"),
               signal("coronal_maybe_mirrored", ["g1", "coronal.orientation"], "mirrored?"),
               signal("single_source", ["base.m1.sectors", "base.cv1"], "no cv pair")]
    cv_region = CVRegion(id="base.cv1", view="base", kind="open stroke", px=5, box_ref=[0, 0, 1, 1])
    out = build_output(extraction(), views(), marks(), [cv_region], [group], [MarkReason(mark="mid.m1", reason="x")], [], signals)
    by_id = {m.id: m for m in out.marks}
    assert by_id["base.m1"].review_status == ReviewStatus.NEEDS_REVIEW
    assert by_id["base.m1"].certainty.explanation == "run_instability: found in 2 of 3 runs; single_source: no cv pair"
    assert by_id["mid.m1"].review_status == ReviewStatus.UNREVIEWED
    assert out.groups[0].review_status == ReviewStatus.NEEDS_REVIEW
    coronal = next(v for v in out.views if v.id == "coronal").orientation
    assert coronal.review_status == ReviewStatus.NEEDS_REVIEW and "mirrored?" in coronal.certainty.explanation
    assert len(out.signals) == 4
    # inputs untouched
    assert marks()[0].review_status == ReviewStatus.UNREVIEWED
    path = tmp_path / "case1" / "drawing.json"
    write(out, path)
    assert load(path) == out


def test_unknown_ids_raise():
    with pytest.raises(ValueError, match="unknown observation"):
        build_output(extraction(), views(), marks(), [], [], [], [], [signal("unknown_ink", ["base.u9"], "x")])
    with pytest.raises(ValueError, match="unknown marks"):
        group = Group(id="g1", members=["base.m1", "base.m9"], proposed_finding_kind="other", reason="r")
        build_output(extraction(), views(), marks(), [], [group], [], [], [])
    with pytest.raises(ValueError, match="Unknown mark"):
        build_output(extraction(), views(), marks(), [], [], [MarkReason(mark="x.m1", reason="r")], [], [])
