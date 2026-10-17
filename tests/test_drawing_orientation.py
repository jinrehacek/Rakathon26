from drawing_pipeline import reference
from drawing_pipeline.models import AvailabilityStatus, Mark, Sector, SectorShare
from drawing_pipeline.orientation import RIGHT_AT_NEGATIVE, RIGHT_AT_POSITIVE, apply_sides, orient_views


def letter(mark_id, text, x, y, kind="side letter"):
    return Mark(id=mark_id, view=mark_id.split(".")[0], kind=kind, runs_found=3, text=text,
                polygon_ref=[[x - 5, y - 5], [x + 5, y - 5], [x + 5, y + 5], [x - 5, y + 5]], closed=True)


def kinds(signals):
    return sorted(s.kind for s in signals)


def test_explicit_letter_sets_view_and_others_inherit():
    # base axis 1061: L at x<axis means patient left at x<0, so patient right at x>0
    orientations, letters, signals = orient_views([letter("base.m1", "L", 900, 500)])
    base = orientations["base"]
    assert (base.status, base.value, base.basis.value) == (AvailabilityStatus.RECORDED, RIGHT_AT_POSITIVE, "explicit")
    assert letters["base"] == ["base.m1"]
    mid = orientations["mid"]
    assert (mid.value, mid.basis.value, mid.derived_from) == (RIGHT_AT_POSITIVE, "inferred", ["base.orientation"])
    assert orientations["seminal_vesicles"].derived_from == ["base.orientation"]
    assert signals == []


def test_p_and_r_both_mean_patient_right():
    for text in ("p", " R "):
        orientations, _, _ = orient_views([letter("mid.m1", text, 900, 1000)])
        assert orientations["mid"].value == RIGHT_AT_NEGATIVE
        orientations, _, _ = orient_views([letter("mid.m1", text, 1200, 1000)])
        assert orientations["mid"].value == RIGHT_AT_POSITIVE


def test_defaults_without_letters():
    orientations, letters, signals = orient_views([])
    assert orientations["base"].value == RIGHT_AT_NEGATIVE and orientations["base"].basis.value == "inferred"
    assert orientations["coronal"].value == RIGHT_AT_NEGATIVE
    assert orientations["coronal"].certainty.interpretation.value == "low"
    assert orientations["sagittal"].status == AvailabilityStatus.NOT_APPLICABLE
    assert orientations["urethra"].status == AvailabilityStatus.NOT_APPLICABLE
    assert signals == [] and all(not ids for ids in letters.values())


def test_non_letter_text_is_not_a_side_letter():
    orientations, letters, _ = orient_views([letter("base.m1", "X", 900, 500), letter("base.m2", "L", 900, 500, kind="text")])
    assert letters["base"] == [] and orientations["base"].value == RIGHT_AT_NEGATIVE


def test_coronal_letter_is_explicit():
    orientations, letters, _ = orient_views([letter("coronal.m1", "P", 500, 300)])
    assert orientations["coronal"].value == RIGHT_AT_POSITIVE and orientations["coronal"].basis.value == "explicit"
    assert letters["coronal"] == ["coronal.m1"]


def test_conflict_keeps_both_letters_and_no_value():
    orientations, letters, signals = orient_views([letter("apex.m1", "L", 900, 1400), letter("apex.m2", "P", 900, 1450)])
    # both left of the axis, one P and one L
    assert orientations["apex"].status == AvailabilityStatus.UNREADABLE and orientations["apex"].value is None
    assert letters["apex"] == ["apex.m1", "apex.m2"]
    assert kinds(signals) == ["letter_conflict"]
    assert "apex.orientation" in signals[0].observations


def test_sagittal_letter_signals_and_not_applicable():
    orientations, letters, signals = orient_views([letter("sagittal.m1", "P", 300, 1200)])
    assert orientations["sagittal"].status == AvailabilityStatus.NOT_APPLICABLE and orientations["sagittal"].value is None
    assert letters["sagittal"] == ["sagittal.m1"]
    assert kinds(signals) == ["letter_in_sagittal"]


def test_duplicate_letter_from_overlapping_crops_is_one_letter():
    marks = [letter("seminal_vesicles.m1", "L", 900, 365 - 30), letter("base.m3", "L", 905, 335)]
    _, letters, signals = orient_views(marks)
    assert letters["seminal_vesicles"] == ["base.m3"] or letters["seminal_vesicles"] == ["seminal_vesicles.m1"]
    assert sum(len(v) for v in letters.values()) == 1 and signals == []


