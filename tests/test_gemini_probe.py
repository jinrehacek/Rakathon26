import importlib.util
import json
from pathlib import Path

import httpx
import numpy as np
import pytest
from pydantic import ValidationError

spec = importlib.util.spec_from_file_location("probe", Path(__file__).resolve().parents[1] / "scripts/probe_gemini.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def response(value):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(value)}]}}]}


def test_pass_request_is_one_image_and_one_fresh_message():
    body = probe.request_body("Original crop; inspect all marks", b"image")
    assert len(body["contents"]) == 1
    assert body["contents"][0]["role"] == "user"
    assert sum("inlineData" in p for p in body["contents"][0]["parts"]) == 1
    assert "cachedContent" not in body and "tools" not in body
    assert body["generationConfig"]["mediaResolution"] == "MEDIA_RESOLUTION_HIGH"


def test_no_marks_is_valid_but_truncated_output_is_not():
    data = response({"coverage": "complete", "coverage_issues": [], "marks": []})
    assert probe.parse_response(data).marks == []
    data["candidates"][0]["finishReason"] = "MAX_TOKENS"
    with pytest.raises(ValueError):
        probe.parse_response(data)


def test_missing_values_and_open_geometry_are_not_silently_changed():
    with pytest.raises(ValidationError):
        probe.TextReading(status="unreadable", value="probably 10mm", certainty="low", reason="guess")
    with pytest.raises(ValidationError):
        probe.TextReading(status="unreadable", value="", certainty="low", reason="missing")
    with pytest.raises(ValidationError):
        probe.SectorReading(status="recorded", value=None, candidates=[], certainty="low", reason="missing")
    with pytest.raises(ValidationError):
        probe.Geometry(kind="closed_outline", points_xy=[[10, 20], [30, 40]], reason="open")
    with pytest.raises(ValidationError):
        probe.Geometry(kind="open_polyline", points_xy=[[10, 1001], [30, 40]], reason="outside")


def test_api_schema_avoids_array_bounds_but_local_validation_keeps_them():
    sent = json.dumps(probe.api_schema())
    assert '"maxItems"' not in sent and '"minItems"' not in sent
    assert '"maxItems"' in json.dumps(probe.Reading.model_json_schema())


def test_retry_once_preserves_both_attempts(tmp_path):
    calls = []
    good = response({"coverage": "complete", "coverage_issues": [], "marks": []})
    def handle(request):
        calls.append(request)
        return httpx.Response(503, json={"error": "temporary"}) if len(calls) == 1 else httpx.Response(200, json=good)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        reading, history = probe.call_with_retry(client, "https://example.test/model", "secret", {}, tmp_path, sleeper=lambda _: None)
    assert reading is not None and len(calls) == len(history) == 2
    assert (tmp_path / "attempt_1_error.json").exists()
    assert (tmp_path / "attempt_2_response.json").exists()
    assert "secret" not in json.dumps(history)


def test_permanent_error_is_not_retried_and_malformed_json_is_bounded(tmp_path):
    for status, payload, expected in [(401, {"error": "unauthorized"}, 1), (200, response({"bad": "schema"}), 2)]:
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(status, json=payload)
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            reading, history = probe.call_with_retry(client, "https://example.test/model", "secret", {}, tmp_path, sleeper=lambda _: None)
        assert reading is None and len(calls) == len(history) == expected


def test_polygon_coordinates_use_whole_crop_and_keep_small_contacts():
    mark = probe.Mark.model_construct(kind="outline", box_2d=[200, 200, 400, 400], geometry=probe.Geometry(kind="closed_outline", points_xy=[[200, 200], [400, 200], [400, 400], [200, 400]], reason="trace"))
    mask = np.zeros((100, 200), np.uint8)
    mask[20:41, 40] = 255
    sectors = [{"key": 7, "name": "template test", "reference_coordinates_px": [[90, 30], [100, 30], [100, 40], [90, 40]]}]
    translation = [[1, 0, 500], [0, 1, 600], [0, 0, 1]]
    result = probe.polygon_diagnostics(mark, mask, np.array([10, 10, 200, 100]), translation, sectors)
    assert result["source_points_xy"][0] == [540, 620]
    assert result["reference_polygon_contacts"][0]["reference_key"] == 7
    assert result["polygon_area_px"] == 800


def test_open_arc_is_not_filled_for_sector_contact():
    mark = probe.Mark.model_construct(kind="open_arc", box_2d=[100, 100, 900, 900], geometry=probe.Geometry(kind="open_polyline", points_xy=[[100, 100], [900, 100], [900, 900]], reason="gap"))
    sectors = [{"key": 1, "name": "inside imaginary closure", "reference_coordinates_px": [[48, 48], [52, 48], [52, 52], [48, 52]]}]
    result = probe.polygon_diagnostics(mark, np.zeros((100, 100), np.uint8), np.array([0, 0, 100, 100]), np.eye(3), sectors)
    assert not result["closed"]
    assert result["reference_polygon_contacts"] == []


def test_crossing_polygon_is_preserved_but_not_used_for_filled_overlap():
    geometry = probe.Geometry(kind="closed_outline", points_xy=[[100, 100], [900, 900], [900, 100], [100, 900]], reason="model bow tie")
    mark = probe.Mark.model_construct(kind="outline", box_2d=[100, 100, 900, 900], geometry=geometry)
    sectors = [{"key": 1, "name": "test", "reference_coordinates_px": [[0, 0], [99, 0], [99, 99], [0, 99]]}]
    result = probe.polygon_diagnostics(mark, np.zeros((100, 100), np.uint8), np.array([0, 0, 100, 100]), np.eye(3), sectors)
    assert any("crossing segments" in reason for reason in result["geometry_issues"])
    assert result["reference_polygon_contacts"] == []
    assert mark.geometry.points_xy == geometry.points_xy
