import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "prepare_showcase", Path(__file__).resolve().parents[1] / "prepare_showcase.py"
)
showcase = importlib.util.module_from_spec(spec)
spec.loader.exec_module(showcase)


class ShowcaseTests(unittest.TestCase):
    def dictionary(self, root, case_id="case-1"):
        dictionary = root / "dictionary.json"
        dictionary.write_text(json.dumps({
            "SYNTHETIC-ORIGINAL-ID": {
                "case_id": case_id,
                "sources": [{
                    "role": role, "id": "SYNTHETIC-ORIGINAL-ID", "confident": True,
                    "sha256": "a" * 64,
                    "candidates": [{"id": "SYNTHETIC-ORIGINAL-ID", "quote": "SYNTHETIC-ORIGINAL-ID",
                                    "basis": "explicit", "box": [1, 2, 10, 20]}],
                } for role in ("report", "drawing")],
            },
            "UNRELATED-PRIVATE-ID": {"case_id": "other-case", "sources": []},
        }))
        return dictionary

    def test_restore_only_matching_identity_and_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pair, analysis, text, _ = self.inputs(root)
            output = root / "local"
            result = type("Result", (), {"returncode": 0, "stdout": b""})()
            with patch.object(showcase.subprocess, "run", return_value=result):
                config = showcase.prepare(pair, analysis, text, output, dictionary=self.dictionary(root))
            identity = config["sourceIdentity"]
            self.assertEqual(identity["originalId"], "SYNTHETIC-ORIGINAL-ID")
            self.assertEqual(identity["sourceCaseId"], pair.name)
            self.assertEqual(identity["basis"], "explicit")
            self.assertEqual(len(identity["evidence"]), 2)
            self.assertNotIn("UNRELATED-PRIVATE-ID", (output / "case.json").read_text())
            self.assertNotIn("recordId", config)
            self.assertEqual(config["sourceBinding"], "showcase-unlinked")

    def test_identity_disagreement_missing_or_ambiguous_mapping_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.dictionary(root)
            original = json.loads(path.read_text())
            for variant in ("missing", "duplicate", "disagreement", "unconfident", "no-evidence"):
                data = json.loads(json.dumps(original))
                entry = data["SYNTHETIC-ORIGINAL-ID"]
                if variant == "missing":
                    entry["case_id"] = "unknown"
                elif variant == "duplicate":
                    data["DUPLICATE-ID"] = entry
                elif variant == "disagreement":
                    entry["sources"][0]["id"] = "DIFFERENT"
                elif variant == "unconfident":
                    entry["sources"][0]["confident"] = False
                else:
                    entry["sources"][0]["candidates"] = []
                path.write_text(json.dumps(data))
                with self.subTest(variant=variant), self.assertRaises(ValueError):
                    showcase.source_identity(path, "case-1")

    def inputs(self, root):
        pair = root / "batch" / "case-1"
        pair.mkdir(parents=True)
        sources = {}
        for role in ("report", "drawing"):
            sources[role] = b"\xff\xd8\xffsynthetic-image-" + role.encode()
            (pair / f"{role}.jpg").write_bytes(sources[role])
        (pair.parent / "manifest.json").write_text(json.dumps({
            "data_scope": "artificial",
            "cases": {"case-1": {role: f"case-1/{role}.jpg" for role in sources}},
        }))
        text = root / "report.txt"
        text.write_bytes(b"Synthetic report.\n")
        analysis = root / "analysis.json"
        analysis.write_text(json.dumps({
            "mode": "fixture", "for_text_sha256": hashlib.sha256(text.read_bytes()).hexdigest(),
            "response": {},
        }))
        return pair, analysis, text, sources

    def test_copy_is_explicitly_unlinked_and_originals_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pair, analysis, text, sources = self.inputs(root)
            output = root / "local"
            result = type("Result", (), {"returncode": 0, "stdout": b""})()
            with patch.object(showcase.subprocess, "run", return_value=result):
                config = showcase.prepare(pair, analysis, text, output)
            self.assertEqual(config["sourceBinding"], "showcase-unlinked")
            self.assertEqual(config["mode"], "showcase")
            for role, data in sources.items():
                self.assertEqual((output / f"{role}.jpg").read_bytes(), data)
                self.assertEqual((pair / f"{role}.jpg").read_bytes(), data)
            self.assertEqual((output / "analysis.json").read_bytes(), analysis.read_bytes())
            self.assertEqual(set(path.name for path in output.iterdir()), {
                "report.jpg", "drawing.jpg", "analysis.json", "analysis-report.txt", "case.json",
            })

    def test_unmatched_pair_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pair, analysis, text, _ = self.inputs(root)
            (pair.parent / "manifest.json").write_text('{"data_scope":"artificial","cases":{}}')
            with self.assertRaisesRegex(ValueError, "paired case"):
                showcase.prepare(pair, analysis, text, root / "local")
            self.assertFalse((root / "local").exists())

    def test_hash_mismatch_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pair, analysis, text, _ = self.inputs(root)
            text.write_text("Changed synthetic text.")
            with self.assertRaisesRegex(ValueError, "hash"):
                showcase.prepare(pair, analysis, text, root / "local")
            self.assertFalse((root / "local").exists())

    def test_unignored_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pair, analysis, text, _ = self.inputs(root)
            result = type("Result", (), {"returncode": 1, "stdout": b""})()
            with patch.object(showcase.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(ValueError, "ignored"):
                    showcase.prepare(pair, analysis, text, root / "local")
            self.assertFalse((root / "local").exists())

    def test_complete_prefilled_fixture_is_copied_without_external_assignments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pair, _, _, sources = self.inputs(root)
            analysis = showcase.HERE / "fixtures/prefilled-analysis.json"
            text = showcase.HERE / "fixtures/prefilled-report.txt"
            output = root / "local"
            result = type("Result", (), {"returncode": 0, "stdout": b""})()
            with patch.object(showcase.subprocess, "run", return_value=result):
                config = showcase.prepare(pair, analysis, text, output)
            self.assertNotIn("demoAssignments", config)
            copied = json.loads((output / "analysis.json").read_text())
            self.assertEqual(copied["schema_version"], "doctor-review-showcase-v1")
            self.assertEqual(copied["mode"], "synthetic")
            self.assertEqual(len(copied["lesions"]), 2)
            self.assertTrue(all(len(lesion["fields"]) == 12 for lesion in copied["lesions"]))
            self.assertEqual((output / "analysis.json").read_bytes(), analysis.read_bytes())
            self.assertEqual((output / "analysis-report.txt").read_bytes(), text.read_bytes())
            self.assertEqual(config["sourceBinding"], "showcase-unlinked")
            for role, data in sources.items():
                self.assertEqual((pair / f"{role}.jpg").read_bytes(), data)

    def test_prefilled_hash_mismatch_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pair, _, text, _ = self.inputs(root)
            analysis = showcase.HERE / "fixtures/prefilled-analysis.json"
            with self.assertRaisesRegex(ValueError, "hash"):
                showcase.prepare(pair, analysis, text, root / "local")
            self.assertFalse((root / "local").exists())

    def test_unknown_synthetic_contract_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pair, analysis, text, _ = self.inputs(root)
            analysis.write_text(json.dumps({
                "mode": "synthetic", "schema_version": "unsupported",
                "report_sha256": hashlib.sha256(text.read_bytes()).hexdigest(),
                "lesions": [{"id": "synthetic-focus"}],
            }))
            with self.assertRaisesRegex(ValueError, "supported"):
                showcase.prepare(pair, analysis, text, root / "local")
            self.assertFalse((root / "local").exists())
