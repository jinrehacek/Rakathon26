from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from report_extractor.extractors import (
    ExtractionError,
    ExternalExtractorDisabled,
    FixtureExtractor,
)
from report_extractor.ingest import build_text_layer
from report_extractor.models import (
    COORDINATE_CONVENTION,
    OFFSET_CONVENTION,
    ExtractionProposal,
    TextLayer,
    WordBox,
)
from report_extractor.pipeline import run_extraction
from report_extractor.render import render_text_layer_preview
from report_extractor.validation import validate_payload

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_TEXT = ROOT / "fixtures" / "synthetic_report.txt"
FIXTURE_RESPONSE = ROOT / "fixtures" / "synthetic_response.json"


def text_layer_for(text: str) -> TextLayer:
    source_bytes = text.encode("utf-8")
    digest = hashlib.sha256(source_bytes).hexdigest()
    return TextLayer(
        id=f"layer-{digest[:20]}",
        source_path="/tmp/synthetic.txt",
        source_sha256=digest,
        text_sha256=digest,
        input_kind="text",
        extraction_method="plain_text",
        tool="UTF-8 decoder",
        tool_version="1",
        text=text,
    )


def evidence(layer: TextLayer, evidence_id: str, quote: str) -> dict:
    start = layer.text.index(quote)
    return {
        "id": evidence_id,
        "text_layer_id": layer.id,
        "page": 1,
        "quotation": quote,
        "start_offset": start,
        "end_offset": start + len(quote),
        "offset_convention": OFFSET_CONVENTION,
    }


def subject(
    layer: TextLayer,
    subject_id: str,
    kind: str,
    label: str,
    quote: str,
    parent_id: str | None = None,
) -> tuple[dict, dict]:
    evidence_id = f"e-{subject_id}"
    return (
        {
            "id": subject_id,
            "kind": kind,
            "label": label,
            "identification_basis": "explicit",
            "parent_id": parent_id,
            "evidence_ids": [evidence_id],
        },
        evidence(layer, evidence_id, quote),
    )


def observation(
    observation_id: str,
    subject_id: str,
    property_name: str,
    status: str,
    *,
    basis: str = "explicit",
    value: dict | None = None,
    evidence_ids: list[str] | None = None,
    unavailable_reason: str | None = None,
    derived_from: list[str] | None = None,
) -> dict:
    return {
        "id": observation_id,
        "subject_id": subject_id,
        "property": property_name,
        "status": status,
        "basis": basis,
        "value": value,
        "evidence_ids": evidence_ids or [],
        "derived_from": derived_from or [],
        "review_status": "unreviewed",
        "certainty": {
            "extraction": "unassessed",
            "interpretation": "unassessed",
        },
        "unavailable_reason": unavailable_reason,
    }


def base_payload(layer: TextLayer) -> dict:
    specimen, specimen_evidence = subject(
        layer, "specimen", "specimen", "Preparát", "Preparát."
    )
    focus_a, evidence_a = subject(
        layer, "focus-a", "tumour_focus", "Ložisko A", "Ložisko A", "specimen"
    )
    focus_b, evidence_b = subject(
        layer, "focus-b", "tumour_focus", "Ložisko B", "Ložisko B", "specimen"
    )
    evidence_items = [specimen_evidence, evidence_a, evidence_b]
    return {
        "source_text_sha256": layer.text_sha256,
        "evidence": evidence_items,
        "subjects": [specimen, focus_a, focus_b],
        "coverage": [],
        "observations": [],
        "issues": [],
    }


