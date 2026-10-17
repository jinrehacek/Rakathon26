"""Regression checks through the public combination function, using synthetic targets."""

import unittest
from copy import deepcopy

from central.combine import combine


class CombineRegressionTests(unittest.TestCase):
    def setUp(self):
        self.interpretation = {"lesions": [], "issues": []}
        self.matching = {"hypotheses": []}
        self.llm = {"status": "ok", "assignments": [], "issues": [], "confidence": []}
        for suffix in ("a", "b"):
            focus, mark = "focus-" + suffix, "base.m" + suffix
            self.interpretation["lesions"].append({
                "id": "lesion-" + suffix, "focus": focus, "marks": [mark],
                "identity_certainty": {"level": "high", "explanation": "Explicit matching."},
                "sectors": {"in": ["pzpl_base_rs"], "supports": [mark], "confidence": {
                    "rules": "high", "final": "high", "explanations": ["Rules support the sectors."]}},
                "properties": [],
            })
            self.matching["hypotheses"].append({
                "focus": focus, "certainty": "high", "memberships": [
                    {"subject": focus, "certainty": "high"},
                    {"subject": mark, "certainty": "high", "depends_on": ["group:" + suffix]},
                ],
            })
            self.llm["assignments"].append({"focus": focus, "marks": [mark]})

    def opinion(self, focus="focus-a", level="high", prop="sectors"):
        self.llm["confidence"].append({
            "focus": focus, "property": prop, "level": level, "reason": "Synthetic LLM reading."})

    def test_disagreement_caps_later_high_opinion_without_changing_source_or_rules_assignment(self):
        self.llm["assignments"][0]["marks"] = []
        self.opinion()
        original_interpretation = deepcopy(self.interpretation)
        original_matching = deepcopy(self.matching)

        result, matching = combine(self.interpretation, self.matching, self.llm)

        sectors = result["lesions"][0]["sectors"]
        self.assertEqual(sectors["confidence"]["final"], "low")
        self.assertEqual(sectors["confidence"]["rules"], "high")
        self.assertEqual(sectors["confidence"]["llm"], "high")
        self.assertEqual(sectors["confidence"]["explanations"], [
            "Rules support the sectors.", "Synthetic LLM reading.", "The two matchers disagree."])
        self.assertEqual(sectors["in"], original_interpretation["lesions"][0]["sectors"]["in"])
        self.assertEqual(sectors["supports"], ["base.ma"])
        self.assertEqual(matching["hypotheses"][0]["memberships"][1]["subject"], "base.ma")
        self.assertEqual(result["issues"][0]["kind"], "matcher_disagreement")
        self.assertEqual(result["lesions"][1], original_interpretation["lesions"][1])
        self.assertEqual(self.interpretation, original_interpretation)
        self.assertEqual(self.matching, original_matching)

    def test_identity_and_all_memberships_follow_disagreement(self):
        self.llm["assignments"][0]["marks"] = []
        result, matching = combine(self.interpretation, self.matching, self.llm)

        self.assertEqual(result["lesions"][0]["identity_certainty"], {
            "level": "low", "explanation": "The two matchers disagree."})
        hypothesis = matching["hypotheses"][0]
        self.assertEqual(hypothesis["certainty"], "low")
        self.assertTrue(all(member["certainty"] == "low" for member in hypothesis["memberships"]))
        self.assertEqual(matching["hypotheses"][1], self.matching["hypotheses"][1])
        self.assertNotIn("llm", result["lesions"][0]["sectors"]["confidence"])

    def test_review_drops_removed_mark_issue_and_keeps_untouched_llm_opinions(self):
        self.llm["assignments"][0]["marks"] = ["base.removed"]
        self.llm["issues"] = [
            {"kind": "other", "context": ["base.removed"], "reason": "Stale mark issue."},
            {"kind": "other", "context": ["base.mb"], "reason": "Untouched mark issue."},
        ]
        self.opinion(level="conflict")
        self.opinion(focus="focus-b", level="medium")
        result, matching = combine(self.interpretation, self.matching, self.llm,
                                   touched={"focus-a", "lesion-a", "base.removed"})

        self.assertEqual([issue["context"] for issue in result["issues"]], [["base.mb"]])
        self.assertEqual(result["issues"][0]["raised_by"], ["llm"])
        self.assertEqual(result["lesions"][0], self.interpretation["lesions"][0])
        self.assertEqual(result["lesions"][1]["sectors"]["confidence"]["final"], "medium")
        self.assertEqual(matching, self.matching)

    def test_explicit_touched_mark_suppresses_related_stale_assignment_and_confidence(self):
        for touched_mark in ("base.ma", "base.removed"):
            with self.subTest(mark=touched_mark):
                self.llm["assignments"][0]["marks"] = ["base.removed"]
                self.llm["confidence"] = []
                self.opinion(level="conflict")
                result, matching = combine(self.interpretation, self.matching, self.llm,
                                           touched={touched_mark})
                self.assertEqual(result, self.interpretation)
                self.assertEqual(matching, self.matching)

    def test_conflict_from_either_brain_wins_over_disagreement_cap(self):
        self.llm["assignments"][0]["marks"] = []
        for rules, llm in (("conflict", "high"), ("high", "conflict")):
            with self.subTest(rules=rules, llm=llm):
                confidence = self.interpretation["lesions"][0]["sectors"]["confidence"]
                confidence.update(rules=rules, final=rules)
                self.llm["confidence"] = []
                self.opinion(level=llm)
                result, _ = combine(self.interpretation, self.matching, self.llm)
                combined = result["lesions"][0]["sectors"]["confidence"]
                self.assertEqual(combined["final"], "conflict")
                self.assertEqual(combined["rules"], rules)
                self.assertEqual(combined["llm"], llm)


if __name__ == "__main__":
    unittest.main()
