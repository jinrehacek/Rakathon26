"""Public workflow checks use synthetic findings and an injected external brain."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from central.combine import combine
from central.decisions import Decisions, apply_interpretation_decisions, bind_property_targets
from central.output import identify_issues
from central.pipeline import run_case
from central_fixtures import write_case


def decision(kind, target, value=None, ident="d1"):
    return {"id": ident, "kind": kind, "target": target, "value": value,
            "reviewer": "synthetic-reviewer", "timestamp": "2026-10-17T12:00:00Z",
            "reason": "Synthetic review for a workflow test."}


class CombinationTests(unittest.TestCase):
    def setUp(self):
        self.interpretation = {"lesions": [{"id": "L1", "focus": "focus-a",
                                            "sectors": {"confidence": {"rules": "high", "final": "high", "explanations": ["Explicit side."]}},
                                            "properties": []}], "issues": []}
        self.matching = {"hypotheses": [{"focus": "focus-a", "certainty": "high",
                                          "memberships": [{"subject": "report:focus-a"}, {"subject": "base.m1"}]}]}

    def test_disagreement_keeps_rules_marks_but_lowers_certainty(self):
        llm = {"status": "ok", "assignments": [{"focus": "focus-a", "marks": [], "reason": "No counterpart."}],
               "issues": [], "confidence": []}
        result, matching = combine(self.interpretation, self.matching, llm)
        self.assertEqual(matching["hypotheses"][0]["memberships"][1]["subject"], "base.m1")
        self.assertEqual(matching["hypotheses"][0]["certainty"], "low")
        self.assertEqual(result["issues"][0]["kind"], "matcher_disagreement")
        self.assertEqual(self.matching["hypotheses"][0]["certainty"], "high")

    def test_reviewed_lesion_ignores_stale_llm_disagreement_and_conflict(self):
        llm = {"status": "ok", "assignments": [{"focus": "focus-a", "marks": [], "reason": "Old reading."}],
               "issues": [], "confidence": [{"focus": "focus-a", "property": "sectors", "level": "conflict", "reason": "Old conflict."}]}
        result, matching = combine(self.interpretation, self.matching, llm, touched={"L1"})
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["lesions"][0]["sectors"]["confidence"]["final"], "high")

    def test_llm_failure_leaves_a_reviewable_rules_draft(self):
        result, _ = combine(self.interpretation, self.matching, {"status": "missing", "error": "HTTP unavailable"})
        self.assertEqual(result["lesions"], self.interpretation["lesions"])
        self.assertEqual(result["issues"][0]["kind"], "llm_missing")

    def test_conflict_wins_over_high_confidence(self):
        llm = {"status": "ok", "assignments": [{"focus": "focus-a", "marks": ["base.m1"], "reason": "Matches."}],
               "issues": [], "confidence": [{"focus": "focus-a", "property": "sectors", "level": "conflict", "reason": "Side conflict."}]}
        result, _ = combine(self.interpretation, self.matching, llm)
        self.assertEqual(result["lesions"][0]["sectors"]["confidence"]["final"], "conflict")


class ReviewTests(unittest.TestCase):
    def test_fresh_attempt_binds_old_lesion_number_to_its_source_focus(self):
        previous = {"lesions": [{"id": "L1", "focus": "f1"}, {"id": "L2", "focus": "f2"}]}
        current = {"lesions": [{"id": "L1", "focus": "f2"}, {"id": "L2", "focus": "f1"}]}
        entry = decision("set_value", {"lesion": "L1", "property": "grade_group"}, {})
        rebound, issues = bind_property_targets([entry], current, previous)
        self.assertEqual(rebound[0]["target"], {"lesion": "L2", "focus": "f1", "property": "grade_group"})
        self.assertEqual(issues, [])

    def test_vanished_source_cannot_transfer_its_decision_to_reused_lesion_number(self):
        previous = {"lesions": [{"id": "L1", "focus": "gone"}]}
        current = {"lesions": [{"id": "L1", "focus": "f2"}]}
        entry = decision("set_value", {"lesion": "L1", "property": "grade_group"}, {})
        rebound, issues = bind_property_targets([entry], current, previous)
        self.assertEqual(rebound, [])
        self.assertEqual(issues[0]["severity"], "info")

    def test_decisions_need_reviewer_reason_and_zoned_timestamp(self):
        entry = decision("assign_mark", {"focus": "f1", "mark": "base.m1"})
        entry["timestamp"] = "2026-10-17T12:00:00"
        with self.assertRaises(ValueError):
            Decisions.model_validate({"decisions": [entry]})

    def test_reviewer_value_retains_original_source_assessment(self):
        original = {"property": "grade_group", "status": "recorded", "value": {"type": "coded", "code": "2"},
                    "basis": "explicit", "supports": ["report:obs-a"], "opposes": [], "confidence": {"final": "high"}}
        result = {"lesions": [{"id": "L1", "focus": "f1", "properties": [original]}], "issues": []}
        entry = decision("set_value", {"lesion": "L1", "property": "grade_group"},
                         {"status": "recorded", "value": {"type": "coded", "code": "3", "original_wording": "review selection"}})
        changed, touched, applied = apply_interpretation_decisions(result, [entry])
        prop = changed["lesions"][0]["properties"][0]
        self.assertEqual(prop["value"]["code"], "3")
        self.assertEqual(prop["source_assessment"]["value"]["code"], "2")
        self.assertEqual(result["lesions"][0]["properties"][0], original)
        self.assertEqual(touched, {"L1", "f1"})

    def test_issue_resolution_has_stable_id_and_review_record(self):
        issue = {"kind": "side_conflict", "severity": "question", "context": ["L1"], "reason": "Sides differ."}
        identified = identify_issues([issue])[0]
        entry = decision("resolve_issue", {"issue": identified["id"]})
        result, _, _ = apply_interpretation_decisions({"lesions": [], "issues": [identified]}, [entry])
        self.assertEqual(result["issues"][0]["status"], "resolved")
        self.assertEqual(identify_issues(result["issues"])[0]["id"], identified["id"])
        self.assertEqual(result["issues"][0]["decision"]["reviewer"], "synthetic-reviewer")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.report_file, self.drawing_file = write_case(self.root)
        self.calls = []

    def brain(self, body):
        self.calls.append(body)
        return {"assignments": [{"focus": "f1", "marks": ["mid.m1", "base.m1"], "reason": "Synthetic right focus."},
                                 {"focus": "f2", "marks": ["apex.m1"], "reason": "Synthetic left focus."}],
                "issues": [], "confidence": [{"focus": "f2", "property": "sectors", "level": "medium", "reason": "Synthetic lower confidence."}]}

    def run_pipeline(self):
        path = run_case("synthetic-case", root=self.root, transport=self.brain)
        return path, json.loads(path.read_text())

    def save_decisions(self, entries):
        path = self.root / "Other/output/combined/synthetic-case/decisions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": "decisions-1", "decisions": entries}))

    def test_full_case_pins_inputs_and_writes_new_runs(self):
        first, original = self.run_pipeline()
        second, later = self.run_pipeline()
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())
        self.assertEqual(second.resolve(), (second.parent.parent / "latest/combined.json").resolve())
        self.assertEqual(original["lesions"][0]["sectors"]["in"], ["pzpl_base_rs", "pzpl_mid_rs"])
        self.assertEqual(original["lesions"][1]["sectors"]["confidence"]["final"], "medium")
        self.assertEqual(original["inputs"]["report"]["sha256"], later["inputs"]["report"]["sha256"])
        self.assertEqual(len(self.calls), 2)

    def test_review_splits_group_without_moving_untouched_lesion_or_calling_llm(self):
        first, original = self.run_pipeline()
        self.save_decisions([decision("reject_membership", {"focus": "f1", "mark": "base.m1"})])
        second, reviewed = self.run_pipeline()
        self.assertEqual(reviewed["lesions"][0]["sectors"]["in"], ["pzpl_mid_rs"])
        self.assertEqual(reviewed["lesions"][1], original["lesions"][1])
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(reviewed["brains"]["llm"]["before_decisions"])
        self.assertEqual(reviewed["decisions_applied"][0]["id"], "d1")
        self.assertTrue(first.exists())

    def test_location_edit_recomputes_text_only_sector_proposal(self):
        self.run_pipeline()
        self.save_decisions([
            decision("reject_group", {"group": "g1"}),
            decision("set_value", {"lesion": "L1", "property": "level"},
                     {"status": "recorded", "value": {"type": "location", "levels": ["apex"], "original_wording": "reviewed apex"}}, "d2")])
        _, reviewed = self.run_pipeline()
        self.assertEqual(reviewed["lesions"][0]["sectors"]["in"], ["pza_apex_rs", "pzpl_apex_rs", "pzpm_apex_rs"])
        level = next(p for p in reviewed["lesions"][0]["properties"] if p["property"] == "level")
        self.assertEqual(level["source_assessment"]["value"]["levels"], ["mid"])
        self.assertIn("decision:d2", reviewed["lesions"][0]["sectors"]["supports"])
        self.assertEqual(len(self.calls), 1)

    def test_dominance_edit_keeps_lesion_identity_and_order(self):
        self.run_pipeline()
        self.save_decisions([decision("set_value", {"lesion": "L2", "property": "dominant"},
                                     {"status": "recorded", "value": {"type": "presence", "value": "present", "original_wording": "reviewed dominant"}})])
        _, reviewed = self.run_pipeline()
        self.assertEqual([(lesion["id"], lesion["focus"], lesion["order"]) for lesion in reviewed["lesions"]],
                         [("L1", "f1", 1), ("L2", "f2", 2)])
        prop = next(p for p in reviewed["lesions"][1]["properties"] if p["property"] == "dominant")
        self.assertEqual(prop["value"]["value"], "present")

    def test_sector_override_preserves_proposal_and_records_decision_support(self):
        self.run_pipeline()
        self.save_decisions([decision("set_value", {"lesion": "L1", "property": "sectors"},
                                     {"status": "recorded", "value": {"type": "sectors", "in": ["pzpl_mid_rs"], "maybe": []}})])
        _, reviewed = self.run_pipeline()
        sectors = reviewed["lesions"][0]["sectors"]
        self.assertEqual(sectors["in"], ["pzpl_mid_rs"])
        self.assertEqual(sectors["source_assessment"]["in"], ["pzpl_base_rs", "pzpl_mid_rs"])
        self.assertEqual(sectors["supports"], ["decision:d1"])
        self.assertEqual(sectors["review_status"], "accepted")

    def test_reassignment_after_group_rejection_depends_on_review(self):
        self.run_pipeline()
        self.save_decisions([decision("reject_group", {"group": "g1"}),
                             decision("assign_mark", {"focus": "f1", "mark": "mid.m1"}, ident="d2")])
        _, reviewed = self.run_pipeline()
        hypothesis = next(h for h in reviewed["matching"]["hypotheses"] if h["focus"] == "f1")
        member = next(m for m in hypothesis["memberships"] if m["subject"] == "mid.m1")
        self.assertEqual(member["depends_on"], ["decision:d2"])

    def test_reviewed_target_recovers_rules_certainty_after_llm_disagreement(self):
        def disagree(body):
            return {"assignments": [{"focus": "f2", "marks": ["apex.m1"], "reason": "Other focus unmatched."}],
                    "issues": [], "confidence": []}
        path = run_case("synthetic-case", root=self.root, transport=disagree)
        original = json.loads(path.read_text())
        self.assertEqual(original["lesions"][0]["sectors"]["confidence"]["final"], "low")
        self.save_decisions([decision("set_value", {"lesion": "L1", "property": "reported_label"},
                                     {"status": "recorded", "value": {"type": "text", "text": "A", "original_wording": "review A"}})])
        _, reviewed = self.run_pipeline()
        self.assertEqual(reviewed["lesions"][0]["sectors"]["confidence"]["final"], "high")

    def test_changed_input_invalidates_missing_decision_target(self):
        self.run_pipeline()
        self.save_decisions([decision("assign_mark", {"focus": "gone", "mark": "mid.m1"})])
        drawing = json.loads(self.drawing_file.read_text())
        drawing["extraction"]["notes"] = ["New extraction attempt."]
        self.drawing_file.write_text(json.dumps(drawing))
        _, reviewed = self.run_pipeline()
        self.assertFalse(reviewed["brains"]["llm"]["input_hashes_match"])
        self.assertTrue(any("no longer exists" in i.get("reason", "") for i in reviewed["issues"]))
        self.assertEqual(reviewed["decisions_applied"], [])
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
