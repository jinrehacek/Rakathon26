import unittest

from central.evaluation import score_case


class ProbeTests(unittest.TestCase):
    def case(self):
        pins = {"report": {"sha256": "a" * 64}, "drawing": {"sha256": "b" * 64}}
        labels = {"case_id": "case", "non_expert": True, "inputs": pins,
                  "assignments": [{"focus": "f1", "marks": ["mid.m1"], "sectors": ["pzpl_mid_rs"], "uncertain": False},
                                  {"focus": "f2", "marks": [], "sectors": [], "uncertain": True}]}
        combined = {"case_id": "case", "inputs": pins,
                    "matching": {"hypotheses": [{"focus": "f1", "memberships": [{"subject": "mid.m1", "role": "diagram depiction"}]}]},
                    "lesions": [{"focus": "f1", "sectors": {"in": ["pzpl_mid_rs", "pzpm_mid_rs"]}}],
                    "brains": {"rules": {"issues": [{"kind": "unmatched_focus"}]}, "llm": {"status": "missing"}}}
        drawing = {"views": [], "marks": []}
        return labels, combined, drawing

    def test_uncertain_labels_and_missing_brain_are_not_scored_as_failures(self):
        result = score_case(*self.case())
        self.assertEqual(result["scores"]["rules"]["correct_assignments"], 1)
        self.assertEqual(result["scores"]["rules"]["mean_sector_jaccard"], 0.5)
        self.assertEqual(result["scores"]["rules"]["scored_foci"], 1)
        self.assertEqual(result["scores"]["llm"]["scored_foci"], 0)
        self.assertIsNone(result["scores"]["llm"]["mean_sector_jaccard"])
        self.assertEqual(result["issue_kinds_only_rules"], ["unmatched_focus"])

    def test_labels_with_other_input_hashes_are_rejected(self):
        labels, combined, drawing = self.case()
        labels["inputs"] = {"report": {"sha256": "c" * 64}, "drawing": {"sha256": "b" * 64}}
        with self.assertRaisesRegex(ValueError, "pinned run"):
            score_case(labels, combined, drawing)

    def test_stale_llm_reading_is_excluded_from_scores_and_issue_counts(self):
        labels, combined, drawing = self.case()
        combined["brains"]["llm"] = {
            "status": "ok", "input_hashes_match": False,
            "assignments": [{"focus": "f1", "marks": ["mid.m1"]}],
            "issues": [{"kind": "unmatched_candidate"}, {"kind": "other"}]}

        result = score_case(labels, combined, drawing)

        self.assertFalse(result["scores"]["llm"]["available"])
        self.assertEqual(result["scores"]["llm"]["scored_foci"], 0)
        self.assertIsNone(result["scores"]["llm"]["mean_sector_jaccard"])
        self.assertEqual(result["issue_counts"]["llm"], {})
        self.assertEqual(result["issue_kinds_only_llm"], [])
        self.assertEqual(result["issue_kinds_only_rules"], ["unmatched_focus"])

    def test_reviewed_run_with_decisions_is_refused(self):
        labels, combined, drawing = self.case()
        combined["decisions_applied"] = [{"id": "review-1"}]
        with self.assertRaisesRegex(ValueError, "reviewed runs cannot be scored"):
            score_case(labels, combined, drawing)