class IngestionTests(unittest.TestCase):
    def test_plain_text_layer_preserves_text_without_ocr_coordinates(self) -> None:
        text = "Závěr: nádor < 2 mm.\r\n"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "report.txt"
            source.write_bytes(text.encode("utf-8"))
            layer = build_text_layer(source)
        self.assertEqual(layer.text, text)
        self.assertEqual(layer.input_kind, "text")
        self.assertEqual(layer.extraction_method, "plain_text")
        self.assertEqual(layer.words, ())
        self.assertIsNone(layer.language)
        self.assertIsNone(layer.image_width)
        self.assertIsNone(layer.image_height)
        preview = render_text_layer_preview(layer)
        self.assertIn("TEXT INGEST ONLY", preview)
        self.assertIn("no claim of verified OCR accuracy", preview)
        self.assertNotIn("OCR ONLY", preview)
        with self.assertRaises(Exception):
            layer.text = "changed"

    def test_ocr_word_coordinates_anchor_evidence_to_source_image(self) -> None:
        text = "Gleason 3+4=7"
        layer = TextLayer(
            id="ocr-layer",
            source_path="/tmp/source.jpg",
            source_sha256="a" * 64,
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            input_kind="image",
            extraction_method="tesseract",
            tool="Tesseract",
            tool_version="5.3.4",
            language="ces",
            text=text,
            words=(
                WordBox(
                    text=text,
                    start_offset=0,
                    end_offset=len(text),
                    x=12,
                    y=34,
                    width=150,
                    height=22,
                    confidence=91.5,
                ),
            ),
            image_width=200,
            image_height=100,
        )
        payload = {
            "source_text_sha256": layer.text_sha256,
            "evidence": [evidence(layer, "e-score", text)],
            "subjects": [
                {
                    "id": "specimen",
                    "kind": "specimen",
                    "label": "Specimen",
                    "identification_basis": "explicit",
                    "parent_id": None,
                    "evidence_ids": ["e-score"],
                }
            ],
            "coverage": [],
            "observations": [],
            "issues": [],
        }
        result = validate_payload(payload, layer)
        region = result.evidence[0].image_region
        self.assertEqual(
            (region.x, region.y, region.width, region.height), (12, 34, 150, 22)
        )
        self.assertEqual(region.coordinate_convention, COORDINATE_CONVENTION)


class FixturePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.layer = build_text_layer(FIXTURE_TEXT)
        self.fixture = json.loads(FIXTURE_RESPONSE.read_text(encoding="utf-8"))
        self.payload = self.fixture["response"]

    def test_fixture_runs_end_to_end_and_is_prominently_labelled(self) -> None:
        self.assertEqual(self.layer.id, "tl-9cad32159aac464dd8df0be7")
        extractor = FixtureExtractor(FIXTURE_RESPONSE)
        result = validate_payload(extractor.extract(self.layer), self.layer)
        self.assertTrue(result.complete)
        self.assertEqual(len(result.subjects), 3)
        self.assertEqual(len(result.observations), 46)
        self.assertEqual(
            {item.kind for item in result.subjects}, {"specimen", "tumour_focus"}
        )
        focus_a = next(item for item in result.subjects if item.id == "focus-a")
        self.assertEqual(focus_a.parent_id, "specimen-1")
        specimen_dimensions = next(
            item
            for item in result.observations
            if item.id == "specimen-1-lymph_nodes_examined"
        )
        self.assertEqual(specimen_dimensions.status, "not reported")
        self.assertEqual(specimen_dimensions.evidence_ids, ())
        focus_dimensions = next(
            item for item in result.observations if item.id == "obs-focus-a-dimensions"
        )
        self.assertEqual(
            [measurement.axis for measurement in focus_dimensions.value.measurements],
            [None, None],
        )
        self.assertEqual(
            {item.review_status for item in result.observations}, {"unreviewed"}
        )
        negative = next(
            item for item in result.observations if item.id == "obs-r"
        )
        self.assertEqual(negative.value.original_code, "R0")

        with tempfile.TemporaryDirectory() as directory:
            output = run_extraction(self.layer, extractor, directory)
            bundle = json.loads((output / "result.json").read_text())
            html_report = (output / "review.html").read_text()
        self.assertEqual(bundle["extraction"]["mode"], "fixture")
        self.assertTrue(bundle["extraction"]["complete"])
        self.assertIn("FIXTURE MODE", html_report)
        self.assertIn("synthetic response only", html_report)
        self.assertIn("cannot prove that an interpretation", html_report)
        self.assertNotIn("<script", html_report.lower())
        self.assertNotIn("https://", html_report.lower())

    def test_fixture_is_bound_to_exact_text_and_external_mode_is_disabled(self) -> None:
        different = text_layer_for(self.layer.text + "\n")
        with self.assertRaisesRegex(ExtractionError, "different text"):
            FixtureExtractor(FIXTURE_RESPONSE).extract(different)
        with self.assertRaisesRegex(ExtractionError, "No network calls were made"):
            ExternalExtractorDisabled().extract(self.layer)

    def test_response_schema_exposes_required_statuses_and_typed_values(self) -> None:
        schema = ExtractionProposal.model_json_schema()
        statuses = schema["$defs"]["AvailabilityStatus"]["enum"]
        self.assertEqual(
            statuses,
            ["recorded", "not reported", "unreadable", "not assessed", "not applicable"],
        )
        self.assertIn("DimensionsValue", schema["$defs"])
        self.assertEqual(
            schema["$defs"]["PrototypeBasis"]["enum"], ["explicit", "normalized"]
        )
        self.assertEqual(
            schema["$defs"]["ImageRegion"]["properties"]["coordinate_convention"]["const"],
            COORDINATE_CONVENTION,
        )


