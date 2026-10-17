import numpy as np
import pytest

from drawing_pipeline import geometry, llm, reference
from drawing_pipeline.models import Mark, Sector, signal


def test_every_view_has_its_regions_and_sv_is_included():
    counts = {view: len(reference.regions_for(view)) for view in reference.VIEWS}
    assert counts == {"coronal": 6, "sagittal": 6, "seminal_vesicles": 2, "base": 14, "mid": 12, "apex": 12, "urethra": 1}


def test_ctsit_sides_come_from_geometry_against_the_axis():
    for region in reference.regions():
        if region.ctsit_key and region.zone != "urethra":
            axis = reference.VIEWS[region.view].axis_x
            assert (region.polygon[:, 0].mean() < axis) == (region.image_side == "left")


def test_redcap_uses_patient_side_not_drawn_side():
    assert reference.redcap_code("PZpm", "base", "right") == "pzpm_base_rs"
    assert reference.redcap_code("pzpm", "base", "left") == "pzpm_base_ls"
    assert reference.redcap_code("AFS", "apex", "left") == "as_apex_ls"
    assert reference.redcap_code("SV", "seminal vesicles", "right") == "sv_base_rs"
    assert reference.redcap_code("urethra", "urethra", None) == "urethra"
    assert reference.redcap_code("pzpm", "base", None) is None
    assert reference.redcap_code("prostate", "base", "left") is None


def test_unknown_zone_is_rejected():
    with pytest.raises(ValueError):
        reference.normalize_zone("PZx")


def test_sector_shares_sum_to_one_and_split_at_the_axis():
    view = reference.VIEWS["base"]
    mask = np.zeros(view.shape, bool)
    axis = view.axis_x - view.origin[0]
    mask[300:340, axis - 20:axis + 20] = True
    shares = reference.sector_shares(mask, "base")
    assert abs(sum(s["share"] for s in shares) - 1) < 1e-3
    assert {s["image_side"] for s in shares} == {"left", "right"}
    assert all(isinstance(s["share"], float) for s in shares)


def test_coronal_levels_follow_the_printed_dashed_lines():
    view = reference.VIEWS["coronal"]
    mask = np.zeros(view.shape, bool)
    x = 200 - view.origin[0]
    for y, level in ((500, "base"), (650, "mid"), (800, "apex")):
        mask[:] = False
        mask[y - view.origin[1] - 5:y - view.origin[1] + 5, x:x + 10] = True
        assert reference.sector_shares(mask, "coronal")[0]["level"] == level


def test_raster_closed_open_and_box():
    shape = (100, 100)
    square = [[10, 10], [50, 10], [50, 50], [10, 50]]
    assert geometry.raster(shape, square, closed=True).sum() > 1500
    assert geometry.raster(shape, square, closed=False).sum() < 1000
    assert geometry.raster(shape, None, box=[0, 0, 9, 9]).sum() == 100
    assert geometry.iou(geometry.raster(shape, square), geometry.raster(shape, square)) == 1


def test_normalized_coordinates_map_to_crop_px():
    h, w = reference.VIEWS["base"].shape
    assert np.allclose(geometry.normalized_to_crop([[500, 1000]], "base"), [[w / 2, h]])
    assert np.allclose(geometry.normalized_box_to_crop([0, 0, 1000, 500], "base"), [0, 0, w / 2, h])


def test_signal_gets_default_suggestion_and_mark_defaults():
    assert signal("single_source", ["base.m1"], "x").suggestion == "info only"
    assert signal("low_trust_note", ["base.m2"], "x").suggestion == "text is probably right"
    mark = Mark(id="base.m1", view="base", kind="closed outline", runs_found=3,
                sectors_named=[Sector(zone="pzpm", level="base", image_side="left")])
    assert mark.review_status == "unreviewed"


def test_llm_logs_images_as_hashes_and_never_the_key(tmp_path):
    body = llm.request_body([{"text": "p"}, llm.image_part(b"png")], Mark)
    assert body["generationConfig"]["temperature"] == 1.0
    assert "cachedContent" not in body
    record = llm.request_record(body)
    assert record["parts"][1] == {"image_sha256": llm.sha256(b"png")}

    import httpx

    def handler(request):
        return httpx.Response(500, json={"error": "boom"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        parsed, history = llm.call(client, "m", "SECRETKEY", body, Mark, tmp_path, sleeper=lambda s: None)
    assert parsed is None and len(history) == 2
    assert all("SECRETKEY" not in p.read_text() for p in tmp_path.iterdir())


def test_a_new_call_clears_old_attempts(tmp_path):
    import httpx
    (tmp_path / "attempt_2_response.json").write_text("{}")
    good = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"id": "base.m1", "view": "base", "kind": "other", "runs_found": 1}'}]}}]}
    body = llm.request_body([{"text": "p"}], Mark)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=good))) as client:
        parsed, _ = llm.call(client, "m", "k", body, Mark, tmp_path)
    assert parsed.id == "base.m1" and not (tmp_path / "attempt_2_response.json").exists()
    assert llm.replay(tmp_path, Mark).id == "base.m1"


def test_view_level_is_one_of_its_region_levels_where_the_view_has_one_level():
    # The prompt names the view's level; Gemini copies it into sectors, so it must be a valid enum value.
    for name, view in reference.VIEWS.items():
        levels = {r.level for r in reference.regions_for(name)}
        if len(levels) == 1:
            assert view.level in levels, name
