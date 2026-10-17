"""Consistency checks report contradictions without changing any recorded value."""

from __future__ import annotations

import unittest
from copy import deepcopy

from central.checks import run_checks

PT2C_RULE = "pt2c-both-lobes"
PT2AB_RULE = "pt2ab-one-lobe"
PT3A_RULE = "pt3a-epe"
PT3B_RULE = "pt3b-seminal-vesicles"
GRADE_RULE = "isup-grade-group"


def subject(subject_id: str, kind: str) -> dict:
    return {"id": subject_id, "kind": kind, "label": subject_id,
            "identification_basis": "explicit", "parent_id": None, "evidence_ids": ["e1"]}


def observation(subject_id: str, property_name: str, value: dict | None,
                status: str = "recorded", observation_id: str | None = None) -> dict:
    return {
        "id": observation_id or f"o-{subject_id}-{property_name}",
        "subject_id": subject_id,
        "property": property_name,
        "status": status,
        "basis": "explicit",
        "value": value,
        "evidence_ids": ["e1"] if status == "recorded" else [],
        "derived_from": [],
        "review_status": "unreviewed",
        "certainty": {"extraction": "high", "interpretation": "high"},
        "unavailable_reason": None if status == "recorded" else "not stated",
    }


def presence(value: str) -> dict:
    return {"type": "presence", "value": value, "original_wording": value}


def coded(code) -> dict:
    return {"type": "coded", "code": code, "original_wording": str(code)}


def classification(code: str) -> dict:
    return {"type": "classification", "original_code": code, "classification_system": "TNM",
            "edition": "8th", "normalized_code": None}


def patterns(primary: int, secondary: int, *, old_shape: bool = False) -> dict:
    if old_shape:
        return {"type": "gleason_patterns", "primary_pattern": primary,
                "secondary_pattern": secondary, "original_wording": f"{primary}+{secondary}"}
    return {"type": "gleason_patterns",
            "primary": {"pattern": primary, "percent": None},
            "secondary": {"pattern": secondary, "percent": None},
            "tertiary": None,
            "original_wording": f"{primary}+{secondary}"}


def report(*observations: dict, foci: tuple[str, ...] = ("focus-a",)) -> dict:
    subjects = [subject("specimen", "specimen")]
    subjects.extend(subject(focus, "tumour_focus") for focus in foci)
    return {"extraction": {"subjects": subjects, "observations": list(observations), "evidence": [],
                           "coverage": [], "issues": []}}


def lesion(ident: str, *sectors: str) -> dict:
    return {"id": ident, "sectors": {"in": list(sectors), "maybe": [], "basis": "inferred"}}


def candidate(ident: str, *sides: str, sectors: tuple[str, ...] = ()) -> dict:
    return {"id": ident, "sides": list(sides), "sectors_in": list(sectors)}


def issues_for(report_data: dict, lesions=(), candidates=()) -> list[dict]:
    return run_checks(report_data, list(lesions), list(candidates))


def only_issue(test: unittest.TestCase, result: list[dict]) -> dict:
    test.assertEqual(len(result), 1, result)
    issue = result[0]
    test.assertEqual(issue["kind"], "check_failed")
    test.assertEqual(set(issue), {"kind", "severity", "context", "reason", "rule"})
    test.assertEqual(set(issue["rule"]), {"id", "source", "edition"})
    test.assertTrue(issue["rule"]["source"])
    test.assertTrue(issue["rule"]["edition"])
    return issue


