"""The LLM brain is optional, JSON-only, and validated against pinned IDs."""

from __future__ import annotations

import json
import os
import unittest
from copy import deepcopy
from unittest.mock import patch

from central.llm import MODEL, run_llm


def subject(subject_id: str, kind: str = "tumour_focus") -> dict:
    return {
        "id": subject_id,
        "kind": kind,
        "label": subject_id,
        "identification_basis": "explicit",
        "parent_id": None,
        "evidence_ids": ["e1"],
    }


def report_bundle() -> dict:
    return {
        "document": {"id": "doc-1", "source_path": "/cases/demo/report.jpg"},
        "text_layer": {"id": "layer-1", "text": "Synthetic report text.", "image_width": 900, "image_height": 1200},
        "extraction": {
            "id": "extract-1",
            "output_contract_version": "report-2",
            "complete": True,
            "source_text_sha256": "a" * 64,
            "subjects": [
                subject("specimen", "specimen"),
                subject("focus-a"),
                subject("focus-b"),
                subject("inflammation", "other_finding"),
            ],
            "evidence": [
                {
                    "id": "e1",
                    "text_layer_id": "layer-1",
                    "page": 1,
                    "quotation": "Synthetic quotation.",
                    "start_offset": 0,
                    "end_offset": 19,
                    "offset_convention": "test",
                    "image_region": {"x": 1, "y": 2, "width": 3, "height": 4},
                }
            ],
            "coverage": [],
            "observations": [
                {
                    "id": "o1",
                    "subject_id": "focus-a",
                    "property": "laterality",
                    "status": "recorded",
                    "basis": "explicit",
                    "value": {"type": "location", "laterality": "right", "original_wording": "vpravo"},
                    "evidence_ids": ["e1"],
                }
            ],
            "issues": [],
        },
    }


def drawing_bundle() -> dict:
    return {
        "extraction": {
            "case_id": "demo",
            "source_path": "Other/preprocessed/demo/drawing.jpg",
            "source_sha256": "b" * 64,
            "timestamp_utc": "2026-10-17T00:00:00+00:00",
            "git_sha": "c" * 40,
            "extractor_version": "drawing_pipeline",
            "schema_version": "drawing-1",
            "model": "gemini-3.8-flash",
            "prompt_sha256": {"drawing": "d" * 64},
            "thresholds": {"runs": 3},
            "alignment": {"median_px": 1.2},
            "runs_completed": {"mid": 3},
            "notes": [],
        },
        "views": [
            {
                "id": "mid",
                "kind": "diagram view",
                "view_type": "axial",
                "level": "mid",
                "panel_region_ref": [0, 0, 100, 100],
                "coordinate_convention": {"origin": "upper-left", "units": "reference px"},
                "orientation": {
                    "status": "recorded",
                    "value": "patient right at x<0",
                    "basis": "explicit",
                    "evidence": ["mid.letter"],
                    "derived_from": [],
                    "review_status": "unreviewed",
                    "certainty": {"extraction": "unassessed", "interpretation": "high"},
                },
                "letters": [],
            }
        ],
        "marks": [
            {
                "id": "mid.m1",
                "view": "mid",
                "kind": "closed outline",
                "runs_found": 3,
                "run_local_ids": ["m1", "m1", "m1"],
                "polygon_ref": [[10, 20], [30, 40], [50, 60]],
                "closed": True,
                "box_ref": [10, 20, 50, 60],
                "text": None,
                "basis": "inferred",
                "sectors_named": [{"zone": "pzpl", "level": "mid", "patient_side": "right"}],
                "sectors_polygon": [
                    {"zone": "pzpl", "level": "mid", "patient_side": "right", "redcap": "pzpl_mid_rs",
                     "px": 400, "share": 0.8}
                ],
                "sectors_cv": [
                    {"zone": "pzpl", "level": "mid", "patient_side": "right", "redcap": "pzpl_mid_rs",
                     "px": 380, "share": 0.76}
                ],
                "cv_regions": ["mid.cv1"],
                "ink_px_under_polygon": 500,
                "patient_side": {"value": "right", "basis": "explicit", "derived_from": ["mid.orientation"]},
                "redcap": ["pzpl_mid_rs"],
                "linked_to": None,
                "review_status": "unreviewed",
                "certainty": {"extraction": "unassessed", "interpretation": "unassessed"},
            },
            {
                "id": "mid.m9",
                "view": "mid",
                "kind": "arrow",
                "runs_found": 1,
                "run_local_ids": [None, None, None],
                "polygon_ref": None,
                "closed": False,
                "box_ref": [1, 2, 3, 4],
                "text": "15 mm",
                "basis": "explicit",
                "sectors_named": [],
                "sectors_polygon": [],
                "sectors_cv": [],
                "cv_regions": [],
                "ink_px_under_polygon": None,
                "patient_side": None,
                "redcap": [],
                "linked_to": {"mark": "mid.m1", "basis": "inferred"},
                "review_status": "unreviewed",
                "certainty": {"extraction": "unassessed", "interpretation": "unassessed"},
            },
        ],
        "cv_regions": [{"id": "mid.cv1", "view": "mid", "px": 900, "box_ref": [1, 2, 3, 4]}],
        "groups": [
            {"id": "g1", "members": ["mid.m1"], "proposed_finding_kind": "tumour",
             "reason": "Synthetic group.", "bilateral": False, "fixed": False,
             "review_status": "unreviewed", "matching_certainty": "unassessed",
             "certainty": {"extraction": "unassessed", "interpretation": "unassessed"}}
        ],
        "standalone": [],
        "not_lesion": [{"mark": "mid.m9", "reason": "Measurement arrow."}],
        "signals": [
            {"kind": "single_source", "observations": ["mid.m1"], "reason": "One run.", "suggestion": "info only"}
        ],
    }


