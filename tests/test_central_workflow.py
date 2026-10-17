"""Public workflow checks use synthetic findings and an injected external brain."""

import json
import hashlib
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from central.combine import combine
from central.decisions import Decisions, apply_interpretation_decisions, bind_property_targets, validate_override
from central.output import identify_issues
from central.pipeline import run_case
from central_fixtures import write_case
from central.candidates import build_candidates
from central.lesions import build_interpretation
from central.matching import match


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

    def test_reviewed_codes_use_the_same_property_domains_as_inputs(self):
        for prop, invalid in (("grade_group", "99"), ("histology_type", "0"),
                              ("histology", "99"), ("multifocality", "unknown")):
            with self.subTest(prop=prop), self.assertRaisesRegex(ValueError, "invalid .* code"):
                validate_override(prop, {"value": {"type": "coded", "code": invalid, "original_wording": "review"}})

    def test_reviewer_value_retains_original_source_assessment(self):
        original = {"property": "grade_group", "status": "recorded", "value": {"type": "coded", "code": "2"},
                    "basis": "explicit", "supports": ["report:obs-a"], "opposes": ["report:other"],
                    "candidates": [{"value": {"type": "coded", "code": "4"}, "supports": ["report:other"]}],
                    "confidence": {"final": "high"}}
        result = {"lesions": [{"id": "L1", "focus": "f1", "properties": [original]}], "issues": []}
        entry = decision("set_value", {"lesion": "L1", "property": "grade_group"},
                         {"status": "recorded", "value": {"type": "coded", "code": "3", "original_wording": "review selection"}})
        changed, touched, applied = apply_interpretation_decisions(result, [entry])
        prop = changed["lesions"][0]["properties"][0]
        self.assertEqual(prop["value"]["code"], "3")
        self.assertEqual(prop["source_assessment"]["value"]["code"], "2")
        self.assertEqual(prop["basis"], "inferred")
        self.assertEqual(prop["supports"], ["decision:d1"])
        self.assertEqual(prop["tags"], ["reviewer selection"])
        self.assertEqual(prop["opposes"], [])
        self.assertNotIn("candidates", prop)
        self.assertEqual(prop["source_assessment"]["opposes"], ["report:other"])
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

    def test_reviewed_value_clears_unavailable_source_metadata(self):
        original = {"property": "grade_group", "status": "not reported", "value": None,
                    "basis": "explicit", "supports": [], "opposes": [], "tags": ["single source"],
                    "unavailable_reason": "Not stated", "evidence_ids": [], "derived_from": [],
                    "source_certainty": {"extraction": "high"}, "confidence": {"final": "unassessed"}}
        entry = decision("set_value", {"lesion": "L1", "property": "grade_group"},
                         {"value": {"type": "coded", "code": "3", "original_wording": "review selection"}})
        changed, _, _ = apply_interpretation_decisions({"lesions": [{"id": "L1", "properties": [original]}], "issues": []}, [entry])
        prop = changed["lesions"][0]["properties"][0]
        self.assertEqual(prop["source_assessment"], original)
        for field in ("unavailable_reason", "source_certainty", "evidence_ids", "derived_from"):
            self.assertNotIn(field, prop)


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

    def count_only_report(self):
        report = json.loads(self.report_file.read_text())
        text = "Syntetický vzorek. Dvě ložiska."
        report["text_layer"]["text"] = text
        report["text_layer"]["text_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        report["extraction"]["evidence"][0].update(quotation=text, end_offset=len(text))
        report["extraction"]["subjects"] = report["extraction"]["subjects"][:1]
        for collection in ("observations", "coverage"):
            report["extraction"][collection] = [item for item in report["extraction"][collection] if item["subject_id"] == "specimen"]
        count = next(o for o in report["extraction"]["observations"] if o["property"] == "reported_lesion_count")
        count.update(status="recorded", evidence_ids=["e1"],
                     value={"type": "quantity", "value": 2, "unit": None, "approximate": False, "original_wording": "Dvě ložiska"})
        count.pop("unavailable_reason")
        self.report_file.write_text(json.dumps(report, ensure_ascii=False))

    def test_count_backed_group_retains_every_mark_in_a_hypothesis(self):
        self.count_only_report()
        path = run_case("synthetic-case", root=self.root, use_llm=False)
        combined = json.loads(path.read_text())
        lesion = combined["lesions"][0]
        self.assertNotIn("source_subject", lesion)
        hypothesis = next(h for h in combined["matching"]["hypotheses"] if h["id"] == lesion["hypothesis"])
        self.assertEqual({m["subject"] for m in hypothesis["memberships"]}, {"mid.m1", "base.m1"})
        self.assertIn("report:specimen-reported_lesion_count", hypothesis["supports"])
        self.save_decisions([decision("reject_group", {"group": "g1"})])
        _, reviewed = self.run_pipeline()
        self.assertEqual(reviewed["lesions"][0]["identity_disposition"], "unresolved")
        hypothesis = next(h for h in reviewed["matching"]["hypotheses"] if h["id"] == lesion["hypothesis"])
        self.assertTrue(all(m["review_status"] == "needs_review" for m in hypothesis["memberships"]))

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

    def test_offline_run_records_llm_request_metadata(self):
        path = run_case("synthetic-case", root=self.root, use_llm=False)
        brain = json.loads(path.read_text())["brains"]["llm"]
        self.assertEqual(brain["status"], "missing")
        self.assertEqual(len(brain["prompt_sha256"]), 64)
        self.assertTrue(brain["settings"])
        self.assertEqual(self.calls, [])

    def test_same_case_id_in_another_batch_does_not_establish_pairing(self):
        drawing = json.loads(self.drawing_file.read_text())
        drawing["extraction"]["source_path"] = "Other/preprocessed/another-batch/synthetic-case/drawing.jpg"
        self.drawing_file.write_text(json.dumps(drawing))
        with self.assertRaisesRegex(ValueError, "same supplied preprocess case folder"):
            self.run_pipeline()
        self.assertEqual(self.calls, [])

    def test_full_source_paths_are_compared_before_pairing(self):
        report = json.loads(self.report_file.read_text())
        report["document"]["source_path"] = "/batch-a/Other/preprocessed/synthetic-case/report.jpg"
        report["text_layer"]["source_path"] = report["document"]["source_path"]
        self.report_file.write_text(json.dumps(report))
        drawing = json.loads(self.drawing_file.read_text())
        drawing["extraction"]["source_path"] = "/batch-b/Other/preprocessed/synthetic-case/drawing.jpg"
        self.drawing_file.write_text(json.dumps(drawing))
        with self.assertRaisesRegex(ValueError, "same supplied preprocess case folder"):
            self.run_pipeline()
        self.assertEqual(self.calls, [])

    def test_relative_source_paths_resolve_against_the_supplied_root(self):
        drawing = json.loads(self.drawing_file.read_text())
        drawing["extraction"]["source_path"] = "Other/preprocessed/synthetic-case/drawing.jpg"
        self.drawing_file.write_text(json.dumps(drawing))
        self.run_pipeline()

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
        comparison = next(c for pair in reviewed["matching"]["pair_scores"] if pair["focus"] == "f1"
                          for c in pair["comparisons"] if c["property"] == "level")
        self.assertEqual(comparison["report_ref"], "decision:d2")
        self.assertEqual(comparison["input_observations"][0]["ref"], "decision:d2")
        self.assertEqual(comparison["input_observations"][0]["basis"], "inferred")
        self.assertEqual(comparison["source_report_ref"], "report:f1-level")
        self.assertEqual(len(self.calls), 1)

    def test_empty_followup_decisions_keep_previous_split_assignments(self):
        self.run_pipeline()
        self.save_decisions([decision("reject_membership", {"focus": "f1", "mark": "base.m1"})])
        _, previous = self.run_pipeline()
        self.save_decisions([])
        _, rerun = self.run_pipeline()
        self.assertEqual(rerun["lesions"], previous["lesions"])
        self.assertEqual(rerun["decisions_applied"], previous["decisions_applied"])
        self.assertFalse(any(i["kind"] == "matcher_disagreement" and i["status"] == "open" for i in rerun["issues"]))
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

    def test_group_rejection_preserves_a_prior_direct_membership_decision(self):
        self.run_pipeline()
        self.save_decisions([decision("assign_mark", {"focus": "f1", "mark": "mid.m1"}),
                             decision("reject_group", {"group": "g1"}, ident="d2")])
        _, reviewed = self.run_pipeline()
        hypothesis = next(h for h in reviewed["matching"]["hypotheses"] if h["focus"] == "f1")
        member = next(m for m in hypothesis["memberships"] if m["subject"] == "mid.m1")
        self.assertEqual(member["depends_on"], ["decision:d1"])

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
        resolved = next(i for i in reviewed["issues"] if i["kind"] == "matcher_disagreement")
        self.assertEqual(resolved["resolved_by"], ["d1"])
        self.assertEqual(resolved["decision"]["reviewer"], "synthetic-reviewer")

    def test_resolving_unrelated_issue_keeps_matcher_disagreement_open(self):
        def disagree(body):
            return {"assignments": [], "confidence": [], "issues": [
                {"kind": "other", "severity": "question", "context": ["f1"], "reason": "Separate review question."}]}
        path = run_case("synthetic-case", root=self.root, transport=disagree)
        original = json.loads(path.read_text())
        issue = next(i for i in original["issues"] if i.get("reason") == "Separate review question.")
        self.save_decisions([decision("resolve_issue", {"issue": issue["id"]})])
        _, reviewed = self.run_pipeline()
        self.assertEqual(next(i for i in reviewed["issues"] if i["id"] == issue["id"])["status"], "resolved")
        self.assertTrue(all(i["status"] == "open" for i in reviewed["issues"] if i["kind"] == "matcher_disagreement"))
        self.assertEqual(reviewed["lesions"][0]["identity_certainty"]["level"], "low")

    def test_explicit_resolution_is_retained_when_an_edit_filters_the_llm_issue(self):
        def brain(body):
            result = self.brain(body)
            result["issues"] = [{"kind": "other", "severity": "question", "context": ["f1"], "reason": "Review this detail."}]
            return result
        path = run_case("synthetic-case", root=self.root, transport=brain)
        original = json.loads(path.read_text())
        issue = next(i for i in original["issues"] if i.get("reason") == "Review this detail.")
        self.save_decisions([
            decision("set_value", {"lesion": "L1", "property": "reported_label"},
                     {"value": {"type": "text", "text": "Reviewed", "original_wording": "review"}}),
            decision("resolve_issue", {"issue": issue["id"]}, ident="d2")])
        _, reviewed = self.run_pipeline()
        resolved = next(i for i in reviewed["issues"] if i["id"] == issue["id"])
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["decision"]["id"], "d2")

    def test_bilateral_drawing_conflicts_with_a_unilateral_report_focus(self):
        report = json.loads(self.report_file.read_text())
        drawing = json.loads(self.drawing_file.read_text())
        candidates = build_candidates(drawing)
        candidates[0]["sides"] = ["right", "left"]
        candidates[0]["sectors_in"].append("pzpl_mid_ls")
        matching = match(report, candidates, fixed_assignment={"f1": ["c1"], "f2": ["c2"]})
        comparison = next(c for c in matching["comparisons"] if c["hypothesis"] == "h1" and c["property"] == "laterality")
        self.assertEqual(comparison["score"], -3)
        result = build_interpretation(report, drawing, candidates, matching)
        self.assertTrue(any(i["kind"] == "side_conflict" for i in result["issues"]))
        self.assertEqual(result["lesions"][0]["sectors"]["confidence"]["final"], "conflict")
        laterality = next(p for p in result["lesions"][0]["properties"] if p["property"] == "laterality")
        self.assertEqual(laterality["disposition"], "unresolved")
        self.assertEqual(laterality["candidates"][1]["value"]["laterality"], "bilateral")

    def test_unilateral_drawing_can_depict_part_of_a_bilateral_report_focus(self):
        report = json.loads(self.report_file.read_text())
        next(o for o in report["extraction"]["observations"] if o["id"] == "f1-laterality")["value"]["laterality"] = "bilateral"
        drawing = json.loads(self.drawing_file.read_text())
        candidates = build_candidates(drawing)
        matching = match(report, candidates, fixed_assignment={"f1": ["c1"], "f2": ["c2"]})
        comparison = next(c for c in matching["comparisons"] if c["hypothesis"] == "h1" and c["property"] == "laterality")
        self.assertEqual(comparison["score"], 3)
        self.assertFalse(any(i["kind"] == "side_conflict" for i in build_interpretation(report, drawing, candidates, matching)["issues"]))

    def test_zone_conflict_retains_both_readings_and_lowers_sector_confidence(self):
        report = json.loads(self.report_file.read_text())
        drawing = json.loads(self.drawing_file.read_text())
        candidates = build_candidates(drawing)
        candidates[0]["zones"] = ["tz"]
        candidates[0]["exact_zones"] = ["tzp"]
        candidates[0]["sectors_in"] = ["tzp_mid_rs"]
        matching = match(report, candidates, fixed_assignment={"f1": ["c1"], "f2": ["c2"]})
        result = build_interpretation(report, drawing, candidates, matching)
        prop = next(p for p in result["lesions"][0]["properties"] if p["property"] == "zone")
        self.assertEqual(prop["disposition"], "unresolved")
        self.assertEqual([c["value"]["zones"] for c in prop["candidates"]], [["pz"], ["tzp"]])
        self.assertTrue(any(i["kind"] == "other" and "zone disagree" in i.get("explanation", "") for i in result["issues"]))
        self.assertEqual(result["lesions"][0]["sectors"]["confidence"]["final"], "low")

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

    def test_skipped_decision_never_rebinds_to_a_reused_lesion_number(self):
        self.run_pipeline()
        self.save_decisions([decision("set_value", {"lesion": "L1", "property": "reported_label"},
                                     {"value": {"type": "text", "text": "Old focus", "original_wording": "review"}})])
        report = json.loads(self.report_file.read_text())
        report["extraction"]["subjects"] = [s for s in report["extraction"]["subjects"] if s["id"] != "f1"]
        for name in ("observations", "coverage"):
            report["extraction"][name] = [o for o in report["extraction"][name] if o["subject_id"] != "f1"]
        self.report_file.write_text(json.dumps(report))
        _, changed = self.run_pipeline()
        _, repeated = self.run_pipeline()
        for result in (changed, repeated):
            self.assertEqual(result["lesions"][0]["focus"], "f2")
            self.assertEqual(result["decisions_applied"], [])
            self.assertEqual(result["decisions_history"][0]["target"]["focus"], "f1")
            label = next(p for p in result["lesions"][0]["properties"] if p["property"] == "reported_label")
            self.assertEqual(label["status"], "not reported")
            self.assertNotIn("decision", label)

    def test_old_llm_input_hashes_remain_stale_across_repeated_reruns(self):
        self.run_pipeline()
        self.save_decisions([])
        drawing = json.loads(self.drawing_file.read_text())
        drawing["extraction"]["notes"] = ["New input extraction."]
        self.drawing_file.write_text(json.dumps(drawing))
        _, changed = self.run_pipeline()
        _, repeated = self.run_pipeline()
        self.assertFalse(changed["brains"]["llm"]["input_hashes_match"])
        self.assertFalse(repeated["brains"]["llm"]["input_hashes_match"])
        self.assertNotEqual(repeated["brains"]["llm"]["input_hashes"]["drawing"], repeated["inputs"]["drawing"]["sha256"])
        self.assertTrue(any(i["kind"] == "llm_missing" for i in repeated["issues"]))
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