class GradeGroupTests(unittest.TestCase):
    def test_focus_grade_group_match_raises_nothing(self):
        result = issues_for(report(
            observation("focus-a", "gleason_patterns", patterns(3, 4)),
            observation("focus-a", "grade_group", coded("2")),
        ))
        self.assertEqual(result, [])

    def test_focus_grade_group_mismatch_is_a_question(self):
        issue = only_issue(self, issues_for(report(
            observation("focus-a", "gleason_patterns", patterns(3, 4)),
            observation("focus-a", "grade_group", coded("3")),
        )))
        self.assertEqual(issue["severity"], "question")
        self.assertEqual(issue["rule"]["id"], GRADE_RULE)
        self.assertIn("focus-a", issue["context"])
        self.assertIn("2", issue["reason"])

    def test_specimen_grade_group_is_checked_at_specimen_scope(self):
        result = issues_for(report(
            observation("specimen", "gleason_patterns", patterns(4, 4)),
            observation("specimen", "grade_group", coded("1")),
            observation("focus-a", "gleason_patterns", patterns(3, 4)),
            observation("focus-a", "grade_group", coded("2")),
        ))
        issue = only_issue(self, result)
        self.assertIn("specimen", issue["context"])
        self.assertNotIn("focus-a", issue["context"])
        self.assertIn("specimen", issue["reason"])

    def test_legacy_gleason_shape_is_read(self):
        result = issues_for(report(
            observation("focus-a", "gleason_patterns", patterns(4, 3, old_shape=True)),
            observation("focus-a", "grade_group", coded("3")),
        ))
        self.assertEqual(result, [])

    def test_not_reported_grade_group_is_not_a_failure(self):
        result = issues_for(report(
            observation("focus-a", "gleason_patterns", patterns(3, 4)),
            observation("focus-a", "grade_group", None, status="not reported"),
        ))
        self.assertEqual(result, [])

    def test_unfamiliar_grade_values_are_left_alone(self):
        result = issues_for(report(
            observation("focus-a", "gleason_patterns", patterns(3, 4)),
            observation("focus-a", "grade_group", coded("not sure")),
        ))
        self.assertEqual(result, [])

    def test_grade_group_without_gleason_is_not_checked(self):
        result = issues_for(report(
            observation("focus-a", "grade_group", coded("3")),
        ))
        self.assertEqual(result, [])

    def test_gleason_7_order_matters(self):
        self.assertEqual(issues_for(report(
            observation("focus-a", "gleason_patterns", patterns(4, 3)),
            observation("focus-a", "grade_group", coded("3")),
        )), [])
        issue = only_issue(self, issues_for(report(
            observation("focus-a", "gleason_patterns", patterns(4, 3)),
            observation("focus-a", "grade_group", coded("2")),
        )))
        self.assertEqual(issue["severity"], "question")

    def test_gleason_8_9_and_10_map_to_groups_4_and_5(self):
        for score, group in ((8, "4"), (9, "5"), (10, "5")):
            with self.subTest(score=score):
                self.assertEqual(issues_for(report(
                    observation("focus-a", "gleason_patterns", patterns(4, 4 if score == 8 else 5)),
                    observation("focus-a", "grade_group", coded(group)),
                )), [])


class PtSideTests(unittest.TestCase):
    def test_pt2c_with_one_side_is_info(self):
        issue = only_issue(self, issues_for(
            report(observation("specimen", "classification_pt", classification("pT2c"))),
            [lesion("L1", "pzpl_mid_rs")],
            [candidate("c1", "right")],
        ))
        self.assertEqual(issue["severity"], "info")
        self.assertEqual(issue["rule"]["id"], PT2C_RULE)
        self.assertIn("pT2c", issue["reason"])

    def test_pt2c_with_both_sides_is_not_a_failure(self):
        result = issues_for(
            report(observation("specimen", "classification_pt", classification("pT2c"))),
            [lesion("L1", "pzpl_mid_rs")],
            [candidate("c1", "left")],
        )
        self.assertEqual(result, [])

    def test_pt2c_with_an_unknown_candidate_side_is_not_a_failure(self):
        result = issues_for(
            report(observation("specimen", "classification_pt", classification("pT2c"))),
            [lesion("L1", "pzpl_mid_rs")],
            [candidate("c1")],
        )
        self.assertEqual(result, [])

    def test_pt2a_with_lesions_on_both_sides_is_info(self):
        issue = only_issue(self, issues_for(
            report(observation("specimen", "classification_pt", classification("pT2a"))),
            [lesion("L1", "pzpl_mid_rs"), lesion("L2", "pzpl_mid_ls")],
        ))
        self.assertEqual(issue["severity"], "info")
        self.assertEqual(issue["rule"]["id"], PT2AB_RULE)

    def test_pt2a_with_one_side_is_not_a_failure(self):
        result = issues_for(
            report(observation("specimen", "classification_pt", classification("pT2a"))),
            [lesion("L1", "pzpl_mid_rs")],
        )
        self.assertEqual(result, [])

    def test_pt2b_candidates_do_not_extend_lesion_scope(self):
        result = issues_for(
            report(observation("specimen", "classification_pt", classification("pT2b"))),
            [lesion("L1", "pzpl_mid_rs")],
            [candidate("c1", "left")],
        )
        self.assertEqual(result, [])

    def test_maybe_sector_is_ignored_for_lesion_side(self):
        maybe_left = {"id": "L1", "sectors": {"in": ["pzpl_mid_rs"], "maybe": ["pzpl_mid_ls"]}}
        self.assertEqual(issues_for(
            report(observation("specimen", "classification_pt", classification("pT2a"))),
            [maybe_left],
        ), [])
        issue = only_issue(self, issues_for(
            report(observation("specimen", "classification_pt", classification("pT2c"))),
            [maybe_left],
        ))
        self.assertEqual(issue["rule"]["id"], PT2C_RULE)

    def test_maybe_sector_is_ignored_for_candidate_side(self):
        maybe_left = candidate("c1", "right", sectors=("pzpl_mid_rs",))
        maybe_left["sectors_maybe"] = ["pzpl_mid_ls"]
        issue = only_issue(self, issues_for(
            report(observation("specimen", "classification_pt", classification("pT2c"))),
            [lesion("L1", "pzpl_mid_rs")],
            [maybe_left],
        ))
        self.assertEqual(issue["rule"]["id"], PT2C_RULE)

    def test_bilateral_lesion_counts_as_both_sides(self):
        issue = only_issue(self, issues_for(
            report(observation("specimen", "classification_pt", classification("pT2a"))),
            [{"id": "L1", "sides": ["bilateral"]}],
        ))
        self.assertEqual(issue["rule"]["id"], PT2AB_RULE)
        result = issues_for(
            report(observation("specimen", "classification_pt", classification("pT2c"))),
            [{"id": "L1", "sides": ["bilateral"]}],
        )
        self.assertEqual(result, [])

    def test_pt2_side_unknown_is_not_a_failure(self):
        result = issues_for(
            report(observation("specimen", "classification_pt", classification("pT2c"))),
            [lesion("L1")],
        )
        self.assertEqual(result, [])


