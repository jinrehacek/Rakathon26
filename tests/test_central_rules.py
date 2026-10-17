"""Synthetic rule checks; these are not accuracy measurements on patient scans."""
from __future__ import annotations

import copy
import itertools
import unittest

from central.candidates import build_candidates
from central.confidence import matching_confidence
from central.lesions import build_interpretation
from central.matching import match, pair_score


def report(*focus_ids):
    return {"extraction": {"subjects": [{"id": "spec", "kind": "specimen"}] +
                            [{"id": fid, "kind": "tumour_focus"} for fid in focus_ids],
                            "observations": [], "issues": []}}


def obs(data, sid, prop, value=None, status="recorded"):
    entry = {"id": f"{sid}-{prop}", "subject_id": sid, "property": prop,
             "status": status, "basis": "explicit", "evidence_ids": ["ev1"] if value is not None else [],
             "certainty": {"extraction": "high", "interpretation": "high"}}
    if value is not None:
        entry["value"] = value
    else:
        entry["unavailable_reason"] = "Checked without a usable value."
    data["extraction"]["observations"].append(entry)
    return entry


def locate(data, sid, side="left", levels=("mid",), zones=("pz",), ap="posterior"):
    for prop, key, value in (("laterality", "laterality", side), ("level", "levels", list(levels)),
                             ("zone", "zones", list(zones)), ("anteroposterior", "anteroposterior", ap)):
        if value:
            obs(data, sid, prop, {"type": "location", key: value})


def sector(zone="pzpl", level="mid", side="left", share=1):
    return {"zone": zone, "level": level, "patient_side": side, "image_side": "right",
            "redcap": f"{zone}_{level}_{'ls' if side == 'left' else 'rs'}", "share": share, "px": 10}


def mark(mid="mid.m1", side="left", zone="pzpl", level="mid"):
    return {"id": mid, "view": mid.split(".")[0], "kind": "closed outline", "runs_found": 3,
            "sectors_named": [], "sectors_polygon": [sector(zone, level, side)], "sectors_cv": [],
            "cv_regions": [], "redcap": ["unfiltered_code"]}


def drawing(*marks):
    return {"extraction": {"thresholds": {"share": 0.99}}, "marks": list(marks),
            "views": [{"id": view, "view_type": "longitudinal" if view in {"coronal", "sagittal"} else "cross-sectional",
                       "orientation": {"basis": "explicit"}} for view in dict.fromkeys(m["view"] for m in marks)],
            "groups": [], "standalone": [{"mark": m["id"], "reason": "synthetic"} for m in marks],
            "not_lesion": [], "signals": [], "cv_regions": []}


def interpret(r, d, fixed=None, previous=None):
    candidates = build_candidates(d)
    matching = match(r, candidates, fixed_assignment=fixed, previous_matching=previous)
    return build_interpretation(r, d, candidates, matching), matching


class CandidateTests(unittest.TestCase):
    def test_sector_threshold_named_or_and_cv_maybe(self):
        m = mark()
        m["sectors_polygon"] = [sector(share=.15), sector("pza", share=.1499)]
        m["sectors_cv"] = [sector("tzp", share=1)]
        m["sectors_named"] = [sector("cz", share=0)]
        result = build_candidates(drawing(m))[0]
        self.assertEqual(result["sectors_in"], ["cz_mid_ls", "pzpl_mid_ls"])
        self.assertEqual(result["sectors_maybe"], ["pza_mid_ls", "tzp_mid_ls"])
        self.assertNotIn("unfiltered_code", result["sectors_in"])

    def test_longitudinal_levels_and_group_dependencies(self):
        d = drawing(mark(), mark("coronal.m1", level="apex"))
        d["groups"] = [{"id": "g1", "members": ["mid.m1", "coronal.m1"]}]
        d["standalone"] = []
        d["views"][0]["orientation"]["basis"] = "inferred"
        candidate = build_candidates(d)[0]
        self.assertEqual(candidate["levels"], ["apex", "mid"])
        self.assertEqual(candidate["sectors_in"], ["pzpl_mid_ls"])
        self.assertEqual(candidate["depends_on"], ["group:g1"])
        self.assertEqual(candidate["side_basis"], "inferred")

    def test_not_lesion_excluded_even_if_in_group(self):
        d = drawing(mark())
        d["not_lesion"] = [{"mark": "mid.m1", "reason": "text"}]
        self.assertEqual(build_candidates(d), [])

    def test_missing_redcap_uses_crosswalk(self):
        m = mark()
        del m["sectors_polygon"][0]["redcap"]
        self.assertEqual(build_candidates(drawing(m))[0]["sectors_in"], ["pzpl_mid_ls"])