def test_letter_between_sv_and_base_applies_to_block():
    orientations, letters, _ = orient_views([letter("seminal_vesicles.m1", "L", 900, 365)])
    for name in reference.AXIAL_BLOCK:
        assert letters[name] == ["seminal_vesicles.m1"]
        assert orientations[name].value == RIGHT_AT_POSITIVE and orientations[name].basis.value == "explicit"
    assert letters["coronal"] == []


def test_block_letter_conflicts_with_own_view_letter():
    marks = [letter("seminal_vesicles.m1", "L", 900, 365), letter("mid.m1", "L", 1200, 1000)]
    orientations, _, signals = orient_views(marks)
    assert orientations["mid"].status == AvailabilityStatus.UNREADABLE
    assert "letter_conflict" in kinds(signals)


def sectors(*specs):
    return [Sector(zone=z, level=l, image_side=s) for z, l, s in specs]


def test_apply_sides_and_redcap():
    orientations, _, _ = orient_views([letter("base.m9", "L", 900, 500)])  # patient right at x>0
    mark = Mark(id="base.m1", view="base", kind="closed outline", runs_found=3,
                sectors_named=sectors(("pzpm", "base", "left")),
                sectors_polygon=[SectorShare(zone="pzpm", level="base", image_side="left", px=10, share=1.0)])
    apply_sides([mark], orientations)
    assert mark.sectors_named[0].patient_side == "left"
    assert mark.sectors_polygon[0].redcap == mark.sectors_named[0].redcap
    assert mark.redcap == [mark.sectors_polygon[0].redcap] and mark.redcap[0].endswith("_ls")
    assert mark.patient_side.value == "left" and mark.patient_side.derived_from == ["base.orientation"]


def test_apply_sides_default_orientation_and_bilateral():
    orientations, _, _ = orient_views([])
    mark = Mark(id="mid.m1", view="mid", kind="closed outline", runs_found=3,
                sectors_named=sectors(("pzpl", "mid", "left"), ("pzpl", "mid", "right")))
    apply_sides([mark], orientations)
    assert [s.patient_side for s in mark.sectors_named] == ["right", "left"]
    assert mark.patient_side.value == "bilateral"
    assert len(mark.redcap) == 2


def test_apply_sides_unknown_not_applicable_midline():
    orientations, _, _ = orient_views([letter("apex.m1", "L", 900, 1400), letter("apex.m2", "P", 900, 1450)])
    apex = Mark(id="apex.m3", view="apex", kind="closed outline", runs_found=3, sectors_named=sectors(("cz", "apex", "left")))
    sagittal = Mark(id="sagittal.m1", view="sagittal", kind="closed outline", runs_found=3,
                    sectors_named=sectors(("posterior", "mid", "none")))
    urethra = Mark(id="urethra.m1", view="urethra", kind="small circle", runs_found=3,
                   sectors_named=sectors(("urethra", "apex to base", "midline")))
    apply_sides([apex, sagittal, urethra], orientations)
    assert apex.patient_side.value == "unknown" and apex.sectors_named[0].patient_side is None
    assert sagittal.patient_side.value == "not applicable" and sagittal.redcap == []
    assert urethra.patient_side.value == "midline" and urethra.redcap == ["urethra"]


def test_lettered_axial_conflict_makes_inherited_views_unreadable():
    # base says patient right at x>0, apex says x<0; mid has no letter and must not take either.
    marks = [letter("base.m1", "L", 900, 500), letter("apex.m1", "P", 900, 1400)]
    orientations, _, signals = orient_views(marks)
    assert orientations["mid"].status == AvailabilityStatus.UNREADABLE
    assert orientations["mid"].derived_from == ["base.orientation", "apex.orientation"]
    conflict = next(s for s in signals if s.kind == "letter_conflict")
    assert {"mid.orientation", "seminal_vesicles.orientation"} <= set(conflict.observations)
    mark = Mark(id="mid.m1", view="mid", kind="closed outline", runs_found=3, sectors_named=sectors(("pzpl", "mid", "left")))
    apply_sides([mark], orientations)
    assert mark.patient_side.value == "unknown" and mark.redcap == []


def test_requested_views_only_inherit_from_each_other():
    # The letter sits in the SV/base gap, so it is listed under every axial view, base included.
    marks = [letter("seminal_vesicles.m1", "L", 900, 365)]
    orientations, _, signals = orient_views(marks, ["mid"])
    assert list(orientations) == ["mid"] and signals == []
    assert orientations["mid"].basis.value == "explicit"
    orientations, _, _ = orient_views([letter("base.m1", "L", 900, 500)], ["mid", "apex"])
    assert set(orientations) == {"mid", "apex"} and orientations["mid"].derived_from == []