class PtInvasionTests(unittest.TestCase):
    def test_pt3a_with_epe_absent_is_info(self):
        issue = only_issue(self, issues_for(report(
            observation("specimen", "classification_pt", classification("pT3a")),
            observation("focus-a", "extraprostatic_extension", presence("absent")),
        )))
        self.assertEqual(issue["severity"], "info")
        self.assertEqual(issue["rule"]["id"], PT3A_RULE)
        self.assertIn("focus-a", issue["context"])

    def test_pt3a_with_epe_present_is_not_a_failure(self):
        result = issues_for(report(
            observation("specimen", "classification_pt", classification("pT3a")),
            observation("focus-a", "extraprostatic_extension", presence("present")),
        ))
        self.assertEqual(result, [])

    def test_pt3a_with_unassessed_epe_is_not_a_failure(self):
        result = issues_for(report(
            observation("specimen", "classification_pt", classification("pT3a")),
            observation("focus-a", "extraprostatic_extension", None, status="not reported"),
        ))
        self.assertEqual(result, [])

    def test_pt3a_requires_all_foci_to_be_assessed_absent(self):
        result = issues_for(report(
            observation("specimen", "classification_pt", classification("pT3a")),
            observation("focus-a", "extraprostatic_extension", presence("absent")),
            observation("focus-b", "extraprostatic_extension", None, status="not reported"),
            foci=("focus-a", "focus-b"),
        ))
        self.assertEqual(result, [])

    def test_pt3b_with_seminal_vesicle_invasion_absent_is_info(self):
        issue = only_issue(self, issues_for(report(
            observation("specimen", "classification_pt", classification("pT3b")),
            observation("specimen", "seminal_vesicle_invasion", presence("absent")),
        )))
        self.assertEqual(issue["severity"], "info")
        self.assertEqual(issue["rule"]["id"], PT3B_RULE)

    def test_pt3b_with_seminal_vesicle_invasion_present_is_not_a_failure(self):
        result = issues_for(report(
            observation("specimen", "classification_pt", classification("pT3b")),
            observation("specimen", "seminal_vesicle_invasion", presence("present")),
        ))
        self.assertEqual(result, [])

    def test_pt3b_with_unknown_seminal_vesicle_status_is_not_a_failure(self):
        result = issues_for(report(
            observation("specimen", "classification_pt", classification("pT3b")),
            observation("specimen", "seminal_vesicle_invasion", None, status="not reported"),
        ))
        self.assertEqual(result, [])


class SafetyTests(unittest.TestCase):
    def test_checks_do_not_change_values(self):
        report_data = report(
            observation("specimen", "classification_pt", classification("pT3a")),
            observation("specimen", "grade_group", coded("1")),
            observation("specimen", "gleason_patterns", patterns(4, 4)),
            observation("focus-a", "extraprostatic_extension", presence("absent")),
        )
        lesions = [lesion("L1", "pzpl_mid_rs")]
        candidates = [candidate("c1", "right")]
        before = deepcopy((report_data, lesions, candidates))
        run_checks(report_data, lesions, candidates)
        self.assertEqual((report_data, lesions, candidates), before)

    def test_extraction_without_bundle_is_accepted(self):
        report_data = report(
            observation("specimen", "classification_pt", classification("pT2c")),
        )
        result = run_checks(report_data["extraction"], [lesion("L1", "pzpl_mid_rs")], [])
        self.assertEqual(len(result), 1)

    def test_unfamiliar_pt_code_is_not_a_failure(self):
        result = issues_for(report(
            observation("specimen", "classification_pt", classification("pT?")),
        ), [lesion("L1", "pzpl_mid_rs")])
        self.assertEqual(result, [])

    def test_reviewed_computation_copy_is_read(self):
        base = report(
            observation("specimen", "classification_pt", classification("pT3b")),
            observation("specimen", "seminal_vesicle_invasion", presence("absent")),
        )
        base["extraction"]["observations"][1]["review_decision"] = "review-1"
        self.assertEqual(len(issues_for(base)), 1)
        changed = deepcopy(base)
        changed["extraction"]["observations"][1].update(
            value=presence("present"), review_decision="review-1")
        self.assertEqual(issues_for(changed), [])

    def test_empty_inputs_raise_nothing(self):
        self.assertEqual(run_checks({}, [], []), [])

    def test_missing_side_keys_raise_nothing(self):
        result = issues_for(
            report(observation("specimen", "classification_pt", classification("pT2c"))),
            [{"id": "L1"}],
            [{"id": "c1"}],
        )
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