class MatchingTests(unittest.TestCase):
    def test_global_assignment_matches_bruteforce_and_keeps_runner_up(self):
        r = report("a", "b")
        locate(r, "a", "left")
        locate(r, "b", "right")
        d = drawing(mark("mid.m1", "left"), mark("mid.m2", "right"), mark("mid.m3", "left"))
        candidates = build_candidates(d)
        # Group candidates disable the optional standalone extension in this oracle.
        for c in candidates:
            c.update(standalone=False, source="group:" + c["id"])
        scores = []
        for assignment in itertools.product([None, "c1", "c2", "c3"], repeat=2):
            selected = [cid for cid in assignment if cid]
            if len(set(selected)) != len(selected):
                continue
            total = sum(pair_score(r, {"id": fid}, next(c for c in candidates if c["id"] == cid))[0]
                        for fid, cid in zip(("a", "b"), assignment) if cid)
            scores.append(total)
        scores.sort(reverse=True)
        matching = match(r, candidates)
        self.assertEqual(matching["total_score"], scores[0])
        self.assertEqual(matching["runner_up_score"], scores[1])
        self.assertEqual(matching["certainty"], "low")

    def test_extra_standalone_same_side_penalty(self):
        r = report("a")
        locate(r, "a")
        c = build_candidates(drawing(mark(), mark("mid.m2")))
        result = match(r, c)
        self.assertEqual(set(result["best_assignment"]["a"]), {"c1", "c2"})
        self.assertEqual(result["total_score"], 11)  # 6 + 6 - 1
        c[1]["sides"] = ["right"]
        self.assertLessEqual(len(match(r, c)["best_assignment"]["a"]), 1)

    def test_negative_pair_can_remain_unmatched(self):
        r = report("a")
        locate(r, "a", "left", ("apex",), ("tz",), "anterior")
        result = match(r, build_candidates(drawing(mark(side="right"))))
        self.assertEqual(result["best_assignment"], {"a": []})

    def test_fixed_split_ids_allow_more_than_two_preserve_certainty(self):
        r = report("a")
        locate(r, "a")
        c = build_candidates(drawing(mark(), mark("mid.m2"), mark("mid.m3")))
        for candidate in c:
            candidate["id"] += "~split"
        ids = [candidate["id"] for candidate in c]
        prior = {"hypotheses": [{"focus": "a", "candidates": ids, "certainty": "high"}]}
        result = match(r, c, fixed_assignment={"a": ids}, previous_matching=prior)
        self.assertEqual(result["best_assignment"], {"a": ids})
        self.assertIsNone(result["runner_up_assignment"])
        self.assertEqual(result["hypotheses"][0]["certainty"], "high")
        self.assertEqual(len(result["hypotheses"][0]["memberships"]), 4)
        self.assertEqual(result["hypotheses"][0]["memberships"][0]["subject"], "report:a")

    def test_fixed_rejects_duplicate_ownership_or_missing_reference(self):
        r = report("a", "b")
        c = build_candidates(drawing(mark()))
        for assignment in ({"a": ["c1"], "b": ["c1"]}, {"a": ["gone"]}, {"gone": []}):
            with self.assertRaises(ValueError):
                match(r, c, fixed_assignment=assignment)

    def test_certainty_thresholds(self):
        for margin, explicit, expected in ((3, True, "high"), (3, False, "medium"), (1, True, "medium"), (.5, True, "low")):
            self.assertEqual(matching_confidence(margin, 0, explicit), expected)

    def test_size_rank_weak_bonus_and_noncomparability(self):
        r = report("a")
        locate(r, "a")
        obs(r, "a", "dimensions", {"type": "dimensions", "measurements": [{"value": 2, "unit": "cm"}]})
        c = build_candidates(drawing(mark()))
        result = match(r, c)
        self.assertEqual(result["total_score"], 6.5)
        self.assertEqual(result["comparisons"][-1]["outcome"], "not comparable")


