"""Review history and unresolved identity survive otherwise unchanged runs."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from central.candidates import build_candidates
from central.combine import combine
from central.matching import match
from central.pipeline import run_case
from central_fixtures import write_case


class ReviewContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.report_file, self.drawing_file = write_case(self.root)
        self.decisions_file = self.root / "Other/output/combined/synthetic-case/decisions.json"

    def run_case(self):
        return json.loads(run_case("synthetic-case", root=self.root, use_llm=False).read_text())

    def decisions(self, entries):
        self.decisions_file.write_text(json.dumps({"schema_version": "decisions-1", "decisions": entries}))

    def test_empty_rerun_retains_ambiguity_and_explicit_resolution_stays_resolved(self):
        report = json.loads(self.report_file.read_text())
        values = {o["property"]: o["value"] for o in report["extraction"]["observations"]
                  if o["subject_id"] == "f1" and o["property"] in {"laterality", "level", "zone"}}
        for obs in report["extraction"]["observations"]:
            if obs["subject_id"] == "f2" and obs["property"] in values:
                obs["value"] = deepcopy(values[obs["property"]])
        self.report_file.write_text(json.dumps(report))
        original = self.run_case()
        question = next(i for i in original["issues"] if i["kind"] == "ambiguous_assignment")
        self.decisions([])
        repeated = self.run_case()
        self.assertEqual(repeated["matching"]["certainty"], "low")
        retained = next(i for i in repeated["issues"] if i["kind"] == "ambiguous_assignment")
        self.assertEqual(retained, question)
        self.assertEqual(repeated["matching"]["runner_up_assignment"], original["matching"]["runner_up_assignment"])
        self.decisions([{"id": "resolve-1", "kind": "resolve_issue", "target": {"issue": question["id"]},
                         "reviewer": "synthetic-reviewer", "timestamp": "2026-10-17T12:00:00Z",
                         "reason": "Keep the preselected assignment."}])
        resolved = self.run_case()
        self.assertEqual(next(i for i in resolved["issues"] if i["id"] == question["id"])["status"], "resolved")
        self.decisions_file.unlink()  # This test owns its temporary decision file.
        later = self.run_case()
        self.assertEqual(next(i for i in later["issues"] if i["id"] == question["id"])["status"], "resolved")

    def test_removing_decisions_file_preserves_saved_memberships_and_history(self):
        self.run_case()
        self.decisions([{"id": "reject-1", "kind": "reject_membership",
                         "target": {"focus": "f1", "mark": "base.m1"},
                         "reviewer": "synthetic-reviewer", "timestamp": "2026-10-17T12:00:00Z",
                         "reason": "Exclude this depiction."}])
        reviewed = self.run_case()
        self.decisions_file.unlink()
        repeated = self.run_case()
        self.assertEqual(repeated["lesions"], reviewed["lesions"])
        self.assertEqual(repeated["decisions_applied"], reviewed["decisions_applied"])
        self.assertEqual(repeated["decisions_history"], reviewed["decisions_history"])
        self.assertTrue(repeated["brains"]["llm"]["before_decisions"])

    def test_unmatched_focus_does_not_downgrade_explicit_matching_elsewhere(self):
        report = json.loads(self.report_file.read_text())
        drawing = json.loads(self.drawing_file.read_text())
        candidates = [c for c in build_candidates(drawing) if c["source"] == "group:g1"]
        matching = match(report, candidates)
        self.assertEqual(matching["best_assignment"]["f2"], [])
        self.assertGreaterEqual(matching["total_score"] - matching["runner_up_score"], 3)
        self.assertEqual(matching["certainty"], "high")
        self.assertEqual(matching["hypotheses"][0]["certainty"], "high")

    def test_drawing_only_lesion_filtering_is_independent_of_order(self):
        lesions = [{"id": ident, "focus": None, "marks": [mark], "properties": [],
                    "sectors": {"confidence": {"final": "low", "explanations": []}}}
                   for ident, mark in (("L1", "a.m1"), ("L2", "b.m1"))]
        llm = {"status": "ok", "assignments": [], "confidence": [], "issues": [
            {"kind": "other", "severity": "question", "context": ["a.m1"], "reason": "Old L1 opinion."},
            {"kind": "other", "severity": "question", "context": ["b.m1"], "reason": "Keep L2 opinion."}]}
        for ordered in (lesions, list(reversed(lesions))):
            with self.subTest(order=[l["id"] for l in ordered]):
                result, _ = combine({"lesions": ordered, "issues": []}, {"hypotheses": []}, llm, touched={"L1"})
                self.assertEqual([i["reason"] for i in result["issues"]], ["Keep L2 opinion."])


if __name__ == "__main__":
    unittest.main()
