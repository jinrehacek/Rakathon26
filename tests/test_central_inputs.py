"""Contract failures stop a case before matching or external processing."""

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from central.inputs import load_drawing, load_report
from central_fixtures import write_case


class InputContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.report_path, self.drawing_path = write_case(Path(self.temporary.name))

    def write(self, path, data):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_complete_synthetic_contracts_are_preserved(self):
        for path, loader in ((self.report_path, load_report), (self.drawing_path, load_drawing)):
            original = json.loads(path.read_text())
            self.assertEqual(loader(path), original)

    def test_incomplete_or_unversioned_reports_are_refused(self):
        original = json.loads(self.report_path.read_text())
        for field, value in (("complete", False), ("complete", 1), ("output_contract_version", "report-1")):
            with self.subTest(field=field, value=value):
                report = json.loads(json.dumps(original))
                report["extraction"][field] = value
                self.write(self.report_path, report)
                with self.assertRaises(ValueError):
                    load_report(self.report_path)

    def test_recorded_evidence_must_match_codepoint_offsets(self):
        report = json.loads(self.report_path.read_text())
        report["extraction"]["evidence"][0]["end_offset"] -= 1
        self.write(self.report_path, report)
        with self.assertRaisesRegex(ValueError, "code-point offsets"):
            load_report(self.report_path)

    def test_changed_text_with_stale_hash_is_refused(self):
        report = json.loads(self.report_path.read_text())
        report["text_layer"]["text"] += " changed"
        self.write(self.report_path, report)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            load_report(self.report_path)

    def test_omitted_property_cannot_mean_not_reported(self):
        report = json.loads(self.report_path.read_text())
        report["extraction"]["observations"] = report["extraction"]["observations"][1:]
        self.write(self.report_path, report)
        with self.assertRaisesRegex(ValueError, "missing required property"):
            load_report(self.report_path)

    def test_not_reported_needs_a_coverage_check(self):
        report = json.loads(self.report_path.read_text())
        report["extraction"]["coverage"] = report["extraction"]["coverage"][1:]
        self.write(self.report_path, report)
        with self.assertRaisesRegex(ValueError, "complete coverage"):
            load_report(self.report_path)

    def test_location_components_keep_separate_statuses(self):
        report = json.loads(self.report_path.read_text())
        observation = next(o for o in report["extraction"]["observations"] if o["id"] == "f1-laterality")
        observation["value"]["levels"] = ["mid"]
        self.write(self.report_path, report)
        with self.assertRaisesRegex(ValueError, "another property's component"):
            load_report(self.report_path)

    def test_duplicate_property_observations_cannot_create_two_current_assessments(self):
        report = json.loads(self.report_path.read_text())
        duplicate = dict(report["extraction"]["observations"][0], id="duplicate-observation")
        report["extraction"]["observations"].append(duplicate)
        self.write(self.report_path, report)
        with self.assertRaisesRegex(ValueError, "duplicate subject property"):
            load_report(self.report_path)

    def test_nonempty_quarantine_cannot_claim_a_complete_report(self):
        report = json.loads(self.report_path.read_text())
        report["quarantine"] = [{"raw": "unvalidated"}]
        self.write(self.report_path, report)
        with self.assertRaises(ValueError):
            load_report(self.report_path)

    def test_duplicate_json_keys_are_rejected(self):
        self.report_path.write_text('{"extraction":{},"extraction":{}}')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            load_report(self.report_path)

    def test_specimen_gleason_can_reach_the_specimen_grade_consistency_check(self):
        from central.checks import run_checks
        report = json.loads(self.report_path.read_text())
        phrase = " Gleason 3+4=7, GG3."
        start = len(report["text_layer"]["text"])
        report["text_layer"]["text"] += phrase
        report["text_layer"]["text_sha256"] = hashlib.sha256(report["text_layer"]["text"].encode()).hexdigest()
        anchor = dict(report["extraction"]["evidence"][0], id="grade-evidence", quotation=phrase,
                      start_offset=start, end_offset=start + len(phrase))
        report["extraction"]["evidence"].append(anchor)
        grade = next(obs for obs in report["extraction"]["observations"] if obs["id"] == "specimen-grade_group")
        grade.update(status="recorded", value={"type": "coded", "code": "3", "original_wording": "GG3"},
                     evidence_ids=["grade-evidence"])
        grade.pop("unavailable_reason")
        report["extraction"]["observations"].append({**grade, "id": "specimen-score", "property": "gleason_score",
            "value": {"type": "gleason_score", "primary_pattern": 3, "secondary_pattern": 4, "total": 7, "original_wording": "3+4=7"}})
        self.write(self.report_path, report)
        validated = load_report(self.report_path)
        issues = run_checks(validated, [], [])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["rule"]["id"], "isup-grade-group")
        self.assertIn("specimen", issues[0]["context"])

    def test_unknown_drawing_version_is_refused(self):
        drawing = json.loads(self.drawing_path.read_text())
        drawing["extraction"]["schema_version"] = "drawing-2"
        self.write(self.drawing_path, drawing)
        with self.assertRaisesRegex(ValueError, "drawing-1"):
            load_drawing(self.drawing_path)

    def test_missing_group_member_is_refused(self):
        drawing = json.loads(self.drawing_path.read_text())
        drawing["groups"][0]["members"][0] = "mid.gone"
        self.write(self.drawing_path, drawing)
        with self.assertRaisesRegex(ValueError, "missing group mark"):
            load_drawing(self.drawing_path)

    def test_out_of_range_sector_share_is_refused(self):
        drawing = json.loads(self.drawing_path.read_text())
        drawing["marks"][0]["sectors_polygon"][0]["share"] = 1.1
        self.write(self.drawing_path, drawing)
        with self.assertRaisesRegex(ValueError, "invalid sector share"):
            load_drawing(self.drawing_path)

    def test_wrong_side_for_registry_code_is_refused(self):
        drawing = json.loads(self.drawing_path.read_text())
        drawing["marks"][0]["sectors_named"][0]["patient_side"] = "left"
        self.write(self.drawing_path, drawing)
        with self.assertRaisesRegex(ValueError, "sector code side mismatch"):
            load_drawing(self.drawing_path)

    def test_unsided_urethra_choice_accepts_the_drawing_panel_convention(self):
        drawing = json.loads(self.drawing_path.read_text())
        drawing["views"].append(dict(drawing["views"][0], id="urethra", view_type="schematic", level="urethra"))
        drawing["marks"].append({"id": "urethra.m1", "view": "urethra", "kind": "closed outline", "runs_found": 3,
                                 "sectors_named": [{"zone": "urethra", "level": "urethra", "image_side": "midline",
                                                    "patient_side": "midline", "redcap": "urethra"}]})
        drawing["standalone"].append({"mark": "urethra.m1", "reason": "Synthetic urethra mark."})
        self.write(self.drawing_path, drawing)
        self.assertEqual(load_drawing(self.drawing_path)["marks"][-1]["sectors_named"][0]["redcap"], "urethra")