class MatchingMetadataTests(unittest.TestCase):
    def test_unavailable_report_observation_is_no_counterpart_and_retains_status(self):
        for status in ("not reported", "unreadable", "not assessed", "not applicable"):
            with self.subTest(status=status):
                r = report("a")
                locate(r, "a", side=None)
                missing = obs(r, "a", "laterality", status=status)
                candidate = build_candidates(drawing(mark()))[0]
                score, comparisons = pair_score(r, {"id": "a"}, candidate)
                side = next(item for item in comparisons if item["property"] == "laterality")
                self.assertEqual(side["outcome"], "no counterpart")
                self.assertEqual(side["score"], 0.0)
                self.assertEqual(side["report_ref"], "report:" + missing["id"])
                self.assertEqual(side["report_status"], status)
                self.assertEqual(side["input_observations"][0]["status"], status)
                self.assertIn("report:" + missing["id"], side["inputs"])
                self.assertIn(status, side["explanation"])
                self.assertEqual(score, 3.0)  # level + zone + anteroposterior still agree

    def test_absent_drawing_location_and_orientation_stays_indeterminate(self):
        r = report("a")
        locate(r, "a")
        candidate = build_candidates(drawing(mark()))[0]
        for field in ("sides", "levels", "zones", "anteroposterior"):
            candidate[field] = []
        candidate["side_basis"] = "inferred"
        score, comparisons = pair_score(r, {"id": "a"}, candidate)
        self.assertEqual(score, 0.0)
        for comparison in comparisons[:-1]:
            self.assertEqual(comparison["outcome"], "indeterminate")
            self.assertEqual(comparison["score"], 0.0)
        self.assertIn("orientation", comparisons[0]["explanation"])
        self.assertIn("not no counterpart", comparisons[0]["explanation"])

    def test_hypothesis_metadata_reflects_scored_agreement_and_inferred_orientation(self):
        r = report("a")
        locate(r, "a")
        d = drawing(mark())
        d["views"][0]["orientation"]["basis"] = "inferred"
        result = match(r, build_candidates(d))
        hypothesis = result["hypotheses"][0]
        self.assertIn("c1", hypothesis["rationale"])
        self.assertIn("+3.0", hypothesis["rationale"])
        self.assertTrue(any("inferred" in note.lower() for note in hypothesis["opposing_considerations"]))
        self.assertTrue(any("orientation" in note.lower() for note in hypothesis["assumptions"]))
        for comparison in result["comparisons"]:
            self.assertTrue(comparison["explanation"])
            self.assertTrue(comparison["assumptions"])
            self.assertIn(comparison["review_status"], {"unreviewed", "needs_review"})
        member = next(item for item in hypothesis["memberships"] if item["subject"] == "mid.m1")
        self.assertEqual(member["review_status"], "unreviewed")
        self.assertEqual(member["opposes"], [])
        self.assertIn("c1", member["rationale"])
        self.assertTrue(hypothesis["memberships"][0]["rationale"])

    def test_fixed_conflict_metadata_names_opposition_and_requests_review(self):
        r = report("a")
        locate(r, "a", "left", ("apex",), ("tz",), "anterior")
        d = drawing(mark(side="right"))
        d["views"][0]["orientation"]["basis"] = "inferred"
        result = match(r, build_candidates(d), fixed_assignment={"a": ["c1"]})
        hypothesis = result["hypotheses"][0]
        self.assertEqual(hypothesis["certainty"], "low")
        self.assertIn("-6.0", hypothesis["rationale"])
        self.assertTrue(any("conflict" in note.lower() for note in hypothesis["opposing_considerations"]))
        for comparison in result["comparisons"]:
            if comparison["property"] != "size_rank":
                self.assertEqual(comparison["review_status"], "needs_review")
        report_member = hypothesis["memberships"][0]
        self.assertEqual(report_member["review_status"], "needs_review")
        self.assertIn("mid.m1", report_member["opposes"])
        diagram_member = next(item for item in hypothesis["memberships"] if item["subject"] == "mid.m1")
        self.assertEqual(diagram_member["review_status"], "needs_review")
        self.assertTrue(any(ref.startswith("report:") for ref in diagram_member["opposes"]))
        self.assertIn("needs review", diagram_member["rationale"])

    def test_report_membership_opposes_only_the_conflicting_candidate_marks(self):
        r = report("a")
        locate(r, "a", "left", ("mid",), ("pz",), "posterior")
        d = drawing(mark("mid.m1"), mark("mid.m2", side="right", zone="tza", level="apex"))
        result = match(r, build_candidates(d), fixed_assignment={"a": ["c1", "c2"]})
        hypothesis = result["hypotheses"][0]
        self.assertEqual(hypothesis["memberships"][0]["opposes"], ["mid.m2"])
        self.assertTrue(any("selected candidates depict one focus" in note
                            for note in hypothesis["assumptions"]))
        members = {member["subject"]: member for member in hypothesis["memberships"]}
        self.assertEqual(members["mid.m1"]["review_status"], "unreviewed")
        self.assertEqual(members["mid.m2"]["review_status"], "needs_review")

    def test_assumptions_name_group_and_reviewer_decision_dependencies(self):
        r = report("a")
        locate(r, "a")
        d = drawing(mark(), mark("mid.m2"))
        d["groups"] = [{"id": "g1", "members": ["mid.m1", "mid.m2"]}]
        d["standalone"] = []
        candidate = build_candidates(d)[0]
        grouped = match(r, [candidate], fixed_assignment={"a": ["c1"]})["hypotheses"][0]
        self.assertTrue(any("group:g1 grouping its marks" in note for note in grouped["assumptions"]))
        candidate["depends_on"] = ["decision:d1"]
        reviewed = match(r, [candidate], fixed_assignment={"a": ["c1"]})["hypotheses"][0]
        self.assertTrue(any("reviewer membership decision decision:d1" in note
                            for note in reviewed["assumptions"]))