def brain_output(**overrides) -> dict:
    output = {
        "assignments": [{"focus": "focus-a", "marks": ["mid.m1"], "reason": "Same side and level."}],
        "issues": [],
        "confidence": [
            {"focus": "focus-a", "property": "sectors", "level": "high", "reason": "Explicit side and level."}
        ],
    }
    output.update(overrides)
    return output


def gemini_response(output: dict | str) -> dict:
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    return {
        "candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": text}]}}
        ]
    }


class RecordingTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, body: dict) -> dict:
        self.calls.append(body)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def sent_input(body: dict) -> dict:
    text = body["contents"][0]["parts"][0]["text"]
    marker = "Input JSON:\n"
    return json.loads(text.split(marker, 1)[1])


class LlmSuccessTests(unittest.TestCase):
    def test_one_validated_call_records_model_prompt_and_settings(self):
        transport = RecordingTransport(gemini_response(brain_output()))
        result = run_llm(report_bundle(), drawing_bundle(), transport=transport)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["model"], MODEL)
        self.assertEqual(len(result["prompt_sha256"]), 64)
        self.assertTrue(result["settings"])
        self.assertEqual(result["assignments"], brain_output()["assignments"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["confidence"], brain_output()["confidence"])
        self.assertEqual(result["raw"], brain_output())
        self.assertNotIn("error", result)
        self.assertEqual(len(transport.calls), 1)

    def test_request_is_json_only_and_strips_geometry_pixels_and_paths(self):
        transport = RecordingTransport(gemini_response(brain_output()))
        run_llm(report_bundle(), drawing_bundle(), transport=transport)

        body = transport.calls[0]
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("responseJsonSchema", body["generationConfig"])
        serialized = body["contents"][0]["parts"][0]["text"]
        for banned in (
            "polygon_ref", "box_ref", "box_2d", "cv_regions", "ink_px_under_polygon",
            "panel_region_ref", "coordinate_convention", "image_region", "source_path",
            "image_width", "image_height", "words", "px",
        ):
            self.assertNotIn(banned, serialized, banned)

        payload = sent_input(body)
        self.assertEqual([mark["id"] for mark in payload["drawing"]["marks"]], ["mid.m1", "mid.m9"])
        self.assertEqual([group["id"] for group in payload["drawing"]["groups"]], ["g1"])
        self.assertEqual(payload["drawing"]["signals"][0]["kind"], "single_source")
        self.assertEqual(payload["drawing"]["views"][0]["orientation"]["basis"], "explicit")
        self.assertEqual(payload["drawing"]["not_lesion"][0]["mark"], "mid.m9")
        sector = payload["drawing"]["marks"][0]["sectors_polygon"][0]
        self.assertEqual(sector["share"], 0.8)
        self.assertEqual(sector["patient_side"], "right")
        self.assertEqual(sector["redcap"], "pzpl_mid_rs")
        self.assertNotIn("px", sector)
        self.assertNotIn("redcap", payload["drawing"]["marks"][0])

    def test_prompt_hash_covers_the_input(self):
        first = run_llm(report_bundle(), drawing_bundle(),
                        transport=RecordingTransport(gemini_response(brain_output())))
        changed = drawing_bundle()
        changed["marks"][0]["sectors_polygon"][0]["share"] = 0.4
        second = run_llm(report_bundle(), changed,
                         transport=RecordingTransport(gemini_response(brain_output())))
        self.assertNotEqual(first["prompt_sha256"], second["prompt_sha256"])

    def test_parsed_output_from_an_injected_transport_is_accepted(self):
        result = run_llm(report_bundle(), drawing_bundle(),
                         transport=RecordingTransport(brain_output()))
        self.assertEqual(result["status"], "ok")

    def test_serialized_gemini_response_from_an_injected_transport_is_accepted(self):
        result = run_llm(report_bundle(), drawing_bundle(),
                         transport=RecordingTransport(json.dumps(gemini_response(brain_output()))))
        self.assertEqual(result["status"], "ok", result.get("error"))

    def test_inputs_are_not_mutated(self):
        report, drawing = report_bundle(), drawing_bundle()
        before = deepcopy((report, drawing))
        run_llm(report, drawing, transport=RecordingTransport(gemini_response(brain_output())))
        self.assertEqual((report, drawing), before)


class ReferenceValidationTests(unittest.TestCase):
    def test_confidence_accepts_laterality_sectors_and_sector_set(self):
        for property_name in ("laterality", "sectors", "sector_set"):
            with self.subTest(property=property_name):
                output = brain_output(confidence=[
                    {"focus": "focus-a", "property": property_name, "level": "high", "reason": "Known."}
                ])
                result = run_llm(report_bundle(), drawing_bundle(),
                                 transport=RecordingTransport(gemini_response(output)))
                self.assertEqual(result["status"], "ok", result.get("error"))

    def test_confidence_accepts_a_property_observed_on_the_focus(self):
        report = report_bundle()
        report["extraction"]["observations"].append({
            "id": "o2", "subject_id": "focus-a", "property": "recurrence_risk",
            "status": "recorded", "basis": "explicit",
            "value": {"type": "text", "text": "intermediate", "original_wording": "intermediate"},
            "evidence_ids": ["e1"],
        })
        output = brain_output(confidence=[
            {"focus": "focus-a", "property": "recurrence_risk", "level": "medium", "reason": "Text only."}
        ])
        result = run_llm(report, drawing_bundle(), transport=RecordingTransport(gemini_response(output)))
        self.assertEqual(result["status"], "ok", result.get("error"))

    def test_issue_context_accepts_source_ids_qualified_ids_and_sector_codes(self):
        output = brain_output(issues=[{
            "kind": "side_conflict", "severity": "question",
            "context": [
                "focus-a", "o1", "e1", "mid", "g1", "mid.m1", "mid.orientation", "mid.letter",
                "pzpl_mid_rs", "report:focus-a", "report:o1", "report:e1",
                "subject:focus-a", "obs:o1", "evidence:e1", "focus:focus-a",
                "mark:mid.m1", "view:mid", "group:g1", "standalone:mid.m1",
                "sector:pzpl_mid_rs", "redcap:pzpl_mid_rs", "case:demo",
            ],
            "reason": "Synthetic reference check.",
        }])
        result = run_llm(report_bundle(), drawing_bundle(),
                         transport=RecordingTransport(gemini_response(output)))
        self.assertEqual(result["status"], "ok", result.get("error"))

    def test_empty_issue_context_is_allowed(self):
        output = brain_output(issues=[{
            "kind": "other", "severity": "info", "context": [], "reason": "Global note."
        }])
        result = run_llm(report_bundle(), drawing_bundle(),
                         transport=RecordingTransport(gemini_response(output)))
        self.assertEqual(result["status"], "ok", result.get("error"))


class DefaultTransportTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, payload: bytes):
            self.payload = payload

        def read(self) -> bytes:
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def test_default_transport_uses_urllib_and_a_header_key(self):
        payload = json.dumps(gemini_response(brain_output())).encode("utf-8")
        response = self.FakeResponse(payload)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret", "GOOGLE_API_KEY": ""}):
            with patch("urllib.request.urlopen", return_value=response) as opened:
                result = run_llm(report_bundle(), drawing_bundle())
        self.assertEqual(result["status"], "ok", result.get("error"))
        request = opened.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-goog-api-key"], "test-secret")
        self.assertNotIn("test-secret", request.full_url)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(opened.call_args.kwargs["timeout"], 60.0)

    def test_default_transport_redacts_a_key_from_an_error(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret", "GOOGLE_API_KEY": ""}):
            with patch("urllib.request.urlopen", side_effect=RuntimeError("test-secret exploded")):
                result = run_llm(report_bundle(), drawing_bundle())
        self.assertEqual(result["status"], "missing")
        self.assertNotIn("test-secret", result["error"])
        self.assertIn("[redacted]", result["error"])


class LlmValidationTests(unittest.TestCase):
    def assert_missing(self, output, fragment: str = "") -> dict:
        result = run_llm(report_bundle(), drawing_bundle(),
                         transport=RecordingTransport(gemini_response(output)))
        self.assertEqual(result["status"], "missing")
        self.assertTrue(result["error"])
        self.assertIn(fragment, result["error"])
        self.assertEqual(result["assignments"], [])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["confidence"], [])
        self.assertEqual(result["model"], MODEL)
        self.assertEqual(len(result["prompt_sha256"]), 64)
        self.assertTrue(result["settings"])
        return result

    def test_unknown_focus_is_rejected(self):
        output = brain_output(assignments=[{"focus": "focus-z", "marks": ["mid.m1"], "reason": "Guess."}])
        self.assert_missing(output, "unknown focus")

    def test_unknown_mark_is_rejected(self):
        output = brain_output(assignments=[{"focus": "focus-a", "marks": ["mid.m404"], "reason": "Guess."}])
        self.assert_missing(output, "unknown mark")

    def test_not_lesion_mark_is_rejected(self):
        output = brain_output(assignments=[{"focus": "focus-a", "marks": ["mid.m9"], "reason": "Ink."}])
        self.assert_missing(output, "not_lesion")

    def test_a_mark_can_have_only_one_owner(self):
        output = brain_output(assignments=[
            {"focus": "focus-a", "marks": ["mid.m1"], "reason": "First."},
            {"focus": "focus-b", "marks": ["mid.m1"], "reason": "Second."},
        ])
        self.assert_missing(output, "more than one focus")

    def test_focus_cannot_be_assigned_twice(self):
        output = brain_output(assignments=[
            {"focus": "focus-a", "marks": ["mid.m1"], "reason": "First."},
            {"focus": "focus-a", "marks": [], "reason": "Second."},
        ])
        self.assert_missing(output, "focus assigned more than once")

    def test_reason_is_required(self):
        output = brain_output(assignments=[{"focus": "focus-a", "marks": ["mid.m1"], "reason": "  "}])
        self.assert_missing(output, "reason")

    def test_issue_kind_must_be_central_vocabulary(self):
        output = brain_output(issues=[{"kind": "invented_issue", "severity": "question",
                                       "context": ["focus-a"], "reason": "Guess."}])
        self.assert_missing(output, "issue kind")

    def test_issue_severity_must_match_the_kind(self):
        output = brain_output(issues=[{"kind": "side_conflict", "severity": "info",
                                       "context": ["focus-a"], "reason": "Guess."}])
        self.assert_missing(output, "severity")

    def test_confidence_level_is_checked(self):
        output = brain_output(confidence=[{"focus": "focus-a", "property": "sectors",
                                           "level": "certain", "reason": "Guess."}])
        self.assert_missing(output, "confidence level")

    def test_confidence_unknown_focus_is_rejected(self):
        output = brain_output(confidence=[{"focus": "focus-z", "property": "sectors",
                                           "level": "high", "reason": "Guess."}])
        self.assert_missing(output, "unknown focus")

    def test_confidence_property_must_belong_to_the_focus(self):
        output = brain_output(confidence=[{"focus": "focus-a", "property": "invented_property",
                                           "level": "high", "reason": "Guess."}])
        self.assert_missing(output, "unknown property")

    def test_specimen_property_cannot_be_attached_to_a_focus(self):
        output = brain_output(confidence=[{"focus": "focus-a", "property": "classification_pt",
                                           "level": "high", "reason": "Wrong scope."}])
        self.assert_missing(output, "unknown property")

    def test_issue_context_rejects_an_unknown_reference(self):
        output = brain_output(issues=[{"kind": "side_conflict", "severity": "question",
                                       "context": ["focus-a", "invented-id"],
                                       "reason": "Guess."}])
        self.assert_missing(output, "unknown source ID")

    def test_issue_context_rejects_a_bare_word(self):
        output = brain_output(issues=[{"kind": "side_conflict", "severity": "question",
                                       "context": ["right"], "reason": "Guess."}])
        self.assert_missing(output, "unknown source ID")

    def test_issue_context_rejects_an_unknown_lesion_id(self):
        output = brain_output(issues=[{"kind": "side_conflict", "severity": "question",
                                       "context": ["L1"], "reason": "Guess."}])
        self.assert_missing(output, "unknown source ID")

    def test_top_level_keys_are_strict(self):
        output = brain_output(notes="extra")
        self.assert_missing(output, "top-level")

    def test_malformed_json_is_a_missing_brain(self):
        result = self.assert_missing("not json", "JSON")
        self.assertEqual(result["raw"], "not json")

    def test_incomplete_gemini_candidate_is_a_missing_brain(self):
        response = {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}
        result = run_llm(report_bundle(), drawing_bundle(), transport=RecordingTransport(response))
        self.assertEqual(result["status"], "missing")
        self.assertIn("SAFETY", result["error"])

    def test_transport_failure_does_not_escape(self):
        result = run_llm(report_bundle(), drawing_bundle(), transport=RecordingTransport(RuntimeError("offline")))
        self.assertEqual(result["status"], "missing")
        self.assertIn("offline", result["error"])
        self.assertEqual(result["raw"], None)

    def test_missing_key_fails_open_without_a_request(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}):
            result = run_llm(report_bundle(), drawing_bundle())
        self.assertEqual(result["status"], "missing")
        self.assertIn("GEMINI_API_KEY", result["error"])
        self.assertEqual(len(result["prompt_sha256"]), 64)

    def test_brain_metadata_survives_validation_failure(self):
        result = self.assert_missing(brain_output(notes="extra"), "top-level")
        self.assertIn("temperature", result["settings"])


if __name__ == "__main__":
    unittest.main()