class ValidationTests(unittest.TestCase):
    def test_conflicts_ambiguous_attribution_and_distinct_unavailable_statuses(self) -> None:
        text = (
            "Preparát. Ložisko A je v levém laloku. "
            "Ložisko B je v pravém laloku. "
            "Ložisko A je v pravém laloku. "
            "Rozměr bez přiřazení je 5 mm. "
            "Nádor na okraji není. "
            "Rozměry: [nečitelné]. "
            "Grade Group nebyla hodnocena. "
            "Gleason skóre se neuplatňuje."
        )
        layer = text_layer_for(text)
        payload = base_payload(layer)
        more_evidence = [
            evidence(layer, "e-location-left", "Ložisko A je v levém laloku."),
            evidence(layer, "e-location-right", "Ložisko A je v pravém laloku."),
            evidence(layer, "e-ambiguous", "Rozměr bez přiřazení je 5 mm."),
            evidence(layer, "e-negative", "Nádor na okraji není."),
            evidence(layer, "e-unreadable", "[nečitelné]"),
            evidence(layer, "e-not-assessed", "Grade Group nebyla hodnocena."),
            evidence(layer, "e-not-applicable", "Gleason skóre se neuplatňuje."),
        ]
        payload["evidence"].extend(more_evidence)
        payload["coverage"] = [
            {
                "id": "coverage-unreported",
                "subject_id": "specimen",
                "property": "classification_l",
                "checked": True,
                "source_complete": True,
                "rationale": "The complete report was checked for this token.",
            },
            {
                "id": "coverage-unchecked",
                "subject_id": "specimen",
                "property": "dimensions",
                "checked": False,
                "source_complete": False,
                "rationale": "This property was not checked.",
            },
        ]
        payload["observations"] = [
            observation(
                "absent",
                "specimen",
                "presence",
                "recorded",
                value={
                    "type": "presence",
                    "value": "absent",
                    "original_wording": "Nádor na okraji není.",
                },
                evidence_ids=["e-negative"],
            ),
            observation(
                "not-reported",
                "specimen",
                "classification_l",
                "not reported",
                unavailable_reason="Complete coverage check found no L token.",
            ),
            observation(
                "unreadable",
                "specimen",
                "dimensions",
                "unreadable",
                evidence_ids=["e-unreadable"],
                unavailable_reason="The stated dimensions are unreadable.",
            ),
            observation(
                "not-assessed",
                "specimen",
                "grade_group",
                "not assessed",
                evidence_ids=["e-not-assessed"],
                unavailable_reason="The source explicitly says this was not assessed.",
            ),
            observation(
                "not-applicable",
                "specimen",
                "gleason_score",
                "not applicable",
                evidence_ids=["e-not-applicable"],
                unavailable_reason="The source explicitly says this does not apply.",
            ),
            observation(
                "unchecked-as-omission",
                "specimen",
                "dimensions",
                "not reported",
                unavailable_reason="Incorrectly treats unchecked coverage as omission.",
            ),
            observation(
                "left-location",
                "focus-a",
                "textual_location",
                "recorded",
                value={
                    "type": "location",
                    "description": "levý lalok",
                    "original_wording": "Ložisko A je v levém laloku.",
                },
                evidence_ids=["e-location-left"],
            ),
            observation(
                "right-location-conflict",
                "focus-a",
                "textual_location",
                "recorded",
                value={
                    "type": "location",
                    "description": "pravý lalok",
                    "original_wording": "Ložisko A je v pravém laloku.",
                },
                evidence_ids=["e-location-right"],
            ),
        ]
        payload["issues"] = [
            {
                "id": "unresolved-size",
                "kind": "unresolved_attribution",
                "summary": "The passage does not identify which focus has this size.",
                "evidence_ids": ["e-ambiguous"],
                "alternative_subject_ids": ["focus-a", "focus-b"],
            }
        ]

        result = validate_payload(payload, layer)
        self.assertEqual(
            {item.id for item in result.observations},
            {
                "absent",
                "not-reported",
                "unreadable",
                "not-assessed",
                "not-applicable",
                "left-location",
                "right-location-conflict",
            },
        )
        self.assertEqual(len(result.issues), 1)
        self.assertFalse(result.complete)
        quarantined = next(
            item
            for item in result.quarantine
            if item.item_id == "unchecked-as-omission"
        )
        self.assertIn("coverage", " ".join(quarantined.reasons))
        self.assertEqual(
            [
                item.value.description
                for item in result.observations
                if item.property == "textual_location"
            ],
            ["levý lalok", "pravý lalok"],
        )
        self.assertFalse(
            any(
                item.property == "dimensions" and item.status == "not reported"
                for item in result.observations
            )
        )

    def test_bad_status_evidence_and_dangling_references_are_quarantined_partially(self) -> None:
        layer = text_layer_for("Preparát. Ložisko A. Ložisko B. Gleason 3+4=7.")
        payload = base_payload(layer)
        payload["evidence"].append(evidence(layer, "e-score", "Gleason 3+4=7"))
        payload["observations"] = [
            observation(
                "valid-score",
                "focus-a",
                "gleason_score",
                "recorded",
                value={
                    "type": "gleason_score",
                    "primary_pattern": 3,
                    "secondary_pattern": 4,
                    "total": 7,
                    "original_wording": "Gleason 3+4=7",
                },
                evidence_ids=["e-score"],
            ),
            observation("bad-recorded-without-value", "focus-a", "dimensions", "recorded"),
            observation(
                "dangling-subject",
                "missing",
                "gleason_score",
                "recorded",
                value={
                    "type": "gleason_score",
                    "primary_pattern": 3,
                    "secondary_pattern": 4,
                    "total": 7,
                    "original_wording": "Gleason 3+4=7",
                },
                evidence_ids=["e-score"],
            ),
            observation(
                "dangling-evidence",
                "focus-a",
                "gleason_score",
                "recorded",
                value={
                    "type": "gleason_score",
                    "primary_pattern": 3,
                    "secondary_pattern": 4,
                    "total": 7,
                    "original_wording": "Gleason 3+4=7",
                },
                evidence_ids=["no-such-evidence"],
            ),
        ]
        mismatched = evidence(layer, "e-mismatch", "Gleason 3+4=7")
        mismatched["start_offset"] += 1
        payload["evidence"].append(mismatched)

        result = validate_payload(payload, layer)
        self.assertEqual([item.id for item in result.observations], ["valid-score"])
        self.assertIn(
            "e-mismatch",
            {item.item_id for item in result.quarantine if item.item_type == "evidence"},
        )
        self.assertEqual(len(result.quarantine), 4)
        self.assertFalse(result.complete)

    def test_dependency_quarantine_cycles_and_partial_retention(self) -> None:
        layer = text_layer_for("Preparát. Ložisko A. Ložisko B.")
        payload = base_payload(layer)
        payload["observations"] = [
            observation(
                "valid",
                "focus-a",
                "presence",
                "recorded",
                value={
                    "type": "presence",
                    "value": "present",
                    "original_wording": "Ložisko A.",
                },
                evidence_ids=["e-focus-a"],
            ),
            observation(
                "cycle-a",
                "focus-a",
                "presence",
                "recorded",
                value={
                    "type": "presence",
                    "value": "present",
                    "original_wording": "Ložisko A.",
                },
                evidence_ids=["e-focus-a"],
                derived_from=["cycle-b"],
            ),
            observation(
                "cycle-b",
                "focus-b",
                "presence",
                "recorded",
                value={
                    "type": "presence",
                    "value": "present",
                    "original_wording": "Ložisko B.",
                },
                evidence_ids=["e-focus-b"],
                derived_from=["cycle-a"],
            ),
            observation(
                "dependent",
                "focus-b",
                "presence",
                "recorded",
                value={
                    "type": "presence",
                    "value": "present",
                    "original_wording": "Ložisko B.",
                },
                evidence_ids=["e-focus-b"],
                derived_from=["cycle-a"],
            ),
        ]
        result = validate_payload(payload, layer)
        self.assertEqual([item.id for item in result.observations], ["valid"])
        reasons = {
            item.item_id: " ".join(item.reasons)
            for item in result.quarantine
            if item.item_type == "observation"
        }
        self.assertIn("cycle", reasons["cycle-a"])
        self.assertIn("cycle", reasons["cycle-b"])
        self.assertIn("depends on an invalid", reasons["dependent"])

    def test_unanchored_and_whole_payload_corruption_are_reported(self) -> None:
        layer = text_layer_for("Preparát.")
        result = validate_payload({"source_text_sha256": "wrong"}, layer)
        self.assertFalse(result.complete)
        self.assertIn("Whole-payload corruption", result.errors[0])
        self.assertEqual(result.quarantine[0].item_type, "payload")

    def test_late_subject_invalidation_quarantines_all_references(self) -> None:
        layer = text_layer_for("Preparát. Ložisko A. Ložisko B.")
        payload = base_payload(layer)
        payload["subjects"][0], payload["subjects"][2] = (
            payload["subjects"][2],
            payload["subjects"][0],
        )
        payload["subjects"][2]["evidence_ids"] = ["missing-specimen-evidence"]
        payload["coverage"] = [
            {
                "id": "coverage-focus-a",
                "subject_id": "focus-a",
                "property": "dimensions",
                "checked": True,
                "source_complete": True,
                "rationale": "Coverage for the focus.",
            }
        ]
        payload["issues"] = [
            {
                "id": "issue-focus-attribution",
                "kind": "unresolved_attribution",
                "summary": "The passage might describe either focus.",
                "evidence_ids": ["e-focus-a"],
                "alternative_subject_ids": ["focus-a", "focus-b"],
            }
        ]

        result = validate_payload(payload, layer)
        self.assertEqual(result.subjects, [])
        self.assertEqual(result.coverage, [])
        self.assertEqual(result.issues, [])
        quarantine = {
            (item.item_type, item.item_id): " ".join(item.reasons)
            for item in result.quarantine
        }
        self.assertIn(
            "depends on a missing or quarantined subject",
            quarantine[("coverage", "coverage-focus-a")],
        )
        self.assertIn(
            "depends on a missing or quarantined alternative subject",
            quarantine[("issue", "issue-focus-attribution")],
        )

    def test_unpaired_surrogate_is_quarantined_and_serialized_safely(self) -> None:
        layer = text_layer_for("Preparát. Ložisko A. Ložisko B.")
        payload = base_payload(layer)
        payload["coverage"] = [
            {
                "id": "invalid-unicode",
                "subject_id": "specimen",
                "property": "dimensions",
                "checked": False,
                "source_complete": False,
                "rationale": "\ud800",
            }
        ]
        fixture = {
            "mode": "fixture",
            "prompt_version": "report-extraction-v2",
            "output_contract_version": "report-3",
            "for_text_sha256": layer.text_sha256,
            "response": payload,
        }
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "response.json"
            fixture_path.write_text(json.dumps(fixture, ensure_ascii=True))
            output = run_extraction(
                layer, FixtureExtractor(fixture_path), Path(directory) / "out"
            )
            serialized = (output / "result.json").read_text(encoding="utf-8")
            bundle = json.loads(serialized)
            html_report = (output / "review.html").read_text(encoding="utf-8")
        self.assertIn("\\ud800", serialized)
        self.assertEqual(
            bundle["quarantine"][0]["raw"]["rationale"], "\ud800"
        )
        self.assertIn("unpaired Unicode surrogate", " ".join(
            bundle["quarantine"][0]["reasons"]
        ))
        self.assertIn("INCOMPLETE", html_report)

    def test_html_escapes_source_and_model_text(self) -> None:
        text = "Preparát. Ložisko A. Ložisko B. <script>alert('x')</script>"
        layer = text_layer_for(text)
        payload = base_payload(layer)
        payload["evidence"] = [evidence(layer, "unsafe-quote", "<script>alert('x')</script>")]
        payload["subjects"][0]["evidence_ids"] = ["unsafe-quote"]
        payload["subjects"] = payload["subjects"][:1]
        result = validate_payload(payload, layer)
        self.assertEqual(len(result.subjects), 1)
        with tempfile.TemporaryDirectory() as directory:
            # Rendering is exercised through the full pipeline using the fixture contract.
            fixture = {
                "mode": "fixture",
                "prompt_version": "report-extraction-v2",
                "output_contract_version": "report-3",
                "for_text_sha256": layer.text_sha256,
                "response": payload,
            }
            path = Path(directory) / "response.json"
            path.write_text(json.dumps(fixture), encoding="utf-8")
            output = run_extraction(layer, FixtureExtractor(path), Path(directory) / "out")
            html_report = (output / "review.html").read_text(encoding="utf-8")
        self.assertNotIn("<script", html_report.lower())
        self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", html_report)
        self.assertNotIn("https://", html_report.lower())


if __name__ == "__main__":
    unittest.main()