class InterpretationTests(unittest.TestCase):
    def test_inferred_sectors_require_all_location_components(self):
        r = report("a")
        locate(r, "a", levels=("apex",))
        result, _ = interpret(r, drawing())
        self.assertEqual(result["lesions"][0]["sectors"]["in"], ["pza_apex_ls", "pzpl_apex_ls", "pzpm_apex_ls"])
        self.assertEqual(result["lesions"][0]["sectors"]["confidence"]["final"], "low")
        self.assertIn("inferred_sectors", [i["kind"] for i in result["issues"]])
        r["extraction"]["observations"] = r["extraction"]["observations"][:1]
        result, _ = interpret(r, drawing())
        self.assertEqual(result["lesions"][0]["sectors"]["in"], [])

    def test_dominant_order_scope_and_full_statuses(self):
        r = report("a", "b")
        obs(r, "b", "dominant", {"type": "presence", "value": "present"})
        for prop, status in (("grade_group", "not reported"), ("dimensions", "unreadable"),
                             ("gleason_patterns", "not assessed"), ("histology_type", "not applicable")):
            obs(r, "a", prop, status=status)
        obs(r, "a", "perineural_invasion", {"type": "presence", "value": "absent"})
        obs(r, "spec", "classification_r", {"type": "classification", "original_code": "R0"})
        result, _ = interpret(r, drawing())
        self.assertEqual([l["focus"] for l in result["lesions"]], ["b", "a"])
        props = result["lesions"][1]["properties"]
        self.assertEqual({p["status"] for p in props}, {"recorded", "not reported", "unreadable", "not assessed", "not applicable"})
        self.assertFalse(any(p["property"] == "classification_r" for p in props))
        self.assertTrue(all(p["supports"][0].startswith("report:") for p in props))
        self.assertTrue(all("value" not in p for p in props if p["status"] != "recorded"))

    def test_fallback_count_multifocality_zero_and_count_mismatch(self):
        d = drawing(mark(), mark("mid.m2"))
        for prop, value, expected in (("reported_lesion_count", {"type": "quantity", "value": 1}, 2),
                                      ("multifocality", {"type": "coded", "code": "multifocal"}, 2),
                                      ("reported_lesion_count", {"type": "quantity", "value": 0}, 0)):
            with self.subTest(prop=prop, value=value):
                r = report()
                entry = obs(r, "spec", prop, value)
                result, _ = interpret(r, d)
                self.assertEqual(len(result["lesions"]), expected)
                if expected:
                    self.assertIn("report:" + entry["id"], result["lesions"][0]["supports"])
                    self.assertIn("lesion_from_drawing", [i["kind"] for i in result["issues"]])
                if prop == "reported_lesion_count" and expected:
                    self.assertIn("count_mismatch", [i["kind"] for i in result["issues"]])
        result, _ = interpret(report(), d)
        self.assertEqual(result["lesions"], [])
        self.assertEqual(len(result["issues"]), 2)

    def test_other_finding_absorbs_leftovers(self):
        r = report()
        r["extraction"]["subjects"].append({"id": "inflammation", "kind": "other_finding"})
        locate(r, "inflammation")
        result, _ = interpret(r, drawing(mark()))
        self.assertEqual(result["lesions"], [])
        self.assertEqual(result["other_findings"][0]["candidates"], ["c1"])
        self.assertNotIn("unmatched_candidate", [i["kind"] for i in result["issues"]])

    def test_fixed_conflicts_retain_both_sources_without_selected_value(self):
        r = report("a")
        locate(r, "a", "left", ("apex",), ("pz",), "anterior")
        original = copy.deepcopy(r)
        result, _ = interpret(r, drawing(mark(side="right")), {"a": ["c1"]})
        lesion = result["lesions"][0]
        self.assertEqual(lesion["sectors"]["confidence"]["final"], "conflict")
        kinds = {i["kind"] for i in result["issues"]}
        self.assertTrue({"side_conflict", "ap_conflict", "level_conflict"} <= kinds)
        self.assertNotIn("ambiguous_assignment", kinds)
        for prop in lesion["properties"]:
            if prop["property"] in {"laterality", "level", "anteroposterior"}:
                self.assertEqual(prop["disposition"], "unresolved")
                self.assertEqual(len(prop["candidates"]), 2)
                self.assertNotIn("value", prop)
        self.assertEqual(r, original)

    def test_unchanged_fixed_lesion_uses_previous_hypothesis_certainty(self):
        r = report("a", "b")
        locate(r, "a", "left")
        locate(r, "b", "right")
        d = drawing(mark(), mark("mid.m2", "right"))
        first, previous = interpret(r, d)
        after, _ = interpret(r, d, previous["best_assignment"], previous)
        self.assertEqual(first["lesions"], after["lesions"])

    def test_cv_signal_degrades_containing_mark_confidence(self):
        r = report("a")
        locate(r, "a")
        m = mark()
        m["cv_regions"] = ["mid.cv1"]
        d = drawing(m)
        d["signals"] = [{"kind": "sources_disagree", "observations": ["mid.cv1"],
                         "reason": "CV sector differs", "suggestion": "would flag"}]
        result, _ = interpret(r, d)
        self.assertEqual(result["lesions"][0]["sectors"]["confidence"]["final"], "low")
        self.assertIn("sources_disagree", [i["kind"] for i in result["issues"]])

    def test_mild_instability_info_and_unknown_ink_question(self):
        r = report("a")
        locate(r, "a")
        m = mark()
        m["runs_found"] = 2
        unknown = mark("mid.unknown", "right")
        d = drawing(m, unknown)
        d["standalone"] = d["standalone"][:1]
        d["signals"] = [
            {"kind": "run_instability", "observations": [m["id"]], "reason": "2/3 runs", "suggestion": "would flag"},
            {"kind": "unknown_ink", "observations": [unknown["id"]], "reason": "Unassigned ink", "suggestion": "info only"},
            {"kind": "single_source", "observations": ["unused.m1"], "reason": "Unused", "suggestion": "info only"}]
        result, _ = interpret(r, d)
        kinds = {i["kind"]: i for i in result["issues"]}
        self.assertEqual(kinds["run_instability"]["severity"], "info")
        self.assertEqual(kinds["unknown_ink"]["severity"], "question")
        self.assertEqual(result["lesions"][0]["sectors"]["confidence"]["final"], "medium")
        self.assertEqual(result["details"][0]["signal"]["kind"], "single_source")

    def test_linked_size_units_tolerance_and_unassessed_unitless_note(self):
        r = report("a")
        locate(r, "a")
        obs(r, "a", "dimensions", {"type": "dimensions", "measurements": [{"value": 10, "unit": "mm"}, {"value": 20, "unit": "mm"}]})
        for text, conflict in (("1,2 cm", False), ("13 mm", True), ("10 × 20 mm", False), ("30", False)):
            with self.subTest(text=text):
                note = mark("mid.note")
                note.update(kind="text", text=text, linked_to={"mark": "mid.m1"})
                d = drawing(mark(), note)
                d["standalone"] = d["standalone"][:1]
                result, _ = interpret(r, d)
                self.assertEqual("size_note_conflict" in [i["kind"] for i in result["issues"]], conflict)
                if text == "30":
                    self.assertEqual(result["details"][0]["certainty"], "unassessed")
                self.assertEqual(result["lesions"][0]["properties"][-1]["value"]["measurements"][0]["value"], 10)


if __name__ == "__main__":
    unittest.main()
